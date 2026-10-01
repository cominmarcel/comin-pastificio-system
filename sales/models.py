from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from catalog.models import Item, UnitOfMeasure
from core.models import TimeStampedModel
from inventory.models import (
    StockLocation,
    StockLot,
    StockMovement,
    StockMovementType,
)


class CustomerType(models.TextChoices):
    INDIVIDUAL = 'individual', 'Pessoa física'
    COMPANY = 'company', 'Pessoa jurídica'


class SalesChannel(models.TextChoices):
    WHATSAPP = 'whatsapp', 'WhatsApp'
    INSTAGRAM = 'instagram', 'Instagram'
    WEBSITE = 'website', 'Site'
    DIRECT = 'direct', 'Contato direto'
    PHYSICAL = 'physical', 'Venda presencial'
    PARTNER = 'partner', 'Parceiro ou ponto de venda'
    OTHER = 'other', 'Outro'


class SalesOrderStatus(models.TextChoices):
    DRAFT = 'draft', 'Rascunho'
    CONFIRMED = 'confirmed', 'Confirmado'
    IN_PRODUCTION = 'in_production', 'Em produção'
    READY = 'ready', 'Pronto'
    COMPLETED = 'completed', 'Concluído'
    CANCELLED = 'cancelled', 'Cancelado'


class FulfillmentType(models.TextChoices):
    PICKUP = 'pickup', 'Retirada'
    OWN_DELIVERY = 'own_delivery', 'Entrega própria'
    COURIER = 'courier', 'Motoboy ou transportadora'
    PARTNER_LOCATION = 'partner_location', 'Retirada em parceiro'
    OTHER = 'other', 'Outro'


class SalesPaymentMethod(models.TextChoices):
    PIX = 'pix', 'Pix'
    CASH = 'cash', 'Dinheiro'
    DEBIT_CARD = 'debit_card', 'Cartão de débito'
    CREDIT_CARD = 'credit_card', 'Cartão de crédito'
    CRYPTO = 'crypto', 'Cripto'
    BANK_TRANSFER = 'bank_transfer', 'Transferência bancária'
    OTHER = 'other', 'Outro'


class SalesPaymentStatus(models.TextChoices):
    PENDING = 'pending', 'Pendente'
    PAID = 'paid', 'Pago'
    CANCELLED = 'cancelled', 'Cancelado'
    REFUNDED = 'refunded', 'Estornado'


class Customer(TimeStampedModel):
    name = models.CharField(
        'nome',
        max_length=150,
    )
    customer_type = models.CharField(
        'tipo de cliente',
        max_length=20,
        choices=CustomerType.choices,
        default=CustomerType.INDIVIDUAL,
    )
    tax_id = models.CharField(
        'CPF / CNPJ',
        max_length=14,
        unique=True,
        null=True,
        blank=True,
        help_text='Informe somente os números.',
    )
    contact_name = models.CharField(
        'pessoa de contato',
        max_length=150,
        blank=True,
    )
    phone = models.CharField(
        'telefone / WhatsApp',
        max_length=30,
        blank=True,
    )
    email = models.EmailField(
        'e-mail',
        blank=True,
    )
    birth_date = models.DateField(
        'data de nascimento',
        null=True,
        blank=True,
    )
    address = models.TextField(
        'endereço',
        blank=True,
    )
    city = models.CharField(
        'cidade',
        max_length=100,
        blank=True,
    )
    state = models.CharField(
        'UF',
        max_length=2,
        blank=True,
    )
    postal_code = models.CharField(
        'CEP',
        max_length=9,
        blank=True,
    )
    is_active = models.BooleanField(
        'ativo',
        default=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='cadastrado por',
        related_name='customers_created',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'cliente'
        verbose_name_plural = 'clientes'

    def clean(self):
        super().clean()
        errors = {}

        normalized_tax_id = ''.join(
            character
            for character in (self.tax_id or '')
            if character.isdigit()
        )
        self.tax_id = normalized_tax_id or None

        if self.tax_id and len(self.tax_id) not in {11, 14}:
            errors['tax_id'] = (
                'Informe um CPF com 11 dígitos '
                'ou um CNPJ com 14 dígitos.'
            )

        if (
            self.birth_date
            and self.birth_date > timezone.localdate()
        ):
            errors['birth_date'] = (
                'A data de nascimento não pode estar no futuro.'
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.name = self.name.strip()

        if self.tax_id:
            self.tax_id = ''.join(
                character
                for character in self.tax_id
                if character.isdigit()
            )
        else:
            self.tax_id = None

        self.state = self.state.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class SalesOrder(TimeStampedModel):
    code = models.CharField(
        'número do pedido',
        max_length=50,
        unique=True,
        help_text='Identificador como PED-2026-000001.',
    )
    customer = models.ForeignKey(
        Customer,
        verbose_name='cliente',
        related_name='sales_orders',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text='Pode ficar vazio para uma venda não identificada.',
    )
    ordered_at = models.DateTimeField(
        'data e hora do pedido',
        default=timezone.now,
        db_index=True,
    )
    scheduled_for = models.DateTimeField(
        'data e hora combinadas',
        null=True,
        blank=True,
        db_index=True,
    )
    completed_at = models.DateTimeField(
        'concluído em',
        null=True,
        blank=True,
    )
    status = models.CharField(
        'situação',
        max_length=20,
        choices=SalesOrderStatus.choices,
        default=SalesOrderStatus.DRAFT,
        db_index=True,
    )
    channel = models.CharField(
        'canal da venda',
        max_length=20,
        choices=SalesChannel.choices,
        default=SalesChannel.WHATSAPP,
    )
    fulfillment_type = models.CharField(
        'forma de entrega ou retirada',
        max_length=20,
        choices=FulfillmentType.choices,
        default=FulfillmentType.PICKUP,
    )
    source_location = models.ForeignKey(
        StockLocation,
        verbose_name='local de separação do estoque',
        related_name='sales_orders_fulfilled',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text=(
            'Local padrão de onde sairão os produtos '
            'deste pedido.'
        ),
    )
    delivery_address = models.TextField(
        'endereço da entrega',
        blank=True,
        help_text=(
            'Registre aqui o endereço utilizado neste pedido. '
            'Assim o histórico não muda se o cliente se mudar.'
        ),
    )
    discount_amount = models.DecimalField(
        'desconto geral',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    delivery_fee = models.DecimalField(
        'taxa de entrega cobrada',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Valor de entrega cobrado do cliente.',
    )
    delivery_cost = models.DecimalField(
        'custo real da entrega',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text=(
            'Custo suportado pelo Pastifício, '
            'como combustível ou motoboy.'
        ),
    )
    other_charges_amount = models.DecimalField(
        'outros valores cobrados',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='responsável pela venda',
        related_name='sales_orders_sold',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='cadastrado por',
        related_name='sales_orders_created',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['-ordered_at', '-id']
        verbose_name = 'pedido de venda'
        verbose_name_plural = 'pedidos de venda'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=0),
                name='sales_order_discount_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(delivery_fee__gte=0),
                name='sales_order_delivery_fee_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(delivery_cost__gte=0),
                name='sales_order_delivery_cost_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(other_charges_amount__gte=0),
                name='sales_order_other_charges_nonnegative',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scheduled_for__isnull=True)
                    | models.Q(
                        scheduled_for__gte=models.F('ordered_at'),
                    )
                ),
                name='sales_order_schedule_after_order',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(completed_at__isnull=True)
                    | models.Q(
                        completed_at__gte=models.F('ordered_at'),
                    )
                ),
                name='sales_order_completion_after_order',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        delivery_types = {
            FulfillmentType.OWN_DELIVERY,
            FulfillmentType.COURIER,
        }

        if (
            self.fulfillment_type in delivery_types
            and not self.delivery_address.strip()
        ):
            errors['delivery_address'] = (
                'Informe o endereço para este tipo de entrega.'
            )

        if (
            self.scheduled_for
            and self.ordered_at
            and self.scheduled_for < self.ordered_at
        ):
            errors['scheduled_for'] = (
                'A data combinada não pode ser anterior ao pedido.'
            )

        if (
            self.completed_at
            and self.ordered_at
            and self.completed_at < self.ordered_at
        ):
            errors['completed_at'] = (
                'A conclusão não pode ser anterior ao pedido.'
            )

        if (
            self.status == SalesOrderStatus.COMPLETED
            and not self.completed_at
        ):
            errors['completed_at'] = (
                'Informe quando o pedido foi concluído.'
            )

        if errors:
            raise ValidationError(errors)

    @property
    def items_subtotal(self):
        return sum(
            (item.subtotal for item in self.items.all()),
            Decimal('0.00'),
        )

    @property
    def items_discount_total(self):
        return sum(
            (item.discount_amount for item in self.items.all()),
            Decimal('0.00'),
        )

    @property
    def items_net_total(self):
        return self.items_subtotal - self.items_discount_total

    @property
    def total_amount(self):
        return (
            self.items_net_total
            + self.delivery_fee
            + self.other_charges_amount
            - self.discount_amount
        )

    @property
    def paid_total(self):
        return sum(
            (
                payment.amount
                for payment in self.payments.filter(
                    status=SalesPaymentStatus.PAID,
                )
            ),
            Decimal('0.00'),
        )

    @property
    def balance_due(self):
        return self.total_amount - self.paid_total

    @property
    def items_cost_total(self):
        return sum(
            (item.cost_total for item in self.items.all()),
            Decimal('0.00'),
        )

    @property
    def payment_fees_total(self):
        charged_statuses = {
            SalesPaymentStatus.PAID,
            SalesPaymentStatus.REFUNDED,
        }

        return sum(
            (
                payment.fee_amount
                for payment in self.payments.filter(
                    status__in=charged_statuses,
                )
            ),
            Decimal('0.00'),
        )

    @property
    def total_cost(self):
        return (
            self.items_cost_total
            + self.delivery_cost
            + self.payment_fees_total
        )

    @property
    def profit(self):
        return self.total_amount - self.total_cost

    @property
    def margin_percentage(self):
        if self.total_amount <= 0:
            return None

        return (
            self.profit
            / self.total_amount
            * Decimal('100')
        ).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        customer_name = (
            self.customer.name
            if self.customer
            else 'Cliente não identificado'
        )

        return f'{self.code} — {customer_name}'

class SalesOrderItem(TimeStampedModel):
    sales_order = models.ForeignKey(
        SalesOrder,
        verbose_name='pedido de venda',
        related_name='items',
        on_delete=models.CASCADE,
    )
    item = models.ForeignKey(
        Item,
        verbose_name='item vendido',
        related_name='sales_order_items',
        on_delete=models.PROTECT,
    )
    commercial_quantity = models.DecimalField(
        'quantidade comercial',
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0001'))],
        help_text='Exemplo: 2 pacotes.',
    )
    commercial_unit = models.ForeignKey(
        UnitOfMeasure,
        verbose_name='unidade comercial',
        related_name='sales_order_items',
        on_delete=models.PROTECT,
    )
    base_quantity = models.DecimalField(
        'quantidade total na unidade-base',
        max_digits=18,
        decimal_places=6,
        validators=[MinValueValidator(Decimal('0.000001'))],
        help_text=(
            'Quantidade total que sairá do estoque. '
            'Exemplo: 2 pacotes de 300 g = 600 g.'
        ),
    )
    unit_price = models.DecimalField(
        'preço por unidade comercial',
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    discount_amount = models.DecimalField(
        'desconto do item',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['id']
        verbose_name = 'item do pedido de venda'
        verbose_name_plural = 'itens do pedido de venda'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(commercial_quantity__gt=0),
                name='sales_item_commercial_quantity_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(base_quantity__gt=0),
                name='sales_item_base_quantity_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name='sales_item_unit_price_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=0),
                name='sales_item_discount_nonnegative',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.item_id and not self.item.is_active:
            errors['item'] = 'O item selecionado está inativo.'

        if self.item_id and not self.item.is_sellable:
            errors['item'] = (
                'O item precisa estar marcado como '
                '"pode ser vendido".'
            )

        if (
            self.commercial_unit_id
            and not self.commercial_unit.is_active
        ):
            errors['commercial_unit'] = (
                'A unidade comercial selecionada está inativa.'
            )

        if (
            self.discount_amount is not None
            and self.discount_amount > self.subtotal
        ):
            errors['discount_amount'] = (
                'O desconto do item não pode ser maior '
                'que o subtotal.'
            )

        if errors:
            raise ValidationError(errors)

    @property
    def subtotal(self):
        quantity = self.commercial_quantity or Decimal('0.00')
        unit_price = self.unit_price or Decimal('0.00')

        return (quantity * unit_price).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    @property
    def net_total(self):
        discount = self.discount_amount or Decimal('0.00')
        return self.subtotal - discount

    @property
    def allocated_quantity(self):
        if self.pk is None:
            return Decimal('0.000000')

        return sum(
            (
                allocation.quantity
                for allocation in self.stock_allocations.all()
            ),
            Decimal('0.000000'),
        )

    @property
    def quantity_to_allocate(self):
        return self.base_quantity - self.allocated_quantity

    @property
    def cost_total(self):
        if self.pk is None:
            return Decimal('0.00')

        return sum(
            (
                allocation.total_cost
                for allocation in self.stock_allocations.all()
            ),
            Decimal('0.00'),
        )

    @property
    def profit(self):
        return self.net_total - self.cost_total

    @property
    def margin_percentage(self):
        if self.net_total <= 0:
            return None

        return (
            self.profit
            / self.net_total
            * Decimal('100')
        ).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    def __str__(self):
        return (
            f'{self.item} — '
            f'{self.commercial_quantity} '
            f'{self.commercial_unit.symbol}'
        )
class SalesOrderItemAllocation(TimeStampedModel):
    sales_order_item = models.ForeignKey(
        SalesOrderItem,
        verbose_name='item do pedido',
        related_name='stock_allocations',
        on_delete=models.CASCADE,
    )
    stock_lot = models.ForeignKey(
        StockLot,
        verbose_name='lote de estoque',
        related_name='sales_allocations',
        on_delete=models.PROTECT,
    )
    source_location = models.ForeignKey(
        StockLocation,
        verbose_name='local de origem',
        related_name='sales_allocations',
        on_delete=models.PROTECT,
    )
    quantity = models.DecimalField(
        'quantidade na unidade-base',
        max_digits=18,
        decimal_places=6,
        validators=[MinValueValidator(Decimal('0.000001'))],
    )
    unit_cost = models.DecimalField(
        'custo por unidade-base no momento da venda',
        max_digits=18,
        decimal_places=8,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00000000'))],
        help_text=(
            'Será copiado do lote quando a saída '
            'do estoque for registrada.'
        ),
    )
    dispatch_movement = models.OneToOneField(
        StockMovement,
        verbose_name='movimentação de saída',
        related_name='sales_dispatch_allocation',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    return_movement = models.OneToOneField(
        StockMovement,
        verbose_name='movimentação de devolução',
        related_name='sales_return_allocation',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    notes = models.CharField(
        'observações',
        max_length=255,
        blank=True,
    )

    class Meta:
        ordering = [
            'sales_order_item',
            'stock_lot__expiration_date',
            'id',
        ]
        verbose_name = 'separação de estoque da venda'
        verbose_name_plural = 'separações de estoque da venda'
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'sales_order_item',
                    'stock_lot',
                    'source_location',
                ],
                name='sales_allocation_item_lot_location_unique',
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name='sales_allocation_quantity_positive',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(unit_cost__isnull=True)
                    | models.Q(unit_cost__gte=0)
                ),
                name='sales_allocation_unit_cost_nonnegative',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.stock_lot_id
            and self.sales_order_item_id
            and self.stock_lot.item_id
            != self.sales_order_item.item_id
        ):
            errors['stock_lot'] = (
                'O lote selecionado não corresponde '
                'ao item vendido.'
            )

        if (
            self.source_location_id
            and not self.source_location.is_active
        ):
            errors['source_location'] = (
                'O local de origem está inativo.'
            )

        if (
            self.stock_lot_id
            and not self.dispatch_movement_id
        ):
            if self.stock_lot.is_blocked:
                errors['stock_lot'] = (
                    'O lote selecionado está bloqueado.'
                )
            elif self.stock_lot.is_expired:
                errors['stock_lot'] = (
                    'O lote selecionado está vencido.'
                )

        if (
            self.sales_order_item_id
            and self.quantity is not None
        ):
            other_allocated = (
                type(self).objects
                .filter(
                    sales_order_item=self.sales_order_item,
                )
                .exclude(pk=self.pk)
                .aggregate(total=models.Sum('quantity'))['total']
                or Decimal('0.000000')
            )

            if (
                other_allocated + self.quantity
                > self.sales_order_item.base_quantity
            ):
                errors['quantity'] = (
                    'A soma das separações não pode ultrapassar '
                    'a quantidade total do item vendido.'
                )

        if (
            self.stock_lot_id
            and self.source_location_id
            and self.quantity is not None
            and not self.dispatch_movement_id
        ):
            available_quantity = self.stock_lot.quantity_at(
                self.source_location,
            )

            if self.quantity > available_quantity:
                unit_symbol = self.stock_lot.item.base_unit.symbol
                errors['quantity'] = (
                    'Estoque insuficiente neste local. '
                    f'Disponível: {available_quantity} '
                    f'{unit_symbol}.'
                )

        if self.dispatch_movement_id:
            if (
                self.dispatch_movement.movement_type
                != StockMovementType.SALE_DISPATCH
            ):
                errors['dispatch_movement'] = (
                    'A movimentação deve ser uma saída por venda.'
                )

            if (
                self.stock_lot_id
                and self.dispatch_movement.lot_id
                != self.stock_lot_id
            ):
                errors['dispatch_movement'] = (
                    'A movimentação utiliza outro lote.'
                )

            if (
                self.source_location_id
                and self.dispatch_movement.source_location_id
                != self.source_location_id
            ):
                errors['dispatch_movement'] = (
                    'A movimentação utiliza outro local de origem.'
                )

        if self.return_movement_id:
            if not self.dispatch_movement_id:
                errors['return_movement'] = (
                    'Não pode haver devolução sem uma saída anterior.'
                )

            if (
                self.return_movement.movement_type
                != StockMovementType.CUSTOMER_RETURN
            ):
                errors['return_movement'] = (
                    'A movimentação deve ser uma devolução '
                    'de cliente.'
                )

            if (
                self.stock_lot_id
                and self.return_movement.lot_id
                != self.stock_lot_id
            ):
                errors['return_movement'] = (
                    'A devolução utiliza outro lote.'
                )

            if (
                self.source_location_id
                and self.return_movement.destination_location_id
                != self.source_location_id
            ):
                errors['return_movement'] = (
                    'A devolução utiliza outro local de destino.'
                )

        if errors:
            raise ValidationError(errors)

    @property
    def total_cost(self):
        unit_cost = self.unit_cost or Decimal('0.00000000')

        return (self.quantity * unit_cost).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    @property
    def is_dispatched(self):
        return self.dispatch_movement_id is not None

    @property
    def is_returned(self):
        return self.return_movement_id is not None

    def __str__(self):
        unit_symbol = self.stock_lot.item.base_unit.symbol

        return (
            f'{self.stock_lot} — '
            f'{self.quantity} {unit_symbol}'
        )
class SalesOrderPayment(TimeStampedModel):
    sales_order = models.ForeignKey(
        SalesOrder,
        verbose_name='pedido de venda',
        related_name='payments',
        on_delete=models.CASCADE,
    )
    amount = models.DecimalField(
        'valor cobrado',
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    fee_amount = models.DecimalField(
        'taxa do meio de pagamento',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text=(
            'Exemplo: taxa do cartão ou do Mercado Pago.'
        ),
    )
    method = models.CharField(
        'forma de pagamento',
        max_length=20,
        choices=SalesPaymentMethod.choices,
    )
    financial_account = models.ForeignKey(
        'finance.FinancialAccount',
        verbose_name='conta de recebimento',
        related_name='sales_payments',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text=(
            'Conta em que o recebimento do Pastifício '
            'será registrado.'
        ),
    )
    due_date = models.DateField(
        'data de vencimento',
        default=timezone.localdate,
        db_index=True,
    )
    paid_at = models.DateTimeField(
        'pago em',
        null=True,
        blank=True,
    )
    installment_number = models.PositiveSmallIntegerField(
        'número da parcela',
        default=1,
        validators=[MinValueValidator(1)],
    )
    installment_count = models.PositiveSmallIntegerField(
        'total de parcelas',
        default=1,
        validators=[MinValueValidator(1)],
    )
    status = models.CharField(
        'situação',
        max_length=20,
        choices=SalesPaymentStatus.choices,
        default=SalesPaymentStatus.PENDING,
        db_index=True,
    )
    processor_reference = models.CharField(
        'referência da transação',
        max_length=100,
        blank=True,
        help_text=(
            'Identificador do Pix, cartão ou intermediador, '
            'quando disponível.'
        ),
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='recebido por',
        related_name='sales_payments_received',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['due_date', 'installment_number', 'id']
        verbose_name = 'pagamento do pedido'
        verbose_name_plural = 'pagamentos do pedido'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='sales_payment_amount_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(fee_amount__gte=0),
                name='sales_payment_fee_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(installment_number__gt=0),
                name='sales_payment_installment_number_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(installment_count__gt=0),
                name='sales_payment_installment_count_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    installment_number__lte=models.F(
                        'installment_count',
                    ),
                ),
                name='sales_payment_installment_valid',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    fee_amount__lte=models.F('amount'),
                ),
                name='sales_payment_fee_not_greater_than_amount',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.installment_number
            and self.installment_count
            and self.installment_number > self.installment_count
        ):
            errors['installment_number'] = (
                'O número da parcela não pode ser maior '
                'que o total de parcelas.'
            )

        if (
            self.amount is not None
            and self.fee_amount is not None
            and self.fee_amount > self.amount
        ):
            errors['fee_amount'] = (
                'A taxa não pode ser maior que o pagamento.'
            )

        completed_statuses = {
            SalesPaymentStatus.PAID,
            SalesPaymentStatus.REFUNDED,
        }

        if (
            self.status in completed_statuses
            and not self.paid_at
        ):
            errors['paid_at'] = (
                'Informe a data do pagamento.'
            )

        if (
            self.status == SalesPaymentStatus.PENDING
            and self.paid_at
        ):
            errors['status'] = (
                'Um pagamento com data informada '
                'não pode continuar pendente.'
            )

        if errors:
            raise ValidationError(errors)

    @property
    def net_amount(self):
        if self.status != SalesPaymentStatus.PAID:
            return Decimal('0.00')

        return self.amount - self.fee_amount

    @property
    def is_overdue(self):
        return (
            self.status == SalesPaymentStatus.PENDING
            and self.due_date < timezone.localdate()
        )

    @property
    def current_status(self):
        if self.is_overdue:
            return 'Atrasado'

        return self.get_status_display()

    def __str__(self):
        return (
            f'{self.sales_order.code} — '
            f'parcela {self.installment_number}/'
            f'{self.installment_count}'
        )