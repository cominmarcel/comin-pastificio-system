from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from sales.models import SalesOrderPayment, SalesPaymentStatus

from .models import (
    FinancialAccount,
    FinancialMovement,
    FinancialMovementDirection,
    FinancialMovementKind,
)


@transaction.atomic
def _record_financial_movement(
    *,
    financial_account,
    direction,
    kind,
    amount,
    occurred_on,
    description,
    source_key,
    user=None,
    purchase_payment=None,
    sales_payment=None,
    reversal_of=None,
):
    if financial_account is None or financial_account.pk is None:
        raise ValidationError('Informe uma conta financeira cadastrada.')

    if isinstance(amount, float):
        raise ValidationError(
            'Informe o valor como Decimal ou texto, sem usar float.',
        )

    try:
        account = (
            FinancialAccount.objects
            .select_for_update()
            .get(pk=financial_account.pk)
        )
    except FinancialAccount.DoesNotExist:
        raise ValidationError('A conta financeira não foi encontrada.')

    movement = FinancialMovement(
        financial_account=account,
        direction=direction,
        kind=kind,
        amount=amount,
        occurred_on=occurred_on,
        description=description,
        source_key=source_key,
        created_by=user,
        purchase_payment=purchase_payment,
        sales_payment=sales_payment,
        reversal_of=reversal_of,
    )
    movement.clean_fields()

    existing = (
        FinancialMovement.objects
        .filter(source_key=movement.source_key)
        .first()
    )

    if existing is not None:
        comparable_fields = (
            'financial_account_id',
            'direction',
            'kind',
            'amount',
            'occurred_on',
            'description',
            'purchase_payment_id',
            'sales_payment_id',
            'reversal_of_id',
        )

        if any(
            getattr(existing, field) != getattr(movement, field)
            for field in comparable_fields
        ):
            raise ValidationError(
                'Este identificador já foi utilizado '
                'em uma movimentação com dados diferentes.',
            )

        return existing

    if (
        not account.is_active
        and movement.kind != FinancialMovementKind.REVERSAL
    ):
        raise ValidationError(
            'Uma conta inativa não pode receber novas movimentações.',
        )

    movement.save()
    return movement


@transaction.atomic
def _reverse_financial_movement(
    *,
    movement,
    occurred_on,
    user=None,
):
    if movement is None or movement.pk is None:
        raise ValidationError(
            'Informe uma movimentação financeira registrada.',
        )

    try:
        original = FinancialMovement.objects.get(pk=movement.pk)
    except FinancialMovement.DoesNotExist:
        raise ValidationError(
            'A movimentação financeira não foi encontrada.',
        )

    if original.kind == FinancialMovementKind.REVERSAL:
        raise ValidationError(
            'Não é permitido estornar um estorno.',
        )

    direction = (
        FinancialMovementDirection.OUTGOING
        if original.direction == FinancialMovementDirection.INCOMING
        else FinancialMovementDirection.INCOMING
    )

    return _record_financial_movement(
        financial_account=original.financial_account,
        direction=direction,
        kind=FinancialMovementKind.REVERSAL,
        amount=original.amount,
        occurred_on=occurred_on,
        description=f'Estorno da movimentação #{original.pk}',
        source_key=f'reversal:{original.pk}',
        user=user,
        purchase_payment=original.purchase_payment,
        sales_payment=original.sales_payment,
        reversal_of=original,
    )
def _locked_sales_payment(payment):
    if payment is None or payment.pk is None:
        raise ValidationError('Informe um pagamento de venda salvo.')

    try:
        return (
            SalesOrderPayment.objects
            .select_for_update()
            .get(pk=payment.pk)
        )
    except SalesOrderPayment.DoesNotExist:
        raise ValidationError('O pagamento de venda não foi encontrado.')


@transaction.atomic
def post_sales_payment(*, payment, user=None):
    payment = _locked_sales_payment(payment)

    if payment.status != SalesPaymentStatus.PAID:
        raise ValidationError(
            'Somente um pagamento recebido pode entrar no financeiro.',
        )

    if payment.financial_account_id is None:
        raise ValidationError('Informe a conta de recebimento.')

    payment.full_clean()
    occurred_on = timezone.localdate(payment.paid_at)

    originals = payment.financial_movements.filter(
        reversal_of__isnull=True,
    )
    receipt = originals.filter(
        kind=FinancialMovementKind.SALE_RECEIPT,
    ).first()
    fee = originals.filter(
        kind=FinancialMovementKind.SALE_FEE,
    ).first()

    if originals.filter(reversal__isnull=False).exists():
        raise ValidationError(
            'Este pagamento já possui movimentações estornadas.',
        )

    if fee is not None and receipt is None:
        raise ValidationError(
            'Existe uma taxa sem o recebimento correspondente.',
        )

    if (
        receipt is not None
        and (fee is not None) != (payment.fee_amount > 0)
    ):
        raise ValidationError(
            'A taxa do pagamento foi alterada após o lançamento.',
        )

    receipt = _record_financial_movement(
        financial_account=payment.financial_account,
        direction=FinancialMovementDirection.INCOMING,
        kind=FinancialMovementKind.SALE_RECEIPT,
        amount=payment.amount,
        occurred_on=occurred_on,
        description=f'Recebimento do pagamento de venda #{payment.pk}',
        source_key=f'sales-payment:{payment.pk}:receipt',
        user=user,
        sales_payment=payment,
    )

    if payment.fee_amount > 0:
        _record_financial_movement(
            financial_account=payment.financial_account,
            direction=FinancialMovementDirection.OUTGOING,
            kind=FinancialMovementKind.SALE_FEE,
            amount=payment.fee_amount,
            occurred_on=occurred_on,
            description=f'Taxa do pagamento de venda #{payment.pk}',
            source_key=f'sales-payment:{payment.pk}:fee',
            user=user,
            sales_payment=payment,
        )

    return receipt


@transaction.atomic
def reverse_sales_payment(*, payment, occurred_on, user=None):
    payment = _locked_sales_payment(payment)

    if payment.status != SalesPaymentStatus.REFUNDED:
        raise ValidationError(
            'O pagamento precisa estar marcado como estornado.',
        )

    payment.full_clean()

    originals = payment.financial_movements.filter(
        reversal_of__isnull=True,
    )
    receipt = originals.filter(
        kind=FinancialMovementKind.SALE_RECEIPT,
    ).first()
    fee = originals.filter(
        kind=FinancialMovementKind.SALE_FEE,
    ).first()

    if receipt is None:
        raise ValidationError(
            'Este pagamento não possui lançamento financeiro. '
            'Regularize o recebimento antes de estorná-lo.',
        )

    recorded_fee = fee.amount if fee is not None else 0

    if (
        receipt.financial_account_id != payment.financial_account_id
        or receipt.amount != payment.amount
        or receipt.occurred_on != timezone.localdate(payment.paid_at)
        or recorded_fee != payment.fee_amount
    ):
        raise ValidationError(
            'Os dados do pagamento diferem do lançamento financeiro.',
        )

    return _reverse_financial_movement(
        movement=receipt,
        occurred_on=occurred_on,
        user=user,
    )