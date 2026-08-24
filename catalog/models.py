from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from core.models import TimeStampedModel


class MeasurementDimension(models.TextChoices):
    MASS = 'mass', 'Massa'
    VOLUME = 'volume', 'Volume'
    COUNT = 'count', 'Contagem'
    TIME = 'time', 'Tempo'
    ENERGY = 'energy', 'Energia'
    LENGTH = 'length', 'Comprimento'
    OTHER = 'other', 'Outro'


class UnitOfMeasure(TimeStampedModel):
    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name='código',
    )
    name = models.CharField(
        max_length=100,
        verbose_name='nome',
    )
    symbol = models.CharField(
        max_length=20,
        verbose_name='símbolo',
    )
    dimension = models.CharField(
        max_length=20,
        choices=MeasurementDimension.choices,
        verbose_name='dimensão',
    )
    factor_to_base_unit = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        default=Decimal('1'),
        validators=[MinValueValidator(Decimal('0.000001'))],
        verbose_name='fator para a unidade-base',
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='ativo',
    )

    class Meta:
        ordering = ['dimension', 'name']
        verbose_name = 'unidade de medida'
        verbose_name_plural = 'unidades de medida'

    def __str__(self):
        return f'{self.name} ({self.symbol})'

class ItemCategory(TimeStampedModel):
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name='nome',
    )
    description = models.TextField(
        blank=True,
        verbose_name='descrição',
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='ativo',
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'categoria de item'
        verbose_name_plural = 'categorias de itens'

    def __str__(self):
        return self.name

    
class ItemType(models.TextChoices):
    INGREDIENT = 'ingredient', 'Ingrediente ou insumo'
    PACKAGING = 'packaging', 'Embalagem'
    CONSUMABLE = 'consumable', 'Consumível'
    INTERMEDIATE = 'intermediate', 'Produto intermediário'
    FINISHED_PRODUCT = 'finished_product', 'Produto acabado'
    RESALE_PRODUCT = 'resale_product', 'Produto para revenda'
    EQUIPMENT = 'equipment', 'Equipamento'
    SERVICE = 'service', 'Serviço'
    OTHER = 'other', 'Outro'


class Item(TimeStampedModel):
    name = models.CharField(
        max_length=150,
        verbose_name='nome',
    )
    sku = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        verbose_name='SKU',
    )
    item_type = models.CharField(
        max_length=30,
        choices=ItemType.choices,
        db_index=True,
        verbose_name='tipo de item',
    )
    category = models.ForeignKey(
        ItemCategory,
        on_delete=models.PROTECT,
        related_name='items',
        null=True,
        blank=True,
        verbose_name='categoria',
    )
    base_unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='base_unit_items',
        verbose_name='unidade-base',
    )
    description = models.TextField(
        blank=True,
        verbose_name='descrição',
    )
    net_content_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.000001'))],
        verbose_name='quantidade líquida',
    )
    net_content_unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='net_content_items',
        null=True,
        blank=True,
        verbose_name='unidade do conteúdo líquido',
    )
    is_purchasable = models.BooleanField(
        default=False,
        verbose_name='pode ser comprado',
    )
    is_producible = models.BooleanField(
        default=False,
        verbose_name='pode ser produzido',
    )
    is_sellable = models.BooleanField(
        default=False,
        verbose_name='pode ser vendido',
    )
    tracks_inventory = models.BooleanField(
        default=True,
        verbose_name='controla estoque',
    )
    shelf_life_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='validade em dias',
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='ativo',
    )
    notes = models.TextField(
        blank=True,
        verbose_name='observações',
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'item'
        verbose_name_plural = 'itens'
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        net_content_quantity__isnull=True,
                        net_content_unit__isnull=True,
                    )
                    | models.Q(
                        net_content_quantity__isnull=False,
                        net_content_unit__isnull=False,
                    )
                ),
                name='item_net_content_fields_together',
            ),
        ]

    def __str__(self):
        if self.sku:
            return f'{self.name} [{self.sku}]'
        return self.name