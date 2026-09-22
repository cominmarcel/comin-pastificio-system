from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import (
    Customer,
    SalesOrder,
    SalesOrderItem,
    SalesOrderItemAllocation,
    SalesOrderPayment,
    SalesOrderStatus,
)
from .services import (
    allocate_sales_order_stock,
    cancel_sales_order,
    cancel_sales_payment,
    complete_sales_order,
    confirm_sales_order,
    mark_sales_order_in_production,
    mark_sales_order_ready,
    refund_sales_payment,
    register_sales_payment,
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'customer_type',
        'phone',
        'email',
        'city',
        'is_active',
    )
    list_filter = (
        'customer_type',
        'is_active',
        'city',
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
    readonly_fields = (
        'created_by',
        'created_at',
        'updated_at',
    )
    fieldsets = (
        (
            'Identificação',
            {
                'fields': (
                    'name',
                    'customer_type',
                    'tax_id',
                    'contact_name',
                    'birth_date',
                    'is_active',
                ),
            },
        ),
        (
            'Contato',
            {
                'fields': (
                    'phone',
                    'email',
                ),
            },
        ),
        (
            'Endereço',
            {
                'fields': (
                    'address',
                    'city',
                    'state',
                    'postal_code',
                ),
            },
        ),
        (
            'Informações adicionais',
            {
                'fields': (
                    'notes',
                    'created_by',
                    'created_at',
                    'updated_at',
                ),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

def validation_error_text(error):
    if hasattr(error, 'message_dict'):
        parts = []

        for field, field_messages in error.message_dict.items():
            parts.append(
                f'{field}: {"; ".join(field_messages)}'
            )

        return ' | '.join(parts)

    return '; '.join(error.messages)


class SalesOrderItemInline(admin.TabularInline):
    model = SalesOrderItem
    extra = 1
    show_change_link = True
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
        'subtotal_display',
        'net_total_display',
        'cost_total_display',
        'profit_display',
        'notes',
    )
    readonly_fields = (
        'subtotal_display',
        'net_total_display',
        'cost_total_display',
        'profit_display',
    )

    @admin.display(description='Subtotal')
    def subtotal_display(self, obj):
        if obj.pk is None:
            return '-'

        return f'R$ {obj.subtotal:.2f}'

    @admin.display(description='Total líquido')
    def net_total_display(self, obj):
        if obj.pk is None:
            return '-'

        return f'R$ {obj.net_total:.2f}'

    @admin.display(description='Custo')
    def cost_total_display(self, obj):
        if obj.pk is None:
            return '-'

        return f'R$ {obj.cost_total:.2f}'

    @admin.display(description='Lucro')
    def profit_display(self, obj):
        if obj.pk is None:
            return '-'

        return f'R$ {obj.profit:.2f}'

    def has_delete_permission(self, request, obj=None):
        if obj is None:
            return True

        return obj.status == SalesOrderStatus.DRAFT


class SalesOrderPaymentInline(admin.TabularInline):
    model = SalesOrderPayment
    extra = 1
    show_change_link = True
    can_delete = False
    fields = (
        'amount',
        'fee_amount',
        'method',
        'due_date',
        'paid_at',
        'installment_number',
        'installment_count',
        'status',
        'processor_reference',
        'received_by',
        'notes',
    )
    readonly_fields = (
        'status',
        'paid_at',
        'received_by',
    )

class SalesOrderItemAllocationInline(admin.TabularInline):
    model = SalesOrderItemAllocation
    extra = 1
    can_delete = False
    autocomplete_fields = (
        'stock_lot',
        'source_location',
    )
    fields = (
        'stock_lot',
        'source_location',
        'quantity',
        'unit_cost',
        'total_cost_display',
        'dispatch_movement',
        'return_movement',
        'notes',
    )
    readonly_fields = (
        'unit_cost',
        'total_cost_display',
        'dispatch_movement',
        'return_movement',
    )

    @admin.display(description='Custo total')
    def total_cost_display(self, obj):
        if obj.pk is None:
            return '-'

        return f'R$ {obj.total_cost:.2f}'

@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'customer',
        'ordered_at',
        'scheduled_for',
        'status',
        'total_amount_display',
        'paid_total_display',
        'balance_due_display',
        'profit_display',
    )
    list_filter = (
        'status',
        'channel',
        'fulfillment_type',
        'ordered_at',
    )
    search_fields = (
        'code',
        'customer__name',
        'customer__phone',
        'notes',
    )
    autocomplete_fields = (
        'customer',
        'source_location',
        'seller',
    )
    list_select_related = (
        'customer',
        'source_location',
        'seller',
    )
    readonly_fields = (
        'status',
        'completed_at',
        'created_by',
        'items_subtotal_display',
        'items_discount_total_display',
        'items_net_total_display',
        'total_amount_display',
        'paid_total_display',
        'balance_due_display',
        'items_cost_total_display',
        'payment_fees_total_display',
        'total_cost_display',
        'profit_display',
        'margin_percentage_display',
        'created_at',
        'updated_at',
    )
    inlines = (
        SalesOrderItemInline,
        SalesOrderPaymentInline,
    )
    date_hierarchy = 'ordered_at'

    actions = (
        'confirm_selected_orders',
        'mark_selected_orders_in_production',
        'mark_selected_orders_ready',
        'allocate_selected_orders_stock',
        'complete_selected_orders',
        'cancel_selected_orders',
    )

    def run_order_action(
        self,
        request,
        queryset,
        service,
        success_message,
        extra_arguments=None,
    ):
        successful_operations = 0

        for sales_order in queryset:
            arguments = {
                'sales_order': sales_order,
            }

            if extra_arguments is not None:
                arguments.update(
                    extra_arguments(sales_order),
                )

            try:
                service(**arguments)
            except ValidationError as error:
                self.message_user(
                    request,
                    (
                        f'{sales_order}: '
                        f'{validation_error_text(error)}'
                    ),
                    level=messages.ERROR,
                )
            else:
                successful_operations += 1

        if successful_operations:
            self.message_user(
                request,
                (
                    f'{successful_operations} pedido(s): '
                    f'{success_message}'
                ),
                level=messages.SUCCESS,
            )

    @admin.action(description='Confirmar pedidos selecionados')
    def confirm_selected_orders(self, request, queryset):
        self.run_order_action(
            request,
            queryset,
            confirm_sales_order,
            'confirmado(s) com sucesso.',
        )

    @admin.action(
        description='Marcar pedidos selecionados como em produção',
    )
    def mark_selected_orders_in_production(
        self,
        request,
        queryset,
    ):
        self.run_order_action(
            request,
            queryset,
            mark_sales_order_in_production,
            'marcado(s) como em produção.',
        )

    @admin.action(
        description='Marcar pedidos selecionados como prontos',
    )
    def mark_selected_orders_ready(self, request, queryset):
        self.run_order_action(
            request,
            queryset,
            mark_sales_order_ready,
            'marcado(s) como pronto(s).',
        )

    @admin.action(
        description='Separar estoque dos pedidos selecionados',
    )
    def allocate_selected_orders_stock(
        self,
        request,
        queryset,
    ):
        self.run_order_action(
            request,
            queryset,
            allocate_sales_order_stock,
            'com estoque separado.',
            extra_arguments=lambda sales_order: {
                'source_location': sales_order.source_location,
            },
        )

    @admin.action(description='Concluir pedidos selecionados')
    def complete_selected_orders(self, request, queryset):
        self.run_order_action(
            request,
            queryset,
            complete_sales_order,
            'concluído(s) com sucesso.',
            extra_arguments=lambda sales_order: {
                'user': request.user,
            },
        )

    @admin.action(description='Cancelar pedidos selecionados')
    def cancel_selected_orders(self, request, queryset):
        self.run_order_action(
            request,
            queryset,
            cancel_sales_order,
            'cancelado(s) com sucesso.',
            extra_arguments=lambda sales_order: {
                'user': request.user,
            },
        )

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = request.user

        if obj.seller_id is None:
            obj.seller = request.user

        super().save_model(request, obj, form, change)

    @admin.display(description='Subtotal dos itens')
    def items_subtotal_display(self, obj):
        return f'R$ {obj.items_subtotal:.2f}'

    @admin.display(description='Descontos dos itens')
    def items_discount_total_display(self, obj):
        return f'R$ {obj.items_discount_total:.2f}'

    @admin.display(description='Total líquido dos itens')
    def items_net_total_display(self, obj):
        return f'R$ {obj.items_net_total:.2f}'

    @admin.display(description='Total do pedido')
    def total_amount_display(self, obj):
        return f'R$ {obj.total_amount:.2f}'

    @admin.display(description='Total pago')
    def paid_total_display(self, obj):
        return f'R$ {obj.paid_total:.2f}'

    @admin.display(description='Saldo a receber')
    def balance_due_display(self, obj):
        return f'R$ {obj.balance_due:.2f}'

    @admin.display(description='Custo dos itens')
    def items_cost_total_display(self, obj):
        return f'R$ {obj.items_cost_total:.2f}'

    @admin.display(description='Taxas de pagamento')
    def payment_fees_total_display(self, obj):
        return f'R$ {obj.payment_fees_total:.2f}'

    @admin.display(description='Custo total')
    def total_cost_display(self, obj):
        return f'R$ {obj.total_cost:.2f}'

    @admin.display(description='Lucro')
    def profit_display(self, obj):
        return f'R$ {obj.profit:.2f}'

    @admin.display(description='Margem')
    def margin_percentage_display(self, obj):
        if obj.margin_percentage is None:
            return '-'

        return f'{obj.margin_percentage:.2f}%'

@admin.register(SalesOrderItem)
class SalesOrderItemAdmin(admin.ModelAdmin):
    list_display = (
        'sales_order',
        'item',
        'commercial_quantity',
        'net_total_display',
        'allocated_quantity_display',
        'cost_total_display',
        'profit_display',
    )
    search_fields = (
        'sales_order__code',
        'item__name',
        'item__sku',
        'item__gtin',
    )
    autocomplete_fields = (
        'sales_order',
        'item',
        'commercial_unit',
    )
    list_select_related = (
        'sales_order',
        'item',
        'commercial_unit',
    )
    readonly_fields = (
        'subtotal_display',
        'net_total_display',
        'allocated_quantity_display',
        'quantity_to_allocate_display',
        'cost_total_display',
        'profit_display',
        'margin_display',
        'created_at',
        'updated_at',
    )
    inlines = (
        SalesOrderItemAllocationInline,
    )

    @admin.display(description='Subtotal')
    def subtotal_display(self, obj):
        return f'R$ {obj.subtotal:.2f}'

    @admin.display(description='Total líquido')
    def net_total_display(self, obj):
        return f'R$ {obj.net_total:.2f}'

    @admin.display(description='Quantidade separada')
    def allocated_quantity_display(self, obj):
        return obj.allocated_quantity

    @admin.display(description='Quantidade a separar')
    def quantity_to_allocate_display(self, obj):
        return obj.quantity_to_allocate

    @admin.display(description='Custo')
    def cost_total_display(self, obj):
        return f'R$ {obj.cost_total:.2f}'

    @admin.display(description='Lucro')
    def profit_display(self, obj):
        return f'R$ {obj.profit:.2f}'

    @admin.display(description='Margem')
    def margin_display(self, obj):
        if obj.margin_percentage is None:
            return '-'

        return f'{obj.margin_percentage:.2f}%'

@admin.register(SalesOrderPayment)
class SalesOrderPaymentAdmin(admin.ModelAdmin):
    list_display = (
        'sales_order',
        'amount_display',
        'fee_amount_display',
        'method',
        'due_date',
        'paid_at',
        'status',
        'current_status_display',
    )
    list_filter = (
        'status',
        'method',
        'due_date',
        'paid_at',
    )
    search_fields = (
        'sales_order__code',
        'sales_order__customer__name',
        'processor_reference',
        'notes',
    )
    autocomplete_fields = (
        'sales_order',
        'received_by',
    )
    list_select_related = (
        'sales_order',
        'received_by',
    )
    readonly_fields = (
        'status',
        'paid_at',
        'received_by',
        'current_status_display',
        'net_amount_display',
        'created_at',
        'updated_at',
    )
    date_hierarchy = 'due_date'
    actions = (
        'register_selected_payments',
        'refund_selected_payments',
        'cancel_selected_payments',
    )

    def run_payment_action(
        self,
        request,
        queryset,
        service,
        success_message,
        include_user=False,
    ):
        successful_operations = 0

        for payment in queryset:
            arguments = {
                'payment': payment,
            }

            if include_user:
                arguments['user'] = request.user

            try:
                service(**arguments)
            except ValidationError as error:
                self.message_user(
                    request,
                    (
                        f'{payment}: '
                        f'{validation_error_text(error)}'
                    ),
                    level=messages.ERROR,
                )
            else:
                successful_operations += 1

        if successful_operations:
            self.message_user(
                request,
                (
                    f'{successful_operations} pagamento(s): '
                    f'{success_message}'
                ),
                level=messages.SUCCESS,
            )

    @admin.action(description='Registrar pagamentos selecionados')
    def register_selected_payments(self, request, queryset):
        self.run_payment_action(
            request,
            queryset,
            register_sales_payment,
            'registrado(s) como pago(s).',
            include_user=True,
        )

    @admin.action(description='Estornar pagamentos selecionados')
    def refund_selected_payments(self, request, queryset):
        self.run_payment_action(
            request,
            queryset,
            refund_sales_payment,
            'estornado(s) com sucesso.',
        )

    @admin.action(description='Cancelar pagamentos selecionados')
    def cancel_selected_payments(self, request, queryset):
        self.run_payment_action(
            request,
            queryset,
            cancel_sales_payment,
            'cancelado(s) com sucesso.',
        )

    @admin.display(description='Valor')
    def amount_display(self, obj):
        return f'R$ {obj.amount:.2f}'

    @admin.display(description='Taxa')
    def fee_amount_display(self, obj):
        return f'R$ {obj.fee_amount:.2f}'

    @admin.display(description='Valor líquido')
    def net_amount_display(self, obj):
        return f'R$ {obj.net_amount:.2f}'

    @admin.display(description='Situação atual')
    def current_status_display(self, obj):
        return obj.current_status