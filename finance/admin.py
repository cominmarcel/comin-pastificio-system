from django.contrib import admin

from .models import ExpenseCategory, FinancialAccount


@admin.register(FinancialAccount)
class FinancialAccountAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'name',
        'account_type',
        'is_active',
    )
    list_filter = (
        'account_type',
        'is_active',
    )
    search_fields = (
        'code',
        'name',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
    )


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'is_active',
    )
    list_filter = (
        'is_active',
    )
    search_fields = (
        'name',
        'description',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
    )