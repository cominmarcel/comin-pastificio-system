from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from catalog.models import Item
from core.models import TimeStampedModel


class RecipeVersionStatus(models.TextChoices):
    DRAFT = 'draft', 'Rascunho'
    ACTIVE = 'active', 'Ativa'
    ARCHIVED = 'archived', 'Arquivada'


class AdditionalCostType(models.TextChoices):
    ENERGY = 'energy', 'Energia elétrica'
    GAS = 'gas', 'Gás'
    WATER = 'water', 'Água'
    EQUIPMENT = 'equipment', 'Uso ou depreciação de equipamento'
    CONSUMABLE = 'consumable', 'Material de consumo'
    OTHER = 'other', 'Outro'


class Recipe(TimeStampedModel):
    code = models.CharField(
        'código',
        max_length=30,
        unique=True,
        help_text='Identificador como REC-MASSA-001.',
    )
    name = models.CharField(
        'nome',
        max_length=150,
    )
    output_item = models.ForeignKey(
        Item,
        verbose_name='item produzido',
        related_name='recipes',
        on_delete=models.PROTECT,
    )
    description = models.TextField(
        'descrição',
        blank=True,
    )
    is_active = models.BooleanField(
        'ativa',
        default=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='criada por',
        related_name='recipes_created',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'ficha técnica'
        verbose_name_plural = 'fichas técnicas'

    def clean(self):
        super().clean()

        if (
            self.output_item_id
            and not self.output_item.is_producible
        ):
            raise ValidationError({
                'output_item': (
                    'O item precisa estar marcado como '
                    '"pode ser produzido".'
                ),
            })

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} [{self.code}]'


class RecipeVersion(TimeStampedModel):
    recipe = models.ForeignKey(
        Recipe,
        verbose_name='ficha técnica',
        related_name='versions',
        on_delete=models.CASCADE,
    )
    version = models.PositiveIntegerField(
        'versão',
        default=1,
        validators=[MinValueValidator(1)],
    )
    status = models.CharField(
        'situação',
        max_length=20,
        choices=RecipeVersionStatus.choices,
        default=RecipeVersionStatus.DRAFT,
        db_index=True,
    )
    yield_quantity = models.DecimalField(
        'rendimento na unidade-base do produto',
        max_digits=18,
        decimal_places=6,
        validators=[MinValueValidator(Decimal('0.000001'))],
        help_text=(
            'Quantidade total obtida na unidade-base '
            'do item produzido.'
        ),
    )
    active_time_minutes = models.PositiveIntegerField(
        'tempo de trabalho ativo em minutos',
        default=0,
        help_text=(
            'Tempo efetivamente trabalhado, usado no '
            'cálculo da mão de obra.'
        ),
    )
    total_time_minutes = models.PositiveIntegerField(
        'tempo total do processo em minutos',
        null=True,
        blank=True,
        help_text=(
            'Inclui descansos, resfriamento, congelamento '
            'e outras esperas.'
        ),
    )
    hourly_labor_cost = models.DecimalField(
        'custo da hora de trabalho',
        max_digits=12,
        decimal_places=2,
        default=Decimal('25.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    valid_from = models.DateField(
        'válida a partir de',
        default=timezone.localdate,
        db_index=True,
    )
    valid_until = models.DateField(
        'válida até',
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='criada por',
        related_name='recipe_versions_created',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='aprovada por',
        related_name='recipe_versions_approved',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(
        'aprovada em',
        null=True,
        blank=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['recipe', '-version']
        verbose_name = 'versão da ficha técnica'
        verbose_name_plural = 'versões das fichas técnicas'
        constraints = [
            models.UniqueConstraint(
                fields=['recipe', 'version'],
                name='recipe_version_unique',
            ),
            models.UniqueConstraint(
                fields=['recipe'],
                condition=models.Q(
                    status=RecipeVersionStatus.ACTIVE,
                ),
                name='recipe_one_active_version',
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name='recipe_version_number_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(yield_quantity__gt=0),
                name='recipe_version_yield_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(hourly_labor_cost__gte=0),
                name='recipe_version_labor_cost_nonnegative',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(total_time_minutes__isnull=True)
                    | models.Q(
                        total_time_minutes__gte=models.F(
                            'active_time_minutes',
                        ),
                    )
                ),
                name='recipe_total_time_valid',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(valid_until__isnull=True)
                    | models.Q(valid_until__gte=models.F('valid_from'))
                ),
                name='recipe_version_valid_dates',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.total_time_minutes is not None
            and self.total_time_minutes < self.active_time_minutes
        ):
            errors['total_time_minutes'] = (
                'O tempo total não pode ser menor '
                'que o tempo de trabalho ativo.'
            )

        if (
            self.valid_until
            and self.valid_from
            and self.valid_until < self.valid_from
        ):
            errors['valid_until'] = (
                'A data final não pode ser anterior à inicial.'
            )

        if errors:
            raise ValidationError(errors)

    @property
    def ingredients_cost(self):
        return sum(
            (ingredient.total_cost for ingredient in self.ingredients.all()),
            Decimal('0.00'),
        )

    @property
    def additional_costs_total(self):
        return sum(
            (cost.amount for cost in self.additional_costs.all()),
            Decimal('0.00'),
        )

    @property
    def labor_cost(self):
        hours = (
            Decimal(self.active_time_minutes)
            / Decimal('60')
        )

        return (hours * self.hourly_labor_cost).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    @property
    def total_cost(self):
        return (
            self.ingredients_cost
            + self.additional_costs_total
            + self.labor_cost
        )

    @property
    def cost_per_base_unit(self):
        if not self.yield_quantity or self.yield_quantity <= 0:
            return None

        return self.total_cost / self.yield_quantity

    def __str__(self):
        return f'{self.recipe} — versão {self.version}'
class RecipeIngredient(TimeStampedModel):
    recipe_version = models.ForeignKey(
        RecipeVersion,
        verbose_name='versão da ficha técnica',
        related_name='ingredients',
        on_delete=models.CASCADE,
    )
    sequence = models.PositiveIntegerField(
        'ordem',
        default=1,
        validators=[MinValueValidator(1)],
    )
    item = models.ForeignKey(
        Item,
        verbose_name='ingrediente ou insumo',
        related_name='recipe_uses',
        on_delete=models.PROTECT,
    )
    quantity = models.DecimalField(
        'quantidade na unidade-base',
        max_digits=18,
        decimal_places=6,
        validators=[MinValueValidator(Decimal('0.000001'))],
    )
    unit_cost_override = models.DecimalField(
        'custo informado por unidade-base',
        max_digits=18,
        decimal_places=8,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00000000'))],
        help_text=(
            'Deixe vazio para utilizar o custo do lote '
            'mais recente no estoque.'
        ),
    )
    stage = models.CharField(
        'etapa de utilização',
        max_length=100,
        blank=True,
        help_text='Exemplo: massa, recheio ou finalização.',
    )
    notes = models.CharField(
        'observações',
        max_length=255,
        blank=True,
    )

    class Meta:
        ordering = ['sequence', 'id']
        verbose_name = 'ingrediente da ficha técnica'
        verbose_name_plural = 'ingredientes da ficha técnica'
        constraints = [
            models.UniqueConstraint(
                fields=['recipe_version', 'sequence'],
                name='recipe_ingredient_sequence_unique',
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gt=0),
                name='recipe_ingredient_sequence_positive',
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name='recipe_ingredient_quantity_positive',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(unit_cost_override__isnull=True)
                    | models.Q(unit_cost_override__gte=0)
                ),
                name='recipe_ingredient_cost_nonnegative',
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.item_id
            and self.recipe_version_id
            and self.item_id
            == self.recipe_version.recipe.output_item_id
        ):
            raise ValidationError({
                'item': (
                    'O próprio produto final não pode ser '
                    'ingrediente direto da sua ficha técnica.'
                ),
            })

    @property
    def resolved_unit_cost(self):
        if self.unit_cost_override is not None:
            return self.unit_cost_override

        latest_cost = (
            self.item.stock_lots
            .filter(unit_cost__isnull=False)
            .order_by('-received_date', '-id')
            .values_list('unit_cost', flat=True)
            .first()
        )

        return latest_cost or Decimal('0.00000000')

    @property
    def total_cost(self):
        return (
            self.quantity * self.resolved_unit_cost
        ).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    def __str__(self):
        unit_symbol = self.item.base_unit.symbol

        return (
            f'{self.item} — '
            f'{self.quantity} {unit_symbol}'
        )


class RecipeAdditionalCost(TimeStampedModel):
    recipe_version = models.ForeignKey(
        RecipeVersion,
        verbose_name='versão da ficha técnica',
        related_name='additional_costs',
        on_delete=models.CASCADE,
    )
    cost_type = models.CharField(
        'tipo de custo',
        max_length=20,
        choices=AdditionalCostType.choices,
    )
    description = models.CharField(
        'descrição',
        max_length=150,
    )
    amount = models.DecimalField(
        'valor',
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    notes = models.CharField(
        'observações',
        max_length=255,
        blank=True,
    )

    class Meta:
        ordering = ['cost_type', 'description', 'id']
        verbose_name = 'custo adicional da ficha técnica'
        verbose_name_plural = 'custos adicionais da ficha técnica'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0),
                name='recipe_additional_cost_nonnegative',
            ),
        ]

    def __str__(self):
        return f'{self.description} — R$ {self.amount}'


class RecipeStep(TimeStampedModel):
    recipe_version = models.ForeignKey(
        RecipeVersion,
        verbose_name='versão da ficha técnica',
        related_name='steps',
        on_delete=models.CASCADE,
    )
    sequence = models.PositiveIntegerField(
        'ordem',
        default=1,
        validators=[MinValueValidator(1)],
    )
    phase = models.CharField(
        'fase',
        max_length=100,
        blank=True,
        help_text='Exemplo: dia 1, dia 2, massa ou recheio.',
    )
    title = models.CharField(
        'título',
        max_length=150,
    )
    instructions = models.TextField(
        'instruções',
    )
    duration_minutes = models.PositiveIntegerField(
        'duração estimada em minutos',
        null=True,
        blank=True,
    )
    requires_active_work = models.BooleanField(
        'exige trabalho ativo',
        default=True,
        help_text=(
            'Desmarque para descanso, resfriamento '
            'ou congelamento sem trabalho contínuo.'
        ),
    )

    class Meta:
        ordering = ['sequence', 'id']
        verbose_name = 'etapa da ficha técnica'
        verbose_name_plural = 'etapas da ficha técnica'
        constraints = [
            models.UniqueConstraint(
                fields=['recipe_version', 'sequence'],
                name='recipe_step_sequence_unique',
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gt=0),
                name='recipe_step_sequence_positive',
            ),
        ]

    def __str__(self):
        return f'{self.sequence}. {self.title}'