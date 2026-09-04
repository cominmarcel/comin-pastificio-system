from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import (
    ProductionBatch,
    ProductionMaterial,
    ProductionStepExecution,
)
from .services import (
    cancel_production_batch,
    complete_production_batch,
    prepare_production_batch,
    start_production_batch,
)


def validation_error_text(error):
    if hasattr(error, 'message_dict'):
        parts = []

        for field, field_messages in error.message_dict.items():
            parts.append(f'{field}: {"; ".join(field_messages)}')

        return ' | '.join(parts)

    return '; '.join(error.messages)


class ProductionMaterialInline(admin.TabularInline):
    model = ProductionMaterial
    extra = 0
    can_delete = False
    autocomplete_fields = (
        'stock_lot',
        'source_location',
    )
    fields = (
        'recipe_ingredient',
        'planned_quantity',
        'actual_quantity',
        'stock_lot',
        'source_location',
        'actual_cost_display',
        'movement',
        'notes',
    )
    readonly_fields = (
        'recipe_ingredient',
        'planned_quantity',
        'actual_cost_display',
        'movement',
    )

    @admin.display(description='Custo real')
    def actual_cost_display(self, obj):
        if obj.pk is None:
            return '-'

        return f'R$ {obj.actual_cost:.2f}'


class ProductionStepExecutionInline(admin.TabularInline):
    model = ProductionStepExecution
    extra = 0
    can_delete = False
    autocomplete_fields = ('performed_by',)
    fields = (
        'recipe_step',
        'status',
        'started_at',
        'completed_at',
        'performed_by',
        'notes',
    )
    readonly_fields = ('recipe_step',)


@admin.register(ProductionBatch)
class ProductionBatchAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'output_item_display',
        'planned_date',
        'status',
        'planned_quantity',
        'actual_quantity',
        'total_cost_display',
        'destination_location',
    )
    list_filter = (
        'status',
        'planned_date',
        'destination_location',
    )
    search_fields = (
        'code',
        'recipe_version__recipe__name',
        'recipe_version__recipe__output_item__name',
        'notes',
    )
    autocomplete_fields = (
        'recipe_version',
        'destination_location',
        'responsible',
    )
    readonly_fields = (
        'status',
        'started_at',
        'completed_at',
        'output_lot',
        'output_movement',
        'created_by',
        'completed_by',
        'planned_cost_display',
        'materials_cost_display',
        'labor_cost_display',
        'additional_cost_display',
        'total_cost_display',
        'cost_per_base_unit_display',
        'yield_variance_display',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        (
            'Planejamento',
            {
                'fields': (
                    'code',
                    'recipe_version',
                    'status',
                    'planned_quantity',
                    'planned_date',
                    'destination_location',
                    'expiration_date',
                    'responsible',
                ),
            },
        ),
        (
            'Execução',
            {
                'fields': (
                    'actual_quantity',
                    'actual_active_time_minutes',
                    'actual_additional_cost',
                    'started_at',
                    'completed_at',
                ),
            },
        ),
        (
            'Resultado no estoque',
            {
                'fields': (
                    'output_lot',
                    'output_movement',
                ),
            },
        ),
        (
            'Custos e rendimento',
            {
                'fields': (
                    'planned_cost_display',
                    'materials_cost_display',
                    'labor_cost_display',
                    'additional_cost_display',
                    'total_cost_display',
                    'cost_per_base_unit_display',
                    'yield_variance_display',
                ),
            },
        ),
        (
            'Informações adicionais',
            {
                'fields': (
                    'notes',
                    'created_by',
                    'completed_by',
                    'created_at',
                    'updated_at',
                ),
            },
        ),
    )
    inlines = (
        ProductionMaterialInline,
        ProductionStepExecutionInline,
    )
    actions = (
        'prepare_selected_batches',
        'start_selected_batches',
        'complete_selected_batches',
        'cancel_selected_batches',
    )
    date_hierarchy = 'planned_date'
    list_select_related = (
        'recipe_version',
        'recipe_version__recipe',
        'recipe_version__recipe__output_item',
        'destination_location',
    )

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    @admin.display(description='Produto')
    def output_item_display(self, obj):
        return obj.output_item

    @admin.display(description='Custo previsto')
    def planned_cost_display(self, obj):
        if obj.pk is None:
            return '-'

        return f'R$ {obj.planned_cost:.2f}'

    @admin.display(description='Custo dos materiais')
    def materials_cost_display(self, obj):
        if obj.pk is None:
            return '-'

        return f'R$ {obj.materials_cost:.2f}'

    @admin.display(description='Custo da mão de obra')
    def labor_cost_display(self, obj):
        if obj.pk is None:
            return '-'

        return f'R$ {obj.labor_cost:.2f}'

    @admin.display(description='Custos adicionais')
    def additional_cost_display(self, obj):
        if obj.pk is None:
            return '-'

        return f'R$ {obj.additional_cost:.2f}'

    @admin.display(description='Custo total')
    def total_cost_display(self, obj):
        if obj.pk is None:
            return '-'

        return f'R$ {obj.total_cost:.2f}'

    @admin.display(description='Custo por unidade-base')
    def cost_per_base_unit_display(self, obj):
        value = obj.cost_per_base_unit

        if value is None:
            return '-'

        return f'R$ {value:.8f}'

    @admin.display(description='Variação de rendimento')
    def yield_variance_display(self, obj):
        value = obj.yield_variance

        if value is None:
            return '-'

        unit_symbol = obj.output_item.base_unit.symbol
        return f'{value} {unit_symbol}'

    def _run_action(self, request, queryset, operation, success_text):
        succeeded = 0

        for production_batch in queryset:
            try:
                operation(production_batch)
            except ValidationError as error:
                self.message_user(
                    request,
                    (
                        f'{production_batch.code}: '
                        f'{validation_error_text(error)}'
                    ),
                    level=messages.ERROR,
                )
            else:
                succeeded += 1

        if succeeded:
            self.message_user(
                request,
                success_text.format(count=succeeded),
                level=messages.SUCCESS,
            )

    @admin.action(description='Preparar materiais e etapas')
    def prepare_selected_batches(self, request, queryset):
        self._run_action(
            request,
            queryset,
            operation=lambda batch: prepare_production_batch(
                production_batch=batch,
            ),
            success_text=(
                '{count} lote(s) de produção preparado(s).'
            ),
        )

    @admin.action(description='Iniciar produções selecionadas')
    def start_selected_batches(self, request, queryset):
        self._run_action(
            request,
            queryset,
            operation=lambda batch: start_production_batch(
                production_batch=batch,
                user=request.user,
            ),
            success_text=(
                '{count} lote(s) de produção iniciado(s).'
            ),
        )

    @admin.action(description='Concluir produções selecionadas')
    def complete_selected_batches(self, request, queryset):
        self._run_action(
            request,
            queryset,
            operation=lambda batch: complete_production_batch(
                production_batch=batch,
                output_lot_code=batch.code,
                user=request.user,
            ),
            success_text=(
                '{count} lote(s) de produção concluído(s).'
            ),
        )

    @admin.action(description='Cancelar produções selecionadas')
    def cancel_selected_batches(self, request, queryset):
        self._run_action(
            request,
            queryset,
            operation=lambda batch: cancel_production_batch(
                production_batch=batch,
            ),
            success_text=(
                '{count} lote(s) de produção cancelado(s).'
            ),
        )
