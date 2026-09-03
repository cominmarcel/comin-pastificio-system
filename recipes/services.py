from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    RecipeVersion,
    RecipeVersionStatus,
)


@transaction.atomic
def activate_recipe_version(*, recipe_version, user=None):
    recipe_version = (
        RecipeVersion.objects
        .select_for_update()
        .select_related('recipe')
        .get(pk=recipe_version.pk)
    )

    ingredients = list(
        recipe_version.ingredients.select_related(
            'item',
            'item__base_unit',
        )
    )

    if not ingredients:
        raise ValidationError(
            'Adicione pelo menos um ingrediente ou insumo.',
        )

    missing_cost_items = []

    for ingredient in ingredients:
        if ingredient.unit_cost_override is not None:
            continue

        has_stock_cost = ingredient.item.stock_lots.filter(
            unit_cost__isnull=False,
        ).exists()

        if not has_stock_cost:
            missing_cost_items.append(str(ingredient.item))

    if missing_cost_items:
        item_names = ', '.join(missing_cost_items)

        raise ValidationError(
            'Informe o custo dos itens sem histórico de estoque: '
            f'{item_names}.'
        )

    (
        RecipeVersion.objects
        .select_for_update()
        .filter(
            recipe=recipe_version.recipe,
            status=RecipeVersionStatus.ACTIVE,
        )
        .exclude(pk=recipe_version.pk)
        .update(status=RecipeVersionStatus.ARCHIVED)
    )

    recipe_version.status = RecipeVersionStatus.ACTIVE
    recipe_version.approved_by = user
    recipe_version.approved_at = timezone.now()
    recipe_version.valid_until = None
    recipe_version.full_clean()
    recipe_version.save()

    return recipe_version