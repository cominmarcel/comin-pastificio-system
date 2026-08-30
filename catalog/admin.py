from django.contrib import admin

from .models import Brand, Item, ItemCategory, UnitOfMeasure


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'name',
        'symbol',
        'dimension',
        'factor_to_base_unit',
        'is_active',
    )
    list_filter = ('dimension', 'is_active')
    search_fields = ('code', 'name', 'symbol')


@admin.register(ItemCategory)
class ItemCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'created_at', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'is_active',
    )
    search_fields = (
        'name',
    )
    list_filter = (
        'is_active',
    )
    ordering = (
        'name',
    )
    list_editable = (
        'is_active',
    )

@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'brand',
        'sku',
        'item_type',
        'category',
        'base_unit',
        'is_purchasable',
        'is_producible',
        'is_sellable',
        'tracks_inventory',
        'is_active',
    )
    list_filter = (
        'item_type',
        'brand',
        'is_purchasable',
        'is_producible',
        'is_sellable',
        'tracks_inventory',
        'is_active',
    )
    search_fields = ('name', 'sku', 'description')
    autocomplete_fields = (
        'category',
        'base_unit',
        'net_content_unit',
        'brand',
    )