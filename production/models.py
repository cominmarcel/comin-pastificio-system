from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel
from inventory.models import (
    StockLocation,
    StockLot,
    StockMovement,
    StockMovementType,
)
from recipes.models import (
    RecipeIngredient,
    RecipeStep,
    RecipeVersion,
    RecipeVersionStatus,
)


class ProductionStatus(models.TextChoices):
    PLANNED = 'planned', 'Planejada'
    IN_PROGRESS = 'in_progress', 'Em produção'
    COMPLETED = 'completed', 'Concluída'
    CANCELLED = 'cancelled', 'Cancelada'


class ProductionStepStatus(models.TextChoices):
    PENDING = 'pending', 'Pendente'
    IN_PROGRESS = 'in_progress', 'Em andamento'
    COMPLETED = 'completed', 'Concluída'
    SKIPPED = 'skipped', 'Ignorada'


class ProductionBatch(TimeStampedModel):
    code = models.CharField(
        'código do lote de produção',
        max_length=50,
        unique=True,
        help_text='Identificador como PROD-2026-000001.',
    )
    recipe_version = models.ForeignKey(
        RecipeVersion,
        verbose_name='versão da ficha técnica',
        related_name='production_batches',
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        'situação',
        max_length=20,
        choices=ProductionStatus.choices,
        default=ProductionStatus.PLANNED,
        db_index=True,
    )
    planned_quantity = models.DecimalField(
        'quantidade planejada',
        max_digits=18,
        decimal_places=6,
        validators=[MinValueValidator(Decimal('0.000001'))],
        help_text=(
            'Quantidade planejada na unidade-base '
            'do item produzido.'
        ),
    )
    actual_quantity = models.DecimalField(
        'quantidade efetivamente produzida',
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.000001'))],
    )
    planned_date = models.DateField(
        'data planejada',
        default=timezone.localdate,
        db_index=True,
    )
    started_at = models.DateTimeField(
        'iniciada em',
        null=True,
        blank=True,
    )
    completed_at = models.DateTimeField(
        'concluída em',
        null=True,
        blank=True,
    )
    actual_active_time_minutes = models.PositiveIntegerField(
        'tempo ativo real em minutos',
        null=True,
        blank=True,
    )
    actual_additional_cost = models.DecimalField(
        'custos adicionais reais',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text=(
            'Se ficar vazio, será usada a proporção dos '
            'custos previstos na ficha técnica.'
        ),
    )
    destination_location = models.ForeignKey(
        StockLocation,
        verbose_name='local de destino do produto',
        related_name='production_batches_received',
        on_delete=models.PROTECT,
    )
    expiration_date = models.DateField(
        'validade do lote produzido',
        null=True,
        blank=True,
        db_index=True,
    )
    output_lot = models.OneToOneField(
        StockLot,
        verbose_name='lote de estoque produzido',
        related_name='production_batch',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    output_movement = models.OneToOneField(
        StockMovement,
        verbose_name='movimentação de entrada do produto',
        related_name='production_output_batch',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='responsável pela produção',
        related_name='production_batches_responsible',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='criada por',
        related_name='production_batches_created',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='concluída por',
        related_name='production_batches_completed',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['-planned_date', '-id']
        verbose_name = 'lote de produção'
        verbose_name_plural = 'lotes de produção'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(planned_quantity__gt=0),
                name='production_planned_quantity_positive',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(actual_quantity__isnull=True)
                    | models.Q(actual_quantity__gt=0)
                ),
                name='production_actual_quantity_positive',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(actual_additional_cost__isnull=True)
                    | models.Q(actual_additional_cost__gte=0)
                ),
                name='production_additional_cost_nonnegative',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(started_at__isnull=True)
                    | models.Q(completed_at__isnull=True)
                    | models.Q(completed_at__gte=models.F('started_at'))
                ),
                name='production_completion_after_start',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if (
            self._state.adding
            and self.recipe_version_id
            and self.recipe_version.status
            != RecipeVersionStatus.ACTIVE
        ):
            errors['recipe_version'] = (
                'A versão da ficha técnica precisa estar ativa.'
            )

        if (
            self.destination_location_id
            and not self.destination_location.is_active
        ):
            errors['destination_location'] = (
                'O local de destino está inativo.'
            )

        if (
            self.expiration_date
            and self.planned_date
            and self.expiration_date < self.planned_date
        ):
            errors['expiration_date'] = (
                'A validade não pode ser anterior '
                'à data planejada.'
            )

        if (
            self.started_at
            and self.completed_at
            and self.completed_at < self.started_at
        ):
            errors['completed_at'] = (
                'A conclusão não pode ser anterior ao início.'
            )

        if (
            self.status == ProductionStatus.IN_PROGRESS
            and not self.started_at
        ):
            errors['started_at'] = (
                'Uma produção em andamento precisa '
                'ter data de início.'
            )

        if self.status == ProductionStatus.COMPLETED:
            if not self.actual_quantity:
                errors['actual_quantity'] = (
                    'Informe a quantidade efetivamente produzida.'
                )

            if not self.completed_at:
                errors['completed_at'] = (
                    'Informe quando a produção foi concluída.'
                )

            if not self.output_lot_id:
                errors['output_lot'] = (
                    'A produção concluída precisa gerar '
                    'um lote de estoque.'
                )

            if not self.output_movement_id:
                errors['output_movement'] = (
                    'A produção concluída precisa gerar '
                    'uma entrada no estoque.'
                )

        if (
            self.output_lot_id
            and self.recipe_version_id
            and self.output_lot.item_id
            != self.recipe_version.recipe.output_item_id
        ):
            errors['output_lot'] = (
                'O item do lote produzido não corresponde '
                'ao produto da ficha técnica.'
            )

        if errors:
            raise ValidationError(errors)

    @property
    def output_item(self):
        return self.recipe_version.recipe.output_item

    @property
    def scale_factor(self):
        recipe_yield = self.recipe_version.yield_quantity

        if not recipe_yield or recipe_yield <= 0:
            return Decimal('0.00')

        return self.planned_quantity / recipe_yield

    @property
    def planned_cost(self):
        return (
            self.recipe_version.total_cost * self.scale_factor
        ).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    @property
    def materials_cost(self):
        return sum(
            (
                material.actual_cost
                for material in self.materials.all()
                if material.actual_quantity is not None
            ),
            Decimal('0.00'),
        )

    @property
    def labor_cost(self):
        if self.actual_active_time_minutes is None:
            minutes = (
                Decimal(self.recipe_version.active_time_minutes)
                * self.scale_factor
            )
        else:
            minutes = Decimal(self.actual_active_time_minutes)

        hours = minutes / Decimal('60')

        return (
            hours * self.recipe_version.hourly_labor_cost
        ).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    @property
    def additional_cost(self):
        if self.actual_additional_cost is not None:
            return self.actual_additional_cost

        return (
            self.recipe_version.additional_costs_total
            * self.scale_factor
        ).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    @property
    def total_cost(self):
        return (
            self.materials_cost
            + self.labor_cost
            + self.additional_cost
        )

    @property
    def cost_per_base_unit(self):
        if not self.actual_quantity or self.actual_quantity <= 0:
            return None

        return self.total_cost / self.actual_quantity

    @property
    def yield_variance(self):
        if self.actual_quantity is None:
            return None

        return self.actual_quantity - self.planned_quantity

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f'{self.code} — '
            f'{self.recipe_version.recipe.output_item}'
        )


class ProductionMaterial(TimeStampedModel):
    production_batch = models.ForeignKey(
        ProductionBatch,
        verbose_name='lote de produção',
        related_name='materials',
        on_delete=models.CASCADE,
    )
    recipe_ingredient = models.ForeignKey(
        RecipeIngredient,
        verbose_name='ingrediente da ficha técnica',
        related_name='production_materials',
        on_delete=models.PROTECT,
    )
    stock_lot = models.ForeignKey(
        StockLot,
        verbose_name='lote de estoque utilizado',
        related_name='production_materials',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    source_location = models.ForeignKey(
        StockLocation,
        verbose_name='local de origem',
        related_name='production_materials',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    planned_quantity = models.DecimalField(
        'quantidade planejada',
        max_digits=18,
        decimal_places=6,
        validators=[MinValueValidator(Decimal('0.000001'))],
    )
    actual_quantity = models.DecimalField(
        'quantidade efetivamente utilizada',
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.000000'))],
    )
    movement = models.OneToOneField(
        StockMovement,
        verbose_name='movimentação de consumo',
        related_name='production_material',
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
            'recipe_ingredient__sequence',
            'stock_lot__expiration_date',
            'id',
        ]
        verbose_name = 'material da produção'
        verbose_name_plural = 'materiais da produção'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(planned_quantity__gt=0),
                name='production_material_planned_positive',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(actual_quantity__isnull=True)
                    | models.Q(actual_quantity__gte=0)
                ),
                name='production_material_actual_nonnegative',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        stock_lot__isnull=True,
                        source_location__isnull=True,
                    )
                    | models.Q(
                        stock_lot__isnull=False,
                        source_location__isnull=False,
                    )
                ),
                name='production_material_stock_fields_together',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.recipe_ingredient_id
            and self.production_batch_id
            and self.recipe_ingredient.recipe_version_id
            != self.production_batch.recipe_version_id
        ):
            errors['recipe_ingredient'] = (
                'O ingrediente precisa pertencer à versão '
                'usada nesta produção.'
            )

        if (
            self.stock_lot_id
            and self.recipe_ingredient_id
            and self.stock_lot.item_id
            != self.recipe_ingredient.item_id
        ):
            errors['stock_lot'] = (
                'O lote selecionado não corresponde '
                'ao ingrediente.'
            )

        if bool(self.stock_lot_id) != bool(self.source_location_id):
            errors['stock_lot'] = (
                'Informe o lote e o local de origem juntos.'
            )

        if (
            self.actual_quantity is not None
            and self.actual_quantity > 0
            and self.stock_lot_id
        ):
            if self.stock_lot.is_blocked:
                errors['stock_lot'] = (
                    'O lote selecionado está bloqueado.'
                )
            elif self.stock_lot.is_expired:
                errors['stock_lot'] = (
                    'O lote selecionado está vencido.'
                )

        if self.movement_id:
            if (
                self.movement.movement_type
                != StockMovementType.PRODUCTION_CONSUMPTION
            ):
                errors['movement'] = (
                    'A movimentação deve ser um consumo de produção.'
                )

            if (
                self.stock_lot_id
                and self.movement.lot_id != self.stock_lot_id
            ):
                errors['movement'] = (
                    'A movimentação utiliza outro lote de estoque.'
                )

        if (
            self.production_batch_id
            and self.production_batch.status
            == ProductionStatus.COMPLETED
        ):
            if self.actual_quantity is None:
                errors['actual_quantity'] = (
                    'Informe a quantidade efetivamente utilizada.'
                )

            if (
                self.actual_quantity
                and self.actual_quantity > 0
                and not self.movement_id
            ):
                errors['movement'] = (
                    'O consumo precisa gerar uma saída de estoque.'
                )

        if errors:
            raise ValidationError(errors)

    @property
    def actual_cost(self):
        if (
            self.actual_quantity is None
            or not self.stock_lot_id
            or self.stock_lot.unit_cost is None
        ):
            return Decimal('0.00')

        return (
            self.actual_quantity * self.stock_lot.unit_cost
        ).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )

    def __str__(self):
        item = self.recipe_ingredient.item
        unit_symbol = item.base_unit.symbol

        return (
            f'{item} — '
            f'{self.planned_quantity} {unit_symbol}'
        )


class ProductionStepExecution(TimeStampedModel):
    production_batch = models.ForeignKey(
        ProductionBatch,
        verbose_name='lote de produção',
        related_name='step_executions',
        on_delete=models.CASCADE,
    )
    recipe_step = models.ForeignKey(
        RecipeStep,
        verbose_name='etapa da ficha técnica',
        related_name='production_executions',
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        'situação',
        max_length=20,
        choices=ProductionStepStatus.choices,
        default=ProductionStepStatus.PENDING,
        db_index=True,
    )
    started_at = models.DateTimeField(
        'iniciada em',
        null=True,
        blank=True,
    )
    completed_at = models.DateTimeField(
        'concluída em',
        null=True,
        blank=True,
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='realizada por',
        related_name='production_steps_performed',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notes = models.TextField(
        'observações',
        blank=True,
    )

    class Meta:
        ordering = ['recipe_step__sequence', 'id']
        verbose_name = 'execução de etapa da produção'
        verbose_name_plural = 'execuções das etapas da produção'
        constraints = [
            models.UniqueConstraint(
                fields=['production_batch', 'recipe_step'],
                name='production_step_batch_unique',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(started_at__isnull=True)
                    | models.Q(completed_at__isnull=True)
                    | models.Q(completed_at__gte=models.F('started_at'))
                ),
                name='production_step_completion_after_start',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.production_batch_id
            and self.recipe_step_id
            and self.recipe_step.recipe_version_id
            != self.production_batch.recipe_version_id
        ):
            errors['recipe_step'] = (
                'A etapa precisa pertencer à versão '
                'usada nesta produção.'
            )

        if (
            self.started_at
            and self.completed_at
            and self.completed_at < self.started_at
        ):
            errors['completed_at'] = (
                'A conclusão não pode ser anterior ao início.'
            )

        if (
            self.status == ProductionStepStatus.COMPLETED
            and not self.completed_at
        ):
            errors['completed_at'] = (
                'Informe quando a etapa foi concluída.'
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f'{self.production_batch.code} — '
            f'{self.recipe_step}'
        )
