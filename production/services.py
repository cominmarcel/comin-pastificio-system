from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from inventory.models import StockLot, StockMovementType
from inventory.services import record_stock_movement
from recipes.models import RecipeVersionStatus

from .models import (
    ProductionBatch,
    ProductionMaterial,
    ProductionStatus,
    ProductionStepExecution,
    ProductionStepStatus,
)


QUANTITY_PRECISION = Decimal('0.000001')
COST_PRECISION = Decimal('0.00000001')


def _locked_batch(production_batch):
    if production_batch.pk is None:
        raise ValidationError(
            'Salve o lote de produção antes de executar esta operação.',
        )

    return (
        ProductionBatch.objects
        .select_for_update()
        .select_related(
            'recipe_version',
            'recipe_version__recipe',
            'recipe_version__recipe__output_item',
            'destination_location',
        )
        .get(pk=production_batch.pk)
    )


def _create_planned_lines(production_batch):
    ingredients = list(
        production_batch.recipe_version.ingredients.select_related(
            'item',
            'item__base_unit',
        )
    )
    steps = list(
        production_batch.recipe_version.steps.all()
    )

    if not ingredients:
        raise ValidationError(
            'A ficha técnica não possui ingredientes ou insumos.',
        )

    created_materials = []
    created_steps = []

    for ingredient in ingredients:
        planned_quantity = (
            ingredient.quantity * production_batch.scale_factor
        ).quantize(
            QUANTITY_PRECISION,
            rounding=ROUND_HALF_UP,
        )

        material = ProductionMaterial(
            production_batch=production_batch,
            recipe_ingredient=ingredient,
            planned_quantity=planned_quantity,
        )
        material.full_clean()
        material.save()
        created_materials.append(material)

    for recipe_step in steps:
        step_execution = ProductionStepExecution(
            production_batch=production_batch,
            recipe_step=recipe_step,
        )
        step_execution.full_clean()
        step_execution.save()
        created_steps.append(step_execution)

    return created_materials, created_steps


@transaction.atomic
def prepare_production_batch(*, production_batch):
    production_batch = _locked_batch(production_batch)

    if production_batch.status != ProductionStatus.PLANNED:
        raise ValidationError(
            'Somente uma produção planejada pode ser preparada.',
        )

    if (
        production_batch.recipe_version.status
        != RecipeVersionStatus.ACTIVE
    ):
        raise ValidationError(
            'A versão da ficha técnica precisa estar ativa.',
        )

    if (
        production_batch.materials.exists()
        or production_batch.step_executions.exists()
    ):
        raise ValidationError(
            'Esta produção já possui materiais ou etapas preparados.',
        )

    materials, steps = _create_planned_lines(production_batch)

    return production_batch, materials, steps


@transaction.atomic
def start_production_batch(
    *,
    production_batch,
    user=None,
    started_at=None,
):
    production_batch = _locked_batch(production_batch)

    if production_batch.status != ProductionStatus.PLANNED:
        raise ValidationError(
            'Somente uma produção planejada pode ser iniciada.',
        )

    if not production_batch.materials.exists():
        raise ValidationError(
            'Prepare os materiais da produção antes de iniciá-la.',
        )

    recipe_has_steps = (
        production_batch.recipe_version.steps.exists()
    )

    if (
        recipe_has_steps
        and not production_batch.step_executions.exists()
    ):
        raise ValidationError(
            'Prepare as etapas da produção antes de iniciá-la.',
        )

    production_batch.status = ProductionStatus.IN_PROGRESS
    production_batch.started_at = started_at or timezone.now()

    if production_batch.responsible_id is None and user is not None:
        production_batch.responsible = user

    production_batch.full_clean()
    production_batch.save()

    return production_batch


@transaction.atomic
def complete_production_batch(
    *,
    production_batch,
    output_lot_code,
    user=None,
    completed_at=None,
    notes='',
):
    production_batch = _locked_batch(production_batch)

    if production_batch.status != ProductionStatus.IN_PROGRESS:
        raise ValidationError(
            'Somente uma produção em andamento pode ser concluída.',
        )

    if (
        production_batch.actual_quantity is None
        or production_batch.actual_quantity <= 0
    ):
        raise ValidationError(
            'Informe a quantidade efetivamente produzida.',
        )

    output_lot_code = output_lot_code.strip().upper()

    if not output_lot_code:
        raise ValidationError(
            'Informe o código do lote produzido.',
        )

    materials = list(
        production_batch.materials
        .select_for_update(of=('self',))
        .select_related(
            'recipe_ingredient',
            'recipe_ingredient__item',
            'stock_lot',
            'stock_lot__item',
            'source_location',
            'movement',
        )
    )
    if not materials:
        raise ValidationError(
            'A produção não possui materiais preparados.',
        )

    incomplete_steps = (
        production_batch.step_executions
        .exclude(
            status__in={
                ProductionStepStatus.COMPLETED,
                ProductionStepStatus.SKIPPED,
            },
        )
        .exists()
    )

    if incomplete_steps:
        raise ValidationError(
            'Conclua ou ignore todas as etapas antes '
            'de concluir a produção.',
        )

    for material in materials:
        if material.actual_quantity is None:
            raise ValidationError(
                'Informe a quantidade efetivamente utilizada '
                f'para {material.recipe_ingredient.item}.',
            )

        if material.actual_quantity > 0:
            if not material.stock_lot_id:
                raise ValidationError(
                    'Informe o lote de estoque utilizado '
                    f'para {material.recipe_ingredient.item}.',
                )

            if not material.source_location_id:
                raise ValidationError(
                    'Informe o local de origem '
                    f'para {material.recipe_ingredient.item}.',
                )

        if material.movement_id:
            raise ValidationError(
                'Um dos materiais já possui movimentação de consumo.',
            )

        material.full_clean()

    completion_time = completed_at or timezone.now()
    reference = f'Produção {production_batch.code}'

    for material in materials:
        if material.actual_quantity == 0:
            continue

        movement = record_stock_movement(
            lot=material.stock_lot,
            movement_type=(
                StockMovementType.PRODUCTION_CONSUMPTION
            ),
            quantity=material.actual_quantity,
            source_location=material.source_location,
            occurred_at=completion_time,
            reference=reference,
            user=user,
            notes=(
                'Consumo de ingrediente ou insumo '
                f'na produção {production_batch.code}.'
            ),
        )

        material.movement = movement
        material.full_clean()
        material.save()

    unit_cost = (
        production_batch.total_cost
        / production_batch.actual_quantity
    ).quantize(
        COST_PRECISION,
        rounding=ROUND_HALF_UP,
    )

    if timezone.is_aware(completion_time):
        completion_date = timezone.localdate(completion_time)
    else:
        completion_date = completion_time.date()

    output_lot = StockLot(
        item=production_batch.output_item,
        code=output_lot_code,
        received_date=completion_date,
        manufacturing_date=completion_date,
        expiration_date=production_batch.expiration_date,
        unit_cost=unit_cost,
        notes=notes,
    )
    output_lot.full_clean()
    output_lot.save()

    output_movement = record_stock_movement(
        lot=output_lot,
        movement_type=StockMovementType.PRODUCTION_OUTPUT,
        quantity=production_batch.actual_quantity,
        destination_location=production_batch.destination_location,
        occurred_at=completion_time,
        reference=reference,
        user=user,
        notes=(
            'Entrada do produto acabado gerada '
            f'pela produção {production_batch.code}.'
        ),
    )

    production_batch.status = ProductionStatus.COMPLETED
    production_batch.completed_at = completion_time
    production_batch.completed_by = user
    production_batch.output_lot = output_lot
    production_batch.output_movement = output_movement
    production_batch.full_clean()
    production_batch.save()

    return production_batch


@transaction.atomic
def cancel_production_batch(*, production_batch):
    production_batch = _locked_batch(production_batch)

    if production_batch.status == ProductionStatus.COMPLETED:
        raise ValidationError(
            'Uma produção concluída não pode ser cancelada.',
        )

    if production_batch.status == ProductionStatus.CANCELLED:
        raise ValidationError(
            'Esta produção já está cancelada.',
        )

    has_consumption = production_batch.materials.filter(
        movement__isnull=False,
    ).exists()

    if has_consumption or production_batch.output_movement_id:
        raise ValidationError(
            'A produção possui movimentações de estoque '
            'e não pode ser cancelada diretamente.',
        )

    production_batch.status = ProductionStatus.CANCELLED
    production_batch.full_clean()
    production_batch.save()

    return production_batch
