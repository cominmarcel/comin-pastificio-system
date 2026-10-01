from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel


class FinancialAccountType(models.TextChoices):
    CASH = 'cash', 'Dinheiro em caixa'
    BANK_ACCOUNT = 'bank_account', 'Conta bancária'
    PAYMENT_PLATFORM = (
        'payment_platform',
        'Conta em intermediador de pagamentos',
    )
    OTHER = 'other', 'Outra'


class FinancialMovementDirection(models.TextChoices):
    INCOMING = 'incoming', 'Entrada'
    OUTGOING = 'outgoing', 'Saída'


class FinancialMovementKind(models.TextChoices):
    OPENING_BALANCE = 'opening_balance', 'Saldo inicial'
    PURCHASE_PAYMENT = 'purchase_payment', 'Pagamento de compra'
    SALE_RECEIPT = 'sale_receipt', 'Recebimento de venda'
    SALE_FEE = 'sale_fee', 'Taxa de recebimento'
    EXPENSE_PAYMENT = 'expense_payment', 'Pagamento de despesa'
    OWNER_DEPOSIT = 'owner_deposit', 'Depósito do proprietário'
    OWNER_REIMBURSEMENT = (
        'owner_reimbursement',
        'Reembolso ao proprietário',
    )
    TRANSFER = 'transfer', 'Transferência entre contas'
    ADJUSTMENT = 'adjustment', 'Ajuste de saldo'
    REVERSAL = 'reversal', 'Estorno'


class FinancialAccount(TimeStampedModel):
    code = models.CharField(
        'código',
        max_length=30,
        unique=True,
        help_text='Identificador como CAIXA ou NUBANK-PASTIFICIO.',
    )
    name = models.CharField(
        'nome',
        max_length=150,
    )
    account_type = models.CharField(
        'tipo de conta',
        max_length=30,
        choices=FinancialAccountType.choices,
        default=FinancialAccountType.BANK_ACCOUNT,
    )
    is_active = models.BooleanField(
        'ativa',
        default=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'conta financeira'
        verbose_name_plural = 'contas financeiras'

    def clean(self):
        super().clean()
        self.code = self.code.strip().upper()
        self.name = self.name.strip()

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.name = self.name.strip()
        super().save(*args, **kwargs)

    @property
    def current_balance(self):
        if self.pk is None:
            return Decimal('0.00')

        totals = self.movements.aggregate(
            incoming=models.Sum(
                'amount',
                filter=models.Q(
                    direction=FinancialMovementDirection.INCOMING,
                ),
            ),
            outgoing=models.Sum(
                'amount',
                filter=models.Q(
                    direction=FinancialMovementDirection.OUTGOING,
                ),
            ),
        )

        incoming = totals['incoming'] or Decimal('0.00')
        outgoing = totals['outgoing'] or Decimal('0.00')

        return incoming - outgoing

    def __str__(self):
        return f'{self.code} — {self.name}'


class ExpenseCategory(TimeStampedModel):
    name = models.CharField(
        'nome',
        max_length=100,
        unique=True,
    )
    description = models.TextField(
        'descrição',
        blank=True,
    )
    is_active = models.BooleanField(
        'ativa',
        default=True,
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'categoria de despesa'
        verbose_name_plural = 'categorias de despesas'

    def clean(self):
        super().clean()
        self.name = self.name.strip()

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class FinancialMovement(TimeStampedModel):
    financial_account = models.ForeignKey(
        FinancialAccount,
        verbose_name='conta financeira',
        related_name='movements',
        on_delete=models.PROTECT,
    )
    direction = models.CharField(
        'direção',
        max_length=10,
        choices=FinancialMovementDirection.choices,
    )
    kind = models.CharField(
        'tipo de movimentação',
        max_length=30,
        choices=FinancialMovementKind.choices,
    )
    amount = models.DecimalField(
        'valor',
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    occurred_on = models.DateField(
        'data da movimentação',
        default=timezone.localdate,
        db_index=True,
    )
    description = models.CharField(
        'descrição',
        max_length=255,
    )
    source_key = models.CharField(
        'identificador da operação',
        max_length=100,
        unique=True,
        editable=False,
    )
    purchase_payment = models.ForeignKey(
        'purchases.PurchasePayment',
        verbose_name='pagamento de compra',
        related_name='financial_movements',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    sales_payment = models.ForeignKey(
        'sales.SalesOrderPayment',
        verbose_name='pagamento de venda',
        related_name='financial_movements',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    reversal_of = models.OneToOneField(
        'self',
        verbose_name='movimentação estornada',
        related_name='reversal',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='registrado por',
        related_name='financial_movements_created',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-occurred_on', '-id']
        verbose_name = 'movimentação financeira'
        verbose_name_plural = 'movimentações financeiras'
        indexes = [
            models.Index(
                fields=['financial_account', 'occurred_on'],
                name='finance_account_date_idx',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='finance_movement_amount_positive',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(purchase_payment__isnull=True)
                    | models.Q(sales_payment__isnull=True)
                ),
                name='finance_movement_single_payment_source',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind=FinancialMovementKind.REVERSAL,
                        reversal_of__isnull=False,
                    )
                    | (
                        ~models.Q(
                            kind=FinancialMovementKind.REVERSAL,
                        )
                        & models.Q(reversal_of__isnull=True)
                    )
                ),
                name='finance_movement_reversal_link_valid',
            ),
            models.UniqueConstraint(
                fields=['purchase_payment', 'kind'],
                condition=models.Q(
                    purchase_payment__isnull=False,
                    reversal_of__isnull=True,
                ),
                name='finance_purchase_movement_unique',
            ),
            models.UniqueConstraint(
                fields=['sales_payment', 'kind'],
                condition=models.Q(
                    sales_payment__isnull=False,
                    reversal_of__isnull=True,
                ),
                name='finance_sales_movement_unique',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        expected_directions = {
            FinancialMovementKind.PURCHASE_PAYMENT: (
                FinancialMovementDirection.OUTGOING
            ),
            FinancialMovementKind.SALE_RECEIPT: (
                FinancialMovementDirection.INCOMING
            ),
            FinancialMovementKind.SALE_FEE: (
                FinancialMovementDirection.OUTGOING
            ),
            FinancialMovementKind.EXPENSE_PAYMENT: (
                FinancialMovementDirection.OUTGOING
            ),
            FinancialMovementKind.OWNER_DEPOSIT: (
                FinancialMovementDirection.INCOMING
            ),
            FinancialMovementKind.OWNER_REIMBURSEMENT: (
                FinancialMovementDirection.OUTGOING
            ),
        }
        expected_direction = expected_directions.get(self.kind)

        if (
            expected_direction is not None
            and self.direction != expected_direction
        ):
            errors['direction'] = (
                'A direção não corresponde ao tipo de movimentação.'
            )

        if self.purchase_payment_id and self.sales_payment_id:
            errors['sales_payment'] = (
                'Uma movimentação não pode pertencer '
                'a uma compra e a uma venda ao mesmo tempo.'
            )

        if self.kind != FinancialMovementKind.REVERSAL:
            requires_purchase = (
                self.kind == FinancialMovementKind.PURCHASE_PAYMENT
            )
            requires_sale = self.kind in {
                FinancialMovementKind.SALE_RECEIPT,
                FinancialMovementKind.SALE_FEE,
            }

            if bool(self.purchase_payment_id) != requires_purchase:
                errors['purchase_payment'] = (
                    'O vínculo com a compra deve ser informado '
                    'somente em pagamentos de compra.'
                )

            if bool(self.sales_payment_id) != requires_sale:
                errors['sales_payment'] = (
                    'O vínculo com a venda deve ser informado '
                    'em recebimentos de venda e suas taxas.'
                )

        if self.reversal_of_id:
            original = (
                type(self).objects
                .filter(pk=self.reversal_of_id)
                .first()
            )

            if original is None:
                errors['reversal_of'] = (
                    'A movimentação original não foi encontrada.'
                )
            elif (
                original.pk == self.pk
                or original.kind == FinancialMovementKind.REVERSAL
            ):
                errors['reversal_of'] = (
                    'Selecione uma movimentação original '
                    'que não seja um estorno.'
                )
            else:
                if (
                    self.financial_account_id
                    != original.financial_account_id
                ):
                    errors['financial_account'] = (
                        'O estorno deve utilizar a conta original.'
                    )

                if self.amount != original.amount:
                    errors['amount'] = (
                        'O estorno deve ter o mesmo valor '
                        'da movimentação original.'
                    )

                opposite_direction = (
                    FinancialMovementDirection.OUTGOING
                    if original.direction
                    == FinancialMovementDirection.INCOMING
                    else FinancialMovementDirection.INCOMING
                )

                if self.direction != opposite_direction:
                    errors['direction'] = (
                        'O estorno deve inverter a direção original.'
                    )

                if (
                    self.occurred_on
                    and self.occurred_on < original.occurred_on
                ):
                    errors['occurred_on'] = (
                        'O estorno não pode ser anterior '
                        'à movimentação original.'
                    )

                if (
                    self.purchase_payment_id
                    != original.purchase_payment_id
                    or self.sales_payment_id
                    != original.sales_payment_id
                ):
                    errors['reversal_of'] = (
                        'O estorno deve preservar os vínculos '
                        'com os pagamentos originais.'
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self._state.adding or self.pk is not None:
            raise ValidationError(
                'Uma movimentação registrada não pode ser editada. '
                'Registre um estorno e uma nova movimentação.',
            )

        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            'Movimentações financeiras devem ser estornadas.',
        )

    def __str__(self):
        return (
            f'{self.get_direction_display()} — '
            f'R$ {self.amount} — {self.description}'
        )