from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import (
    StockCount,
    StockCountLine,
    StockCountStatus,
    StockLocation,
    StockLot,
    StockMovement,
)
from .services import (
    complete_stock_count,
    prepare_stock_count,
)


@admin.register(StockLocation)
class StockLocationAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'name',
        'location_type',
        'is_active',
    )
    list_filter = (
        'location_type',
        'is_active',
    )
    search_fields = (
        'code',
        'name',
        'description',
    )
    ordering = ('name',)
    list_editable = ('is_active',)


@admin.register(StockLot)
class StockLotAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'item',
        'supplier_lot_code',
        'received_date',
        'expiration_date',
        'quantity_display',
        'expired_display',
        'is_blocked',
        'is_active',
    )
    list_filter = (
        'is_blocked',
        'is_active',
        'received_date',
        'expiration_date',
        'item__category',
    )
    search_fields = (
        'code',
        'supplier_lot_code',
        'item__name',
        'item__sku',
        'item__gtin',
        'item__brand__name',
    )
    autocomplete_fields = ('item',)
    readonly_fields = (
        'quantity_display',
        'expired_display',
        'created_at',
        'updated_at',
    )
    date_hierarchy = 'received_date'
    list_select_related = (
        'item',
        'item__base_unit',
        'item__brand',
    )

    @admin.display(description='Quantidade atual')
    def quantity_display(self, obj):
        return (
            f'{obj.current_quantity} '
            f'{obj.item.base_unit.symbol}'
        )

    @admin.display(
        boolean=True,
        description='Vencido?',
    )
    def expired_display(self, obj):
        return obj.is_expired


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        'occurred_at',
        'movement_type',
        'item_display',
        'lot',
        'quantity_display',
        'source_location',
        'destination_location',
        'created_by',
    )
    list_filter = (
        'movement_type',
        'occurred_at',
        'source_location',
        'destination_location',
    )
    search_fields = (
        'lot__code',
        'lot__supplier_lot_code',
        'lot__item__name',
        'lot__item__sku',
        'reference',
        'notes',
    )
    autocomplete_fields = (
        'lot',
        'source_location',
        'destination_location',
    )
    readonly_fields = (
        'created_by',
        'created_at',
        'updated_at',
    )
    date_hierarchy = 'occurred_at'
    list_select_related = (
        'lot',
        'lot__item',
        'lot__item__base_unit',
        'source_location',
        'destination_location',
        'created_by',
    )

    @admin.display(description='Item')
    def item_display(self, obj):
        return obj.lot.item

    @admin.display(description='Quantidade')
    def quantity_display(self, obj):
        return (
            f'{obj.quantity} '
            f'{obj.lot.item.base_unit.symbol}'
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return (
                'lot',
                'movement_type',
                'quantity',
                'source_location',
                'destination_location',
                'occurred_at',
                'reference',
                'created_by',
                'notes',
                'created_at',
                'updated_at',
            )

        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)


class StockCountLineInline(admin.TabularInline):
    model = StockCountLine
    extra = 1
    autocomplete_fields = ('lot',)
    fields = (
        'lot',
        'expected_quantity',
        'counted_quantity',
        'difference_display',
        'notes',
    )
    readonly_fields = (
        'expected_quantity',
        'difference_display',
    )

    @admin.display(description='Diferença')
    def difference_display(self, obj):
        if obj.pk is None or obj.difference is None:
            return '-'

        return obj.difference

    def get_readonly_fields(self, request, obj=None):
        if (
            obj is not None
            and obj.status != StockCountStatus.DRAFT
        ):
            return (
                'lot',
                'expected_quantity',
                'counted_quantity',
                'difference_display',
                'notes',
            )

        return self.readonly_fields

    def has_add_permission(self, request, obj=None):
        return (
            obj is None
            or obj.status == StockCountStatus.DRAFT
        )

    def has_delete_permission(self, request, obj=None):
        return (
            obj is None
            or obj.status == StockCountStatus.DRAFT
        )


@admin.register(StockCount)
class StockCountAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'location',
        'counted_at',
        'status',
        'created_by',
        'completed_at',
    )
    list_filter = (
        'status',
        'location',
        'counted_at',
    )
    search_fields = (
        'location__code',
        'location__name',
        'notes',
    )
    autocomplete_fields = ('location',)
    readonly_fields = (
        'status',
        'created_by',
        'completed_at',
        'completed_by',
        'created_at',
        'updated_at',
    )
    date_hierarchy = 'counted_at'
    inlines = (StockCountLineInline,)
    actions = (
        'prepare_selected_counts',
        'complete_selected_counts',
        'cancel_selected_counts',
    )

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    @admin.action(
        description='Preparar lotes das contagens selecionadas',
    )
    def prepare_selected_counts(self, request, queryset):
        for stock_count in queryset:
            try:
                lines = prepare_stock_count(
                    stock_count=stock_count,
                )
            except ValidationError as error:
                self.message_user(
                    request,
                    f'{stock_count}: {"; ".join(error.messages)}',
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    (
                        f'{stock_count}: '
                        f'{len(lines)} lote(s) preparado(s).'
                    ),
                    level=messages.SUCCESS,
                )

    @admin.action(
        description='Concluir contagens selecionadas',
    )
    def complete_selected_counts(self, request, queryset):
        for stock_count in queryset:
            try:
                movements = complete_stock_count(
                    stock_count=stock_count,
                    user=request.user,
                )
            except ValidationError as error:
                self.message_user(
                    request,
                    f'{stock_count}: {"; ".join(error.messages)}',
                    level=messages.ERROR,
                )
            else:
                self.message_user(
                    request,
                    (
                        f'{stock_count}: concluída com '
                        f'{len(movements)} ajuste(s).'
                    ),
                    level=messages.SUCCESS,
                )

    @admin.action(
        description='Cancelar contagens selecionadas',
    )
    def cancel_selected_counts(self, request, queryset):
        draft_counts = queryset.filter(
            status=StockCountStatus.DRAFT,
        )
        cancelled_count = draft_counts.update(
            status=StockCountStatus.CANCELLED,
        )

        self.message_user(
            request,
            f'{cancelled_count} contagem(ns) cancelada(s).',
            level=messages.SUCCESS,
        )