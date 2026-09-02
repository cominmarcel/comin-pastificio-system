from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from catalog.models import Item
from core.models import TimeStampedModel
from purchases.models import PurchaseItem


class StockLocationType(models.TextChoices):
    GENERAL = 'general', 'Armazenamento geral'
    REFRIGERATED = 'refrigerated', 'Refrigerado'
    FROZEN = 'frozen', 'Congelado'
    PRODUCTION = 'production', 'Área de produção'
    IN_TRANSIT = 'in_transit', 'Em trânsito'
    OTHER = 'other', 'Outro'


class StockMovementType(models.TextChoices):
    OPENING_BALANCE = 'opening_balance', 'Saldo inicial'
    PURCHASE_RECEIPT = 'purchase_receipt', 'Entrada por compra'
    PRODUCTION_CONSUMPTION = (
        'production_consumption',
        'Consumo na produção',
    )
    PRODUCTION_OUTPUT = (
        'production_output',
        'Entrada da produção',
    )
    SALE_DISPATCH = 'sale_dispatch', 'Saída por venda'
    CUSTOMER_RETURN = 'customer_return', 'Devolução de cliente'
    SUPPLIER_RETURN = 'supplier_return', 'Devolução ao fornecedor'
    LOSS = 'loss', 'Perda ou descarte'
    ADJUSTMENT_IN = 'adjustment_in', 'Ajuste de entrada'
    ADJUSTMENT_OUT = 'adjustment_out', 'Ajuste de saída'
    TRANSFER = 'transfer', 'Transferência'


class StockCountStatus(models.TextChoices):
    DRAFT = 'draft', 'Rascunho'
    COMPLETED = 'completed', 'Concluído'
    CANCELLED = 'cancelled', 'Cancelado'

class StockLocation(TimeStampedModel):
    code = models.CharField(
        'código',
        max_length=30,
        unique=True,
        help_text='Identificador curto, como FREEZER-01.',
    )
    name = models.CharField(
        'nome',
        max_length=100,
        unique=True,
    )
    location_type = models.CharField(
        'tipo de local',
        max_length=20,
        choices=StockLocationType.choices,
        default=StockLocationType.GENERAL,
    )
    description = models.TextField(
        'descrição',
        blank=True,
    )
    is_active = models.BooleanField(
        'ativo',
        default=True,
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'local de estoque'
        verbose_name_plural = 'locais de estoque'

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} [{self.code}]'

class StockLot(TimeStampedModel):
    item = models.ForeignKey(
        Item,
        verbose_name='item',
        related_name='stock_lots',
        on_delete=models.PROTECT,
    )
    code = models.CharField(
        'código interno do lote',
        max_length=50,
        unique=True,
        help_text='Identificador como LOT-2026-000001.',
    )
    supplier_lot_code = models.CharField(
        'lote informado pelo fornecedor',
        max_length=100,
        blank=True,
    )
    purchase_item = models.ForeignKey(
        PurchaseItem,
        verbose_name='item de compra de origem',
        related_name='stock_lots',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    received_date = models.DateField(
        'data de recebimento',
        default=timezone.localdate,
        db_index=True,
    )
    manufacturing_date = models.DateField(
        'data de fabricação',
        null=True,
        blank=True,
    )
    expiration_date = models.DateField(
        'data de validade',
        null=True,
        blank=True,
        db_index=True,
    )
    unit_cost = models.DecimalField(
        'custo por unidade-base',
        max_digits=18,
        decimal_places=8,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00000000'))],
    )
    is_blocked = models.BooleanField(
        'bloqueado para utilização',
        default=False,
    )
    is_active = models.BooleanField(
        'ativo',
        default=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['expiration_date', 'received_date', 'id']
        verbose_name = 'lote de estoque'
        verbose_name_plural = 'lotes de estoque'
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(unit_cost__isnull=True)
                    | models.Q(unit_cost__gte=0)
                ),
                name='stock_lot_unit_cost_nonnegative',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.manufacturing_date
            and self.expiration_date
            and self.expiration_date < self.manufacturing_date
        ):
            errors['expiration_date'] = (
                'A validade não pode ser anterior à fabricação.'
            )

        if (
            self.purchase_item_id
            and self.item_id
            and self.purchase_item.item_id != self.item_id
        ):
            errors['purchase_item'] = (
                'O item da compra deve corresponder ao item do lote.'
            )

        if errors:
            raise ValidationError(errors)

    @property
    def is_expired(self):
        return (
            self.expiration_date is not None
            and self.expiration_date < timezone.localdate()
        )

    def quantity_at(self, location):
        totals = self.movements.aggregate(
            incoming=models.Sum(
                'quantity',
                filter=models.Q(destination_location=location),
            ),
            outgoing=models.Sum(
                'quantity',
                filter=models.Q(source_location=location),
            ),
        )

        incoming = totals['incoming'] or Decimal('0.000000')
        outgoing = totals['outgoing'] or Decimal('0.000000')

        return incoming - outgoing

    @property
    def current_quantity(self):
        totals = self.movements.aggregate(
            incoming=models.Sum(
                'quantity',
                filter=models.Q(
                    destination_location__isnull=False,
                ),
            ),
            outgoing=models.Sum(
                'quantity',
                filter=models.Q(
                    source_location__isnull=False,
                ),
            ),
        )

        incoming = totals['incoming'] or Decimal('0.000000')
        outgoing = totals['outgoing'] or Decimal('0.000000')

        return incoming - outgoing

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.item} — lote {self.code}'
class StockMovement(TimeStampedModel):
    lot = models.ForeignKey(
        StockLot,
        verbose_name='lote',
        related_name='movements',
        on_delete=models.PROTECT,
    )
    movement_type = models.CharField(
        'tipo de movimentação',
        max_length=30,
        choices=StockMovementType.choices,
        db_index=True,
    )
    quantity = models.DecimalField(
        'quantidade na unidade-base',
        max_digits=18,
        decimal_places=6,
        validators=[MinValueValidator(Decimal('0.000001'))],
    )
    source_location = models.ForeignKey(
        StockLocation,
        verbose_name='local de origem',
        related_name='outgoing_movements',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    destination_location = models.ForeignKey(
        StockLocation,
        verbose_name='local de destino',
        related_name='incoming_movements',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    occurred_at = models.DateTimeField(
        'data e hora da movimentação',
        default=timezone.now,
        db_index=True,
    )
    reference = models.CharField(
        'referência',
        max_length=100,
        blank=True,
        help_text=(
            'Número da compra, produção, venda ou outro '
            'documento relacionado.'
        ),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='registrado por',
        related_name='stock_movements_created',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['-occurred_at', '-id']
        verbose_name = 'movimentação de estoque'
        verbose_name_plural = 'movimentações de estoque'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name='stock_movement_quantity_positive',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_location__isnull=False)
                    | models.Q(destination_location__isnull=False)
                ),
                name='stock_movement_has_location',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_location__isnull=True)
                    | models.Q(destination_location__isnull=True)
                    | ~models.Q(
                        source_location=models.F(
                            'destination_location',
                        ),
                    )
                ),
                name='stock_movement_locations_different',
            ),
        ]
        indexes = [
            models.Index(
                fields=['lot', 'occurred_at'],
                name='stock_move_lot_date_idx',
            ),
            models.Index(
                fields=['movement_type', 'occurred_at'],
                name='stock_move_type_date_idx',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        inbound_types = {
            StockMovementType.OPENING_BALANCE,
            StockMovementType.PURCHASE_RECEIPT,
            StockMovementType.PRODUCTION_OUTPUT,
            StockMovementType.CUSTOMER_RETURN,
            StockMovementType.ADJUSTMENT_IN,
        }
        outbound_types = {
            StockMovementType.PRODUCTION_CONSUMPTION,
            StockMovementType.SALE_DISPATCH,
            StockMovementType.SUPPLIER_RETURN,
            StockMovementType.LOSS,
            StockMovementType.ADJUSTMENT_OUT,
        }

        if self.movement_type == StockMovementType.TRANSFER:
            if not self.source_location_id:
                errors['source_location'] = (
                    'Informe a origem da transferência.'
                )

            if not self.destination_location_id:
                errors['destination_location'] = (
                    'Informe o destino da transferência.'
                )

            if (
                self.source_location_id
                and self.destination_location_id
                and self.source_location_id
                == self.destination_location_id
            ):
                errors['destination_location'] = (
                    'O destino deve ser diferente da origem.'
                )

        elif self.movement_type in inbound_types:
            if self.source_location_id:
                errors['source_location'] = (
                    'Uma entrada não deve possuir local de origem.'
                )

            if not self.destination_location_id:
                errors['destination_location'] = (
                    'Informe o local de destino da entrada.'
                )

        elif self.movement_type in outbound_types:
            if not self.source_location_id:
                errors['source_location'] = (
                    'Informe o local de origem da saída.'
                )

            if self.destination_location_id:
                errors['destination_location'] = (
                    'Uma saída não deve possuir local de destino.'
                )

        restricted_outbound_types = {
            StockMovementType.PRODUCTION_CONSUMPTION,
            StockMovementType.SALE_DISPATCH,
        }

        if (
            self.lot_id
            and self.movement_type in restricted_outbound_types
        ):
            if self.lot.is_blocked:
                errors['lot'] = (
                    'Um lote bloqueado não pode ser utilizado.'
                )
            elif self.lot.is_expired:
                errors['lot'] = (
                    'Um lote vencido não pode ser utilizado.'
                )

        if (
            self._state.adding
            and self.lot_id
            and self.source_location_id
            and self.quantity is not None
        ):
            available_quantity = self.lot.quantity_at(
                self.source_location,
            )

            if self.quantity > available_quantity:
                unit_symbol = self.lot.item.base_unit.symbol
                errors['quantity'] = (
                    'Estoque insuficiente neste local. '
                    f'Disponível: {available_quantity} '
                    f'{unit_symbol}.'
                )

        if errors:
            raise ValidationError(errors)

    @property
    def item(self):
        return self.lot.item

    def __str__(self):
        unit_symbol = self.lot.item.base_unit.symbol

        return (
            f'{self.get_movement_type_display()}: '
            f'{self.quantity} {unit_symbol} — {self.lot}'
        )
class StockCount(TimeStampedModel):
    location = models.ForeignKey(
        StockLocation,
        verbose_name='local de estoque',
        related_name='stock_counts',
        on_delete=models.PROTECT,
    )
    counted_at = models.DateTimeField(
        'data e hora da contagem',
        default=timezone.now,
        db_index=True,
    )
    status = models.CharField(
        'situação',
        max_length=20,
        choices=StockCountStatus.choices,
        default=StockCountStatus.DRAFT,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='criado por',
        related_name='stock_counts_created',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    completed_at = models.DateTimeField(
        'concluído em',
        null=True,
        blank=True,
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='concluído por',
        related_name='stock_counts_completed',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['-counted_at', '-id']
        verbose_name = 'contagem de estoque'
        verbose_name_plural = 'contagens de estoque'

    def __str__(self):
        count_id = self.pk or 'nova'
        count_date = timezone.localtime(
            self.counted_at,
        ).strftime('%d/%m/%Y %H:%M')

        return (
            f'Contagem #{count_id} — '
            f'{self.location} — {count_date}'
        )


class StockCountLine(TimeStampedModel):
    stock_count = models.ForeignKey(
        StockCount,
        verbose_name='contagem de estoque',
        related_name='lines',
        on_delete=models.CASCADE,
    )
    lot = models.ForeignKey(
        StockLot,
        verbose_name='lote',
        related_name='stock_count_lines',
        on_delete=models.PROTECT,
    )
    expected_quantity = models.DecimalField(
        'quantidade esperada',
        max_digits=18,
        decimal_places=6,
        default=Decimal('0.000000'),
        validators=[MinValueValidator(Decimal('0.000000'))],
    )
    counted_quantity = models.DecimalField(
        'quantidade contada',
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.000000'))],
    )
    notes = models.CharField(
        'observações',
        max_length=255,
        blank=True,
    )

    class Meta:
        ordering = ['lot__item__name', 'lot__expiration_date', 'id']
        verbose_name = 'item da contagem'
        verbose_name_plural = 'itens da contagem'
        constraints = [
            models.UniqueConstraint(
                fields=['stock_count', 'lot'],
                name='stock_count_lot_unique',
            ),
            models.CheckConstraint(
                condition=models.Q(expected_quantity__gte=0),
                name='stock_count_expected_nonnegative',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(counted_quantity__isnull=True)
                    | models.Q(counted_quantity__gte=0)
                ),
                name='stock_count_counted_nonnegative',
            ),
        ]

    @property
    def difference(self):
        if self.counted_quantity is None:
            return None

        return self.counted_quantity - self.expected_quantity