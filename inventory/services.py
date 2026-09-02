from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from purchases.models import PurchaseItem, PurchaseStatus

from .models import (
    StockCount,
    StockCountLine,
    StockCountStatus,
    StockLocation,
    StockLot,
    StockMovement,
    StockMovementType,
)


@transaction.atomic
def record_stock_movement(
    *,
    lot,
    movement_type,
    quantity,
    source_location=None,
    destination_location=None,
    occurred_at=None,
    reference='',
    user=None,
    notes='',
):
    locked_lot = StockLot.objects.select_for_update().get(
        pk=lot.pk,
    )

    movement = StockMovement(
        lot=locked_lot,
        movement_type=movement_type,
        quantity=quantity,
        source_location=source_location,
        destination_location=destination_location,
        occurred_at=occurred_at or timezone.now(),
        reference=reference,
        created_by=user,
        notes=notes,
    )
    movement.full_clean()
    movement.save()

    return movement


@transaction.atomic
def receive_purchase_item(
    *,
    purchase_item,
    destination_location,
    lot_code,
    quantity=None,
    supplier_lot_code='',
    manufacturing_date=None,
    expiration_date=None,
    received_date=None,
    user=None,
    notes='',
):
    purchase_item = (
        PurchaseItem.objects
        .select_for_update()
        .select_related('purchase', 'item')
        .get(pk=purchase_item.pk)
    )
    destination_location = StockLocation.objects.get(
        pk=destination_location.pk,
    )

    if not destination_location.is_active:
        raise ValidationError(
            'O local de destino está inativo.',
        )

    if purchase_item.purchase.status not in {
        PurchaseStatus.PARTIALLY_RECEIVED,
        PurchaseStatus.RECEIVED,
    }:
        raise ValidationError(
            'A compra precisa estar parcial ou totalmente recebida.',
        )

    received_quantity = (
        StockMovement.objects
        .filter(
            lot__purchase_item=purchase_item,
            movement_type=StockMovementType.PURCHASE_RECEIPT,
        )
        .aggregate(total=Sum('quantity'))['total']
        or Decimal('0.000000')
    )
    remaining_quantity = (
        purchase_item.base_quantity - received_quantity
    )

    if quantity is None:
        quantity = remaining_quantity
    else:
        quantity = Decimal(str(quantity))

    if quantity <= 0:
        raise ValidationError(
            'Não existe quantidade pendente de recebimento.',
        )

    if quantity > remaining_quantity:
        raise ValidationError(
            'A quantidade recebida não pode ultrapassar '
            'a quantidade pendente da compra.',
        )

    unit_cost = purchase_item.cost_per_base_unit

    if unit_cost is not None:
        unit_cost = unit_cost.quantize(
            Decimal('0.00000001'),
            rounding=ROUND_HALF_UP,
        )

    lot = StockLot(
        item=purchase_item.item,
        code=lot_code.strip().upper(),
        supplier_lot_code=supplier_lot_code.strip(),
        purchase_item=purchase_item,
        received_date=(
            received_date
            or purchase_item.purchase.received_date
            or purchase_item.purchase.purchase_date
        ),
        manufacturing_date=manufacturing_date,
        expiration_date=expiration_date,
        unit_cost=unit_cost,
        notes=notes,
    )
    lot.full_clean()
    lot.save()

    movement = record_stock_movement(
        lot=lot,
        movement_type=StockMovementType.PURCHASE_RECEIPT,
        quantity=quantity,
        destination_location=destination_location,
        reference=f'Compra #{purchase_item.purchase_id}',
        user=user,
        notes=notes,
    )

    return lot, movement
@transaction.atomic
def prepare_stock_count(*, stock_count):
    stock_count = (
        StockCount.objects
        .select_for_update()
        .select_related('location')
        .get(pk=stock_count.pk)
    )

    if stock_count.status != StockCountStatus.DRAFT:
        raise ValidationError(
            'Somente uma contagem em rascunho pode ser preparada.',
        )

    if stock_count.lines.exists():
        raise ValidationError(
            'Esta contagem já possui itens preparados.',
        )

    lots = (
        StockLot.objects
        .filter(is_active=True)
        .select_related('item', 'item__base_unit')
    )
    created_lines = []

    for lot in lots:
        expected_quantity = lot.quantity_at(
            stock_count.location,
        )

        if expected_quantity <= 0:
            continue

        line = StockCountLine(
            stock_count=stock_count,
            lot=lot,
            expected_quantity=expected_quantity,
            counted_quantity=None,
        )
        line.full_clean()
        line.save()
        created_lines.append(line)

    return created_lines


@transaction.atomic
def complete_stock_count(*, stock_count, user=None):
    stock_count = (
        StockCount.objects
        .select_for_update()
        .select_related('location')
        .get(pk=stock_count.pk)
    )

    if stock_count.status != StockCountStatus.DRAFT:
        raise ValidationError(
            'Somente uma contagem em rascunho pode ser concluída.',
        )

    lines = list(
        stock_count.lines.select_related(
            'lot',
            'lot__item',
            'lot__item__base_unit',
        )
    )

    missing_lines = [
        line
        for line in lines
        if line.counted_quantity is None
    ]

    if missing_lines:
        raise ValidationError(
            'Preencha a quantidade contada de todos os lotes.',
        )

    for line in lines:
        current_quantity = line.lot.quantity_at(
            stock_count.location,
        )

        if current_quantity != line.expected_quantity:
            raise ValidationError(
                'O estoque mudou depois da preparação da contagem. '
                'Crie uma nova contagem para evitar um ajuste incorreto.',
            )

    movements = []

    for line in lines:
        difference = line.difference

        if difference > 0:
            movement = record_stock_movement(
                lot=line.lot,
                movement_type=StockMovementType.ADJUSTMENT_IN,
                quantity=difference,
                destination_location=stock_count.location,
                reference=f'Contagem #{stock_count.pk}',
                user=user,
                notes='Ajuste gerado pela contagem física.',
            )
            movements.append(movement)

        elif difference < 0:
            movement = record_stock_movement(
                lot=line.lot,
                movement_type=StockMovementType.ADJUSTMENT_OUT,
                quantity=abs(difference),
                source_location=stock_count.location,
                reference=f'Contagem #{stock_count.pk}',
                user=user,
                notes='Ajuste gerado pela contagem física.',
            )
            movements.append(movement)

    stock_count.status = StockCountStatus.COMPLETED
    stock_count.completed_at = timezone.now()
    stock_count.completed_by = user
    stock_count.save()

    return movements