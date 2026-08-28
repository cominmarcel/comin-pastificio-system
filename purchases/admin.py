from django.contrib import admin

from .models import (
    Purchase,
    PurchaseDocument,
    PurchaseItem,
    PurchasePayment,
    Supplier,
)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'supplier_type',
        'phone',
        'email',
        'is_active',
    )
    list_filter = (
        'supplier_type',
        'is_active',
    )
    search_fields = (
        'name',
        'tax_id',
        'contact_name',
        'phone',
        'email',
    )
    ordering = ('name',)
    list_editable = ('is_active',)


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 1
    autocomplete_fields = (
        'item',
        'commercial_unit',
    )
    fields = (
        'item',
        'commercial_quantity',
        'commercial_unit',
        'base_quantity',
        'unit_price',
        'discount_amount',
        'notes',
    )


class PurchasePaymentInline(admin.TabularInline):
    model = PurchasePayment
    extra = 1
    fields = (
        'amount',
        'method',
        'funding_source',
        'due_date',
        'payment_date',
        'installment_number',
        'installment_count',
        'status',
        'notes',
    )


class PurchaseDocumentInline(admin.TabularInline):
    model = PurchaseDocument
    extra = 0
    fields = (
        'document_type',
        'file',
        'description',
    )


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'purchase_date',
        'supplier',
        'status',
        'channel',
        'declared_total',
    )
    list_filter = (
        'status',
        'channel',
        'document_type',
        'purchase_date',
    )
    search_fields = (
        'supplier__name',
        'document_number',
        'notes',
    )
    autocomplete_fields = (
        'supplier',
        'purchased_by',
    )
    readonly_fields = (
        'created_by',
        'created_at',
        'updated_at',
    )
    date_hierarchy = 'purchase_date'
    list_select_related = (
        'supplier',
        'purchased_by',
    )
    inlines = (
        PurchaseItemInline,
        PurchasePaymentInline,
        PurchaseDocumentInline,
    )

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)

        for deleted_object in formset.deleted_objects:
            deleted_object.delete()

        for instance in instances:
            if (
                isinstance(instance, PurchaseDocument)
                and instance.uploaded_by_id is None
            ):
                instance.uploaded_by = request.user

            instance.save()

        formset.save_m2m()