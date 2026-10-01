from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone
from finance.services import post_sales_payment, reverse_sales_payment

from inventory.models import (
    StockLocation,
    StockLot,
    StockMovementType,
)
from inventory.services import record_stock_movement

from .models import (
    SalesOrder,
    SalesOrderItem,
    SalesOrderItemAllocation,
    SalesOrderPayment,
    SalesOrderStatus,
    SalesPaymentStatus,
)


def _locked_order(sales_order):
    if sales_order.pk is None:
        raise ValidationError(
            'Salve o pedido antes de executar esta operação.',
        )

    return (
        SalesOrder.objects
        .select_for_update()
        .get(pk=sales_order.pk)
    )


def _validate_order_items(sales_order):
    items = list(
        sales_order.items.select_related(
            'item',
            'commercial_unit',
        )
    )

    if not items:
        raise ValidationError(
            'Adicione pelo menos um item ao pedido.',
        )

    for order_item in items:
        order_item.full_clean()

    if sales_order.total_amount <= 0:
        raise ValidationError(
            'O valor total do pedido precisa ser maior que zero.',
        )

    return items


@transaction.atomic
def confirm_sales_order(*, sales_order):
    sales_order = _locked_order(sales_order)

    if sales_order.status != SalesOrderStatus.DRAFT:
        raise ValidationError(
            'Somente um pedido em rascunho pode ser confirmado.',
        )

    _validate_order_items(sales_order)

    sales_order.status = SalesOrderStatus.CONFIRMED
    sales_order.full_clean()
    sales_order.save()

    return sales_order


@transaction.atomic
def mark_sales_order_in_production(*, sales_order):
    sales_order = _locked_order(sales_order)

    if sales_order.status != SalesOrderStatus.CONFIRMED:
        raise ValidationError(
            'Somente um pedido confirmado pode entrar em produção.',
        )

    sales_order.status = SalesOrderStatus.IN_PRODUCTION
    sales_order.full_clean()
    sales_order.save()

    return sales_order


@transaction.atomic
def mark_sales_order_ready(*, sales_order):
    sales_order = _locked_order(sales_order)

    allowed_statuses = {
        SalesOrderStatus.CONFIRMED,
        SalesOrderStatus.IN_PRODUCTION,
    }

    if sales_order.status not in allowed_statuses:
        raise ValidationError(
            'Somente um pedido confirmado ou em produção '
            'pode ser marcado como pronto.',
        )

    sales_order.status = SalesOrderStatus.READY
    sales_order.full_clean()
    sales_order.save()

    return sales_order

@transaction.atomic
def allocate_sales_order_stock(
    *,
    sales_order,
    source_location,
):
    sales_order = _locked_order(sales_order)

    allowed_statuses = {
        SalesOrderStatus.CONFIRMED,
        SalesOrderStatus.IN_PRODUCTION,
        SalesOrderStatus.READY,
    }

    if sales_order.status not in allowed_statuses:
        raise ValidationError(
            'O pedido precisa estar confirmado, em produção '
            'ou pronto para separar o estoque.',
        )

    if source_location is None or source_location.pk is None:
        raise ValidationError(
            'Selecione um local de separação do estoque no pedido.',
        )
    source_location = (
        StockLocation.objects
        .select_for_update()
        .get(pk=source_location.pk)
    )

    if not source_location.is_active:
        raise ValidationError(
            'O local de origem do estoque está inativo.',
        )

    order_items = list(
        sales_order.items
        .select_for_update(of=('self',))
        .select_related(
            'item',
            'item__base_unit',
        )
    )

    if not order_items:
        raise ValidationError(
            'O pedido não possui itens.',
        )

    active_order_statuses = {
        SalesOrderStatus.CONFIRMED,
        SalesOrderStatus.IN_PRODUCTION,
        SalesOrderStatus.READY,
    }
    created_allocations = []

    for order_item in order_items:
        if not order_item.item.tracks_inventory:
            continue

        if order_item.stock_allocations.exists():
            raise ValidationError(
                f'{order_item.item} já possui estoque separado. '
                'Revise ou remova as separações existentes.',
            )

        remaining_quantity = order_item.base_quantity

        lots = (
            StockLot.objects
            .select_for_update(of=('self',))
            .filter(
                item=order_item.item,
                is_active=True,
                is_blocked=False,
            )
            .filter(
                Q(expiration_date__isnull=True)
                | Q(expiration_date__gte=timezone.localdate())
            )
            .order_by(
                F('expiration_date').asc(nulls_last=True),
                'received_date',
                'id',
            )
        )

        for stock_lot in lots:
            available_quantity = stock_lot.quantity_at(
                source_location,
            )

            reserved_quantity = (
                SalesOrderItemAllocation.objects
                .filter(
                    stock_lot=stock_lot,
                    source_location=source_location,
                    dispatch_movement__isnull=True,
                    sales_order_item__sales_order__status__in=(
                        active_order_statuses
                    ),
                )
                .aggregate(total=Sum('quantity'))['total']
                or Decimal('0.000000')
            )

            available_to_allocate = (
                available_quantity - reserved_quantity
            )

            if available_to_allocate <= 0:
                continue

            if stock_lot.unit_cost is None:
                raise ValidationError(
                    f'Informe o custo do lote {stock_lot.code} '
                    'antes de utilizá-lo em uma venda.',
                )

            allocated_quantity = min(
                remaining_quantity,
                available_to_allocate,
            )

            allocation = SalesOrderItemAllocation(
                sales_order_item=order_item,
                stock_lot=stock_lot,
                source_location=source_location,
                quantity=allocated_quantity,
                unit_cost=stock_lot.unit_cost,
            )
            allocation.full_clean()
            allocation.save()
            created_allocations.append(allocation)

            remaining_quantity -= allocated_quantity

            if remaining_quantity <= 0:
                break

        if remaining_quantity > 0:
            unit_symbol = order_item.item.base_unit.symbol

            raise ValidationError(
                f'Estoque insuficiente para {order_item.item}. '
                f'Faltam {remaining_quantity} {unit_symbol}.',
            )

    return created_allocations


@transaction.atomic
def clear_sales_order_stock_allocations(*, sales_order):
    sales_order = _locked_order(sales_order)

    if sales_order.status in {
        SalesOrderStatus.COMPLETED,
        SalesOrderStatus.CANCELLED,
    }:
        raise ValidationError(
            'Não é possível limpar separações de um pedido '
            'concluído ou cancelado.',
        )

    allocations = (
        SalesOrderItemAllocation.objects
        .select_for_update()
        .filter(sales_order_item__sales_order=sales_order)
    )

    if allocations.filter(
        dispatch_movement__isnull=False,
    ).exists():
        raise ValidationError(
            'Existe uma saída de estoque registrada '
            'e a separação não pode ser removida.',
        )

    deleted_count, _ = allocations.delete()

    return deleted_count

@transaction.atomic
def complete_sales_order(
    *,
    sales_order,
    user=None,
    completed_at=None,
):
    sales_order = _locked_order(sales_order)

    if sales_order.status != SalesOrderStatus.READY:
        raise ValidationError(
            'Somente um pedido pronto pode ser concluído.',
        )

    order_items = _validate_order_items(sales_order)
    tracked_items = [
        order_item
        for order_item in order_items
        if order_item.item.tracks_inventory
    ]

    allocations = list(
        SalesOrderItemAllocation.objects
        .select_for_update(of=('self',))
        .select_related(
            'sales_order_item',
            'sales_order_item__item',
            'stock_lot',
            'stock_lot__item',
            'source_location',
            'dispatch_movement',
            'return_movement',
        )
        .filter(
            sales_order_item__sales_order=sales_order,
        )
    )

    allocations_by_item = {}

    for allocation in allocations:
        allocations_by_item.setdefault(
            allocation.sales_order_item_id,
            [],
        ).append(allocation)

    for order_item in tracked_items:
        item_allocations = allocations_by_item.get(
            order_item.pk,
            [],
        )
        allocated_quantity = sum(
            (
                allocation.quantity
                for allocation in item_allocations
            ),
            Decimal('0.000000'),
        )

        if allocated_quantity != order_item.base_quantity:
            unit_symbol = order_item.item.base_unit.symbol

            raise ValidationError(
                f'A separação de {order_item.item} deve totalizar '
                f'{order_item.base_quantity} {unit_symbol}. '
                f'Valor separado: {allocated_quantity} '
                f'{unit_symbol}.',
            )

    movement_time = completed_at or timezone.now()
    reference = f'Venda {sales_order.code}'

    for allocation in allocations:
        if allocation.dispatch_movement_id:
            raise ValidationError(
                'Uma das separações já possui saída de estoque.',
            )

        if allocation.return_movement_id:
            raise ValidationError(
                'Uma das separações já possui devolução registrada.',
            )

        if allocation.unit_cost is None:
            if allocation.stock_lot.unit_cost is None:
                raise ValidationError(
                    f'Informe o custo do lote '
                    f'{allocation.stock_lot.code}.',
                )

            allocation.unit_cost = allocation.stock_lot.unit_cost

        movement = record_stock_movement(
            lot=allocation.stock_lot,
            movement_type=StockMovementType.SALE_DISPATCH,
            quantity=allocation.quantity,
            source_location=allocation.source_location,
            occurred_at=movement_time,
            reference=reference,
            user=user,
            notes=(
                'Saída de produto entregue ao cliente '
                f'no pedido {sales_order.code}.'
            ),
        )

        allocation.dispatch_movement = movement
        allocation.full_clean()
        allocation.save()

    sales_order.status = SalesOrderStatus.COMPLETED
    sales_order.completed_at = movement_time
    sales_order.full_clean()
    sales_order.save()

    return sales_order


@transaction.atomic
def cancel_sales_order(
    *,
    sales_order,
    user=None,
    cancelled_at=None,
):
    sales_order = _locked_order(sales_order)

    if sales_order.status == SalesOrderStatus.CANCELLED:
        raise ValidationError(
            'Este pedido já está cancelado.',
        )

    allocations = list(
        SalesOrderItemAllocation.objects
        .select_for_update(of=('self',))
        .select_related(
            'stock_lot',
            'source_location',
            'dispatch_movement',
            'return_movement',
        )
        .filter(
            sales_order_item__sales_order=sales_order,
        )
    )

    movement_time = cancelled_at or timezone.now()
    reference = f'Cancelamento {sales_order.code}'
    return_movements = []

    for allocation in allocations:
        if (
            not allocation.dispatch_movement_id
            or allocation.return_movement_id
        ):
            continue

        return_movement = record_stock_movement(
            lot=allocation.stock_lot,
            movement_type=StockMovementType.CUSTOMER_RETURN,
            quantity=allocation.quantity,
            destination_location=allocation.source_location,
            occurred_at=movement_time,
            reference=reference,
            user=user,
            notes=(
                'Retorno ao estoque gerado pelo cancelamento '
                f'do pedido {sales_order.code}.'
            ),
        )

        allocation.return_movement = return_movement
        allocation.full_clean()
        allocation.save()
        return_movements.append(return_movement)

    sales_order.status = SalesOrderStatus.CANCELLED
    sales_order.full_clean()
    sales_order.save()

    return sales_order, return_movements


def _locked_payment(payment):
    if payment is None or payment.pk is None:
        raise ValidationError(
            'Salve o pagamento antes de executar esta operação.',
        )

    order_id = (
        SalesOrderPayment.objects
        .values_list('sales_order_id', flat=True)
        .get(pk=payment.pk)
    )
    order = (
        SalesOrder.objects
        .select_for_update()
        .get(pk=order_id)
    )
    locked_payment = (
        SalesOrderPayment.objects
        .select_for_update()
        .get(pk=payment.pk)
    )

    if locked_payment.sales_order_id != order.pk:
        raise ValidationError(
            'O pedido deste pagamento foi alterado. '
            'Atualize a página e tente novamente.',
        )

    locked_payment.sales_order = order
    return locked_payment


@transaction.atomic
def register_sales_payment(
    *,
    payment,
    user=None,
    paid_at=None,
):
    payment = _locked_payment(payment)

    if payment.status != SalesPaymentStatus.PENDING:
        raise ValidationError(
            'Somente um pagamento pendente pode ser recebido.',
        )

    if payment.sales_order.status == SalesOrderStatus.CANCELLED:
        raise ValidationError(
            'Não é possível receber um pagamento de pedido cancelado.',
        )

    other_paid_total = (
        payment.sales_order.payments
        .filter(status=SalesPaymentStatus.PAID)
        .exclude(pk=payment.pk)
        .aggregate(total=Sum('amount'))['total']
        or Decimal('0.00')
    )

    if (
        other_paid_total + payment.amount
        > payment.sales_order.total_amount
    ):
        raise ValidationError(
            'O total recebido não pode ultrapassar '
            'o valor do pedido.',
        )

    payment.status = SalesPaymentStatus.PAID
    payment.paid_at = paid_at or timezone.now()
    payment.received_by = user
    payment.full_clean()
    payment.save()

    post_sales_payment(payment=payment, user=user)
    return payment


@transaction.atomic
def refund_sales_payment(
    *,
    payment,
    user=None,
    refunded_on=None,
):
    payment = _locked_payment(payment)

    if payment.status != SalesPaymentStatus.PAID:
        raise ValidationError(
            'Somente um pagamento recebido pode ser estornado.',
        )

    payment.status = SalesPaymentStatus.REFUNDED
    payment.full_clean()
    payment.save()

    reverse_sales_payment(
        payment=payment,
        occurred_on=refunded_on or timezone.localdate(),
        user=user,
    )
    return payment


@transaction.atomic
def cancel_sales_payment(*, payment):
    payment = _locked_payment(payment)

    if payment.status != SalesPaymentStatus.PENDING:
        raise ValidationError(
            'Somente um pagamento pendente pode ser cancelado.',
        )

    if payment.financial_movements.exists():
        raise ValidationError(
            'Um pagamento com movimentações financeiras '
            'não pode ser cancelado como pendente.',
        )

    payment.status = SalesPaymentStatus.CANCELLED
    payment.paid_at = None
    payment.full_clean()
    payment.save()

    return payment