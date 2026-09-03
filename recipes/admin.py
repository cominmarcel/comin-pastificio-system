from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import (
    Recipe,
    RecipeAdditionalCost,
    RecipeIngredient,
    RecipeStep,
    RecipeVersion,
    RecipeVersionStatus,
)
from .services import activate_recipe_version


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'name',
        'output_item',
        'is_active',
        'created_by',
    )
    list_filter = (
        'is_active',
        'output_item__item_type',
        'output_item__category',
    )
    search_fields = (
        'code',
        'name',
        'output_item__name',
        'output_item__sku',
    )
    autocomplete_fields = ('output_item',)
    readonly_fields = (
        'created_by',
        'created_at',
        'updated_at',
    )
    list_select_related = (
        'output_item',
        'output_item__category',
        'created_by',
    )

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)


class DraftOnlyInlineMixin:
    def get_readonly_fields(self, request, obj=None):
        if (
            obj is not None
            and obj.status != RecipeVersionStatus.DRAFT
        ):
            return tuple(self.fields)

        return super().get_readonly_fields(request, obj)

    def has_add_permission(self, request, obj=None):
        return (
            obj is None
            or obj.status == RecipeVersionStatus.DRAFT
        )

    def has_delete_permission(self, request, obj=None):
        return (
            obj is None
            or obj.status == RecipeVersionStatus.DRAFT
        )


class RecipeIngredientInline(
    DraftOnlyInlineMixin,
    admin.TabularInline,
):
    model = RecipeIngredient
    extra = 1
    autocomplete_fields = ('item',)
    fields = (
        'sequence',
        'item',
        'quantity',
        'unit_display',
        'unit_cost_override',
        'resolved_unit_cost_display',
        'total_cost_display',
        'stage',
        'notes',
    )
    readonly_fields = (
        'unit_display',
        'resolved_unit_cost_display',
        'total_cost_display',
    )

    @admin.display(description='Unidade-base')
    def unit_display(self, obj):
        if not obj.item_id:
            return '-'

        return obj.item.base_unit.symbol

    @admin.display(description='Custo unitário utilizado')
    def resolved_unit_cost_display(self, obj):
        if not obj.item_id:
            return '-'

        return obj.resolved_unit_cost

    @admin.display(description='Custo total')
    def total_cost_display(self, obj):
        if not obj.item_id or obj.quantity is None:
            return '-'

        return f'R$ {obj.total_cost}'


class RecipeAdditionalCostInline(
    DraftOnlyInlineMixin,
    admin.TabularInline,
):
    model = RecipeAdditionalCost
    extra = 1
    fields = (
        'cost_type',
        'description',
        'amount',
        'notes',
    )


class RecipeStepInline(
    DraftOnlyInlineMixin,
    admin.StackedInline,
):
    model = RecipeStep
    extra = 1
    fields = (
        'sequence',
        'phase',
        'title',
        'instructions',
        'duration_minutes',
        'requires_active_work',
    )


@admin.register(RecipeVersion)
class RecipeVersionAdmin(admin.ModelAdmin):
    list_display = (
        'recipe',
        'version',
        'status',
        'yield_display',
        'ingredients_cost_display',
        'labor_cost_display',
        'additional_costs_display',
        'total_cost_display',
        'unit_cost_display',
    )
    list_filter = (
        'status',
        'valid_from',
        'recipe__output_item__category',
    )
    search_fields = (
        'recipe__code',
        'recipe__name',
        'recipe__output_item__name',
        'notes',
    )
    autocomplete_fields = ('recipe',)
    readonly_fields = (
        'status',
        'ingredients_cost_display',
        'labor_cost_display',
        'additional_costs_display',
        'total_cost_display',
        'unit_cost_display',
        'created_by',
        'approved_by',
        'approved_at',
        'created_at',
        'updated_at',
    )
    date_hierarchy = 'valid_from'
    inlines = (
        RecipeIngredientInline,
        RecipeAdditionalCostInline,
        RecipeStepInline,
    )
    actions = ('activate_selected_version',)
    list_select_related = (
        'recipe',
        'recipe__output_item',
        'recipe__output_item__base_unit',
    )

    @admin.display(description='Rendimento')
    def yield_display(self, obj):
        unit_symbol = obj.recipe.output_item.base_unit.symbol

        return f'{obj.yield_quantity} {unit_symbol}'

    @admin.display(description='Ingredientes')
    def ingredients_cost_display(self, obj):
        return f'R$ {obj.ingredients_cost}'

    @admin.display(description='Mão de obra')
    def labor_cost_display(self, obj):
        return f'R$ {obj.labor_cost}'

    @admin.display(description='Custos adicionais')
    def additional_costs_display(self, obj):
        return f'R$ {obj.additional_costs_total}'

    @admin.display(description='Custo total')
    def total_cost_display(self, obj):
        return f'R$ {obj.total_cost}'

    @admin.display(description='Custo por unidade-base')
    def unit_cost_display(self, obj):
        cost = obj.cost_per_base_unit

        if cost is None:
            return '-'

        unit_symbol = obj.recipe.output_item.base_unit.symbol

        return f'R$ {cost:.8f}/{unit_symbol}'

    def get_readonly_fields(self, request, obj=None):
        if (
            obj is not None
            and obj.status != RecipeVersionStatus.DRAFT
        ):
            return (
                'recipe',
                'version',
                'status',
                'yield_quantity',
                'active_time_minutes',
                'total_time_minutes',
                'hourly_labor_cost',
                'valid_from',
                'valid_until',
                'notes',
                'ingredients_cost_display',
                'labor_cost_display',
                'additional_costs_display',
                'total_cost_display',
                'unit_cost_display',
                'created_by',
                'approved_by',
                'approved_at',
                'created_at',
                'updated_at',
            )

        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        if obj is None:
            return False

        return obj.status == RecipeVersionStatus.DRAFT

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    @admin.action(description='Ativar a versão selecionada')
    def activate_selected_version(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                'Selecione exatamente uma versão para ativar.',
                level=messages.ERROR,
            )
            return

        recipe_version = queryset.first()

        try:
            activate_recipe_version(
                recipe_version=recipe_version,
                user=request.user,
            )
        except ValidationError as error:
            self.message_user(
                request,
                '; '.join(error.messages),
                level=messages.ERROR,
            )
        else:
            self.message_user(
                request,
                f'{recipe_version} foi ativada.',
                level=messages.SUCCESS,
            )