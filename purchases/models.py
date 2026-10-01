from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MinValueValidator,
)
from django.db import models
from django.utils import timezone
from catalog.models import Item, UnitOfMeasure
from core.models import TimeStampedModel


class SupplierType(models.TextChoices):
    COMPANY = 'company', 'Empresa'
    INDIVIDUAL = 'individual', 'Pessoa física'
    INFORMAL = 'informal', 'Informal'


class Supplier(TimeStampedModel):
    name = models.CharField(
        'nome',
        max_length=150,
        db_index=True,
    )
    supplier_type = models.CharField(
        'tipo',
        max_length=20,
        choices=SupplierType.choices,
        default=SupplierType.COMPANY,
    )
    tax_id = models.CharField(
        'CPF/CNPJ',
        max_length=18,
        blank=True,
        db_index=True,
    )
    contact_name = models.CharField(
        'pessoa de contato',
        max_length=150,
        blank=True,
    )
    phone = models.CharField(
        'telefone',
        max_length=30,
        blank=True,
    )
    email = models.EmailField(
        'e-mail',
        blank=True,
    )
    address = models.TextField(
        'endereço',
        blank=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )
    is_active = models.BooleanField(
        'ativo',
        default=True,
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'fornecedor'
        verbose_name_plural = 'fornecedores'

    def __str__(self):
        return self.name

class PurchaseStatus(models.TextChoices):
    DRAFT = 'draft', 'Rascunho'
    ORDERED = 'ordered', 'Solicitada'
    PARTIALLY_RECEIVED = 'partially_received', 'Parcialmente recebida'
    RECEIVED = 'received', 'Recebida'
    CANCELLED = 'cancelled', 'Cancelada'


class PurchaseChannel(models.TextChoices):
    PHYSICAL_STORE = 'physical_store', 'Loja física'
    ONLINE = 'online', 'Online'
    FAIR = 'fair', 'Feira ou compra informal'
    DIRECT = 'direct', 'Contato direto'
    OTHER = 'other', 'Outro'


class PurchaseDocumentType(models.TextChoices):
    INVOICE = 'invoice', 'NF-e ou nota fiscal'
    NFCE = 'nfce', 'NFC-e (modelo 65)'
    FISCAL_RECEIPT = 'fiscal_receipt', 'Cupom fiscal (ECF)'
    RECEIPT = 'receipt', 'Recibo'
    NO_DOCUMENT = 'no_document', 'Sem documento'
    OTHER = 'other', 'Outro'

class Purchase(TimeStampedModel):
    supplier = models.ForeignKey(
        Supplier,
        verbose_name='fornecedor',
        related_name='purchases',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    purchase_date = models.DateField(
        'data da compra',
        default=timezone.localdate,
        db_index=True,
    )
    received_date = models.DateField(
        'data de recebimento',
        null=True,
        blank=True,
    )
    status = models.CharField(
        'situação',
        max_length=20,
        choices=PurchaseStatus.choices,
        default=PurchaseStatus.DRAFT,
        db_index=True,
    )
    channel = models.CharField(
        'canal',
        max_length=20,
        choices=PurchaseChannel.choices,
        default=PurchaseChannel.PHYSICAL_STORE,
    )
    document_type = models.CharField(
        'tipo de comprovante',
        max_length=20,
        choices=PurchaseDocumentType.choices,
        default=PurchaseDocumentType.NO_DOCUMENT,
    )
    document_number = models.CharField(
        'número do documento',
        max_length=100,
        blank=True,
    )
    freight_amount = models.DecimalField(
        'frete',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    discount_amount = models.DecimalField(
        'desconto geral',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    other_costs_amount = models.DecimalField(
        'outros custos',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    declared_total = models.DecimalField(
        'total informado no comprovante',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    non_business_amount = models.DecimalField(
        'valor não pertencente ao Pastifício',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text=(
            'Parcela pessoal ou alheia ao negócio incluída '
            'no mesmo comprovante.'
        ),
    )
    purchased_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='comprado por',
        related_name='purchases_made',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='cadastrado por',
        related_name='purchase_records_created',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['-purchase_date', '-id']
        verbose_name = 'compra'
        verbose_name_plural = 'compras'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(freight_amount__gte=0),
                name='purchase_freight_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=0),
                name='purchase_discount_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(other_costs_amount__gte=0),
                name='purchase_other_costs_nonnegative',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(declared_total__isnull=True)
                    | models.Q(declared_total__gte=0)
                ),
                name='purchase_declared_total_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(non_business_amount__gte=0),
                name='purchase_non_business_nonnegative',
                ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.purchase_date
            and self.received_date
            and self.received_date < self.purchase_date
        ):
            errors['received_date'] = (
                'A data de recebimento não pode ser anterior à compra.'
            )

        if (
            self.status == PurchaseStatus.RECEIVED
            and not self.received_date
        ):
            errors['received_date'] = (
                'Informe a data de recebimento para uma compra recebida.'
            )
        if (
            self.declared_total is not None
            and self.non_business_amount is not None
            and self.non_business_amount > self.declared_total
        ):
            errors['non_business_amount'] = (
                'O valor fora do Pastifício não pode ser maior '
                'que o total do comprovante.'
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
    def calculated_total(self):
        return (
            self.items_net_total
            + self.freight_amount
            + self.other_costs_amount
            - self.discount_amount
        )

    @property
    def declared_difference(self):
        if self.declared_total is None:
            return None

        non_business_amount = (
            self.non_business_amount or Decimal('0.00')
        )

        return self.declared_total - (
            self.calculated_total + non_business_amount
        )

    def __str__(self):
        supplier_name = (
            self.supplier.name
            if self.supplier
            else 'Fornecedor não informado'
        )
        purchase_date = (
            self.purchase_date.strftime('%d/%m/%Y')
            if self.purchase_date
            else 'sem data'
        )
        purchase_id = self.pk or 'nova'

        return f'Compra #{purchase_id} - {supplier_name} - {purchase_date}'

class PurchaseItem(TimeStampedModel):
    purchase = models.ForeignKey(
        Purchase,
        verbose_name='compra',
        related_name='items',
        on_delete=models.CASCADE,
    )
    item = models.ForeignKey(
        Item,
        verbose_name='item',
        related_name='purchase_items',
        on_delete=models.PROTECT,
    )
    commercial_quantity = models.DecimalField(
        'quantidade comercial',
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0001'))],
    )
    commercial_unit = models.ForeignKey(
        UnitOfMeasure,
        verbose_name='unidade comercial',
        related_name='purchase_items',
        on_delete=models.PROTECT,
    )
    base_quantity = models.DecimalField(
        'quantidade efetiva na unidade-base',
        max_digits=16,
        decimal_places=6,
        validators=[MinValueValidator(Decimal('0.000001'))],
        help_text=(
            'Quantidade efetivamente recebida, expressa na '
            'unidade-base cadastrada para o item.'
        ),
    )
    unit_price = models.DecimalField(
        'preço por unidade comercial',
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0.0000'))],
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
        verbose_name = 'item da compra'
        verbose_name_plural = 'itens da compra'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(commercial_quantity__gt=0),
                name='purchase_item_commercial_qty_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(base_quantity__gt=0),
                name='purchase_item_base_qty_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name='purchase_item_unit_price_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=0),
                name='purchase_item_discount_nonnegative',
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.discount_amount is not None
            and self.discount_amount > self.subtotal
        ):
            raise ValidationError({
                'discount_amount': (
                    'O desconto do item não pode ser maior '
                    'que o seu subtotal.'
                ),
            })

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
    def allocation_ratio(self):
        purchase_total = self.purchase.items_net_total

        if purchase_total <= 0:
            return Decimal('0.00')

        return self.net_total / purchase_total

    @property
    def allocated_freight(self):
        return self.allocation_ratio * self.purchase.freight_amount

    @property
    def allocated_other_costs(self):
        return self.allocation_ratio * self.purchase.other_costs_amount

    @property
    def allocated_general_discount(self):
        return self.allocation_ratio * self.purchase.discount_amount

    @property
    def effective_cost(self):
        return (
            self.net_total
            + self.allocated_freight
            + self.allocated_other_costs
            - self.allocated_general_discount
        )

    @property
    def cost_per_base_unit(self):
        if not self.base_quantity or self.base_quantity <= 0:
            return None

        return self.effective_cost / self.base_quantity

    def __str__(self):
        return (
            f'{self.item} - '
            f'{self.commercial_quantity} {self.commercial_unit.symbol}'
        )

class PaymentMethod(models.TextChoices):
    PIX = 'pix', 'Pix'
    CASH = 'cash', 'Dinheiro'
    DEBIT_CARD = 'debit_card', 'Cartão de débito'
    CREDIT_CARD = 'credit_card', 'Cartão de crédito'
    CRYPTO = 'crypto', 'Cripto'
    BANK_TRANSFER = 'bank_transfer', 'Transferência bancária'
    BOLETO = 'boleto', 'Boleto'
    OTHER = 'other', 'Outro'


class PaymentStatus(models.TextChoices):
    PENDING = 'pending', 'Pendente'
    PAID = 'paid', 'Pago'
    CANCELLED = 'cancelled', 'Cancelado'
    REFUNDED = 'refunded', 'Estornado'


class FundingSource(models.TextChoices):
    BUSINESS_FUNDS = 'business_funds', 'Recursos do Pastifício'
    OWNER_CONTRIBUTION = 'owner_contribution', 'Aporte pessoal'
    OWNER_REIMBURSABLE = (
        'owner_reimbursable',
        'Adiantamento pessoal reembolsável',
    )
    OTHER = 'other', 'Outra origem',

class PurchasePayment(TimeStampedModel):
    purchase = models.ForeignKey(
        Purchase,
        verbose_name='compra',
        related_name='payments',
        on_delete=models.CASCADE,
    )
    amount = models.DecimalField(
        'valor',
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    method = models.CharField(
        'forma de pagamento',
        max_length=20,
        choices=PaymentMethod.choices,
    )
    funding_source = models.CharField(
        'origem do dinheiro',
        max_length=20,
        choices=FundingSource.choices,
        default=FundingSource.BUSINESS_FUNDS,
    )
    financial_account = models.ForeignKey(
        'finance.FinancialAccount',
        verbose_name='conta de pagamento',
        related_name='purchase_payments',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text=(
            'Conta utilizada quando o pagamento é feito '
            'com recursos do Pastifício.'
        ),
    )
    funded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='recursos pessoais de',
        related_name='purchase_payments_funded',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text=(
            'Pessoa que forneceu o dinheiro em um aporte '
            'ou adiantamento pessoal.'
        ),
    )
    due_date = models.DateField(
        'data de vencimento',
        default=timezone.localdate,
        db_index=True,
    )
    payment_date = models.DateField(
        'data do pagamento',
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
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['due_date', 'installment_number', 'id']
        verbose_name = 'pagamento da compra'
        verbose_name_plural = 'pagamentos da compra'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='purchase_payment_amount_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(installment_number__gt=0),
                name='purchase_payment_installment_number_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(installment_count__gt=0),
                name='purchase_payment_installment_count_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    installment_number__lte=models.F(
                        'installment_count',
                    ),
                ),
                name='purchase_payment_installment_valid',
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
            self.status in [
                PaymentStatus.PAID,
                PaymentStatus.REFUNDED,
            ]
            and not self.payment_date
        ):
            errors['payment_date'] = (
                'Informe a data para um pagamento pago ou estornado.'
            )

        if (
            self.status == PaymentStatus.PENDING
            and self.payment_date
        ):
            errors['status'] = (
                'Um pagamento com data informada não pode '
                'continuar como pendente.'
            )

        if errors:
            raise ValidationError(errors)

    @property
    def is_overdue(self):
        return (
            self.status == PaymentStatus.PENDING
            and self.due_date < timezone.localdate()
        )

    @property
    def current_status(self):
        if self.is_overdue:
            return 'Atrasado'

        return self.get_status_display()

    def __str__(self):
        return (
            f'Pagamento {self.installment_number}/'
            f'{self.installment_count} - Compra #{self.purchase_id}'
        )

class PurchaseAttachmentType(models.TextChoices):
    INVOICE = 'invoice', 'NF-e ou nota fiscal'
    NFCE = 'nfce', 'NFC-e (modelo 65)'
    FISCAL_RECEIPT = 'fiscal_receipt', 'Cupom fiscal (ECF)'
    RECEIPT = 'receipt', 'Recibo'
    PAYMENT_PROOF = 'payment_proof', 'Comprovante de pagamento'
    OTHER = 'other', 'Outro'


def purchase_document_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    purchase_date = instance.purchase.purchase_date
    unique_name = f'{uuid4().hex}{extension}'

    return (
        f'purchases/{purchase_date:%Y}/'
        f'{purchase_date:%m}/{unique_name}'
    )


class PurchaseDocument(TimeStampedModel):
    purchase = models.ForeignKey(
        Purchase,
        verbose_name='compra',
        related_name='documents',
        on_delete=models.CASCADE,
    )
    document_type = models.CharField(
        'tipo de documento',
        max_length=20,
        choices=PurchaseAttachmentType.choices,
        default=PurchaseAttachmentType.OTHER,
    )
    file = models.FileField(
        'arquivo',
        upload_to=purchase_document_upload_to,
        validators=[
            FileExtensionValidator(
                allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'],
            ),
        ],
    )
    description = models.CharField(
        'descrição',
        max_length=255,
        blank=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='enviado por',
        related_name='purchase_documents_uploaded',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['id']
        verbose_name = 'documento da compra'
        verbose_name_plural = 'documentos da compra'

    def __str__(self):
        return (
            f'{self.get_document_type_display()} - '
            f'Compra #{self.purchase_id}'
        )