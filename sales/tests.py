from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from catalog.models import (
    Item,
    ItemType,
    MeasurementDimension,
    UnitOfMeasure,
)
from inventory.models import (
    StockLocation,
    StockLot,
    StockMovementType,
)
from inventory.services import record_stock_movement

from .models import (
    SalesOrder,
    SalesOrderItem,
    SalesOrderPayment,
    SalesOrderStatus,
    SalesPaymentMethod,
    SalesPaymentStatus,
)
from .services import (
    allocate_sales_order_stock,
    cancel_sales_order,
    cancel_sales_payment,
    complete_sales_order,
    confirm_sales_order,
    mark_sales_order_ready,
    refund_sales_payment,
    register_sales_payment,
)
from finance.models import FinancialAccount

class SalesServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='sales-test',
        )
        self.financial_account = FinancialAccount.objects.create(
            code='SALES-TEST',
            name='Conta de vendas para testes',
        )
        self.gram = UnitOfMeasure.objects.create(
            code='G',
            name='Grama',
            symbol='g',
            dimension=MeasurementDimension.MASS,
            factor_to_base_unit=Decimal('1'),
        )
        self.package = UnitOfMeasure.objects.create(
            code='PACKAGE',
            name='Pacote',
            symbol='pct',
            dimension=MeasurementDimension.COUNT,
            factor_to_base_unit=Decimal('1'),
        )
        self.item = Item.objects.create(
            name='Massa de teste',
            sku='SALES-TEST-001',
            item_type=ItemType.FINISHED_PRODUCT,
            base_unit=self.gram,
            is_sellable=True,
            tracks_inventory=True,
        )
        self.freezer = StockLocation.objects.create(
            code='FREEZER-TEST',
            name='Freezer de teste',
            location_type='frozen',
        )
        self.order = SalesOrder.objects.create(
            code='PED-TEST-001',
            source_location=self.freezer,
        )
        self.order_item = SalesOrderItem.objects.create(
            sales_order=self.order,
            item=self.item,
            commercial_quantity=Decimal('2'),
            commercial_unit=self.package,
            base_quantity=Decimal('600'),
            unit_price=Decimal('25.00'),
        )

    def create_lot(self, code, quantity, expires_in=30):
        lot = StockLot.objects.create(
            item=self.item,
            code=code,
            received_date=timezone.localdate(),
            expiration_date=(
                timezone.localdate()
                + timedelta(days=expires_in)
            ),
            unit_cost=Decimal('0.02000000'),
        )
        record_stock_movement(
            lot=lot,
            movement_type=StockMovementType.OPENING_BALANCE,
            quantity=Decimal(quantity),
            destination_location=self.freezer,
            user=self.user,
        )
        return lot

    def allocate_order(self):
        return allocate_sales_order_stock(
            sales_order=self.order,
            source_location=self.freezer,
        )

    def prepare_ready_order(self):
        confirm_sales_order(sales_order=self.order)
        self.allocate_order()
        mark_sales_order_ready(sales_order=self.order)

    def create_payment(self, amount, fee='0.00'):
        return SalesOrderPayment.objects.create(
            sales_order=self.order,
            financial_account=self.financial_account,
            amount=Decimal(amount),
            fee_amount=Decimal(fee),
            method=SalesPaymentMethod.PIX,
        )

    def test_confirmation_requires_items(self):
        empty_order = SalesOrder.objects.create(
            code='PED-EMPTY',
        )

        with self.assertRaisesMessage(
            ValidationError,
            'Adicione pelo menos um item',
        ):
            confirm_sales_order(sales_order=empty_order)

        empty_order.refresh_from_db()
        self.assertEqual(
            empty_order.status,
            SalesOrderStatus.DRAFT,
        )

        confirm_sales_order(sales_order=self.order)
        self.order.refresh_from_db()

        self.assertEqual(
            self.order.status,
            SalesOrderStatus.CONFIRMED,
        )

    def test_allocation_requires_source_location(self):
        confirm_sales_order(sales_order=self.order)

        with self.assertRaisesMessage(
            ValidationError,
            'Selecione um local',
        ):
            allocate_sales_order_stock(
                sales_order=self.order,
                source_location=None,
            )

        self.assertFalse(
            self.order_item.stock_allocations.exists(),
        )

    def test_fefo_uses_earliest_expiration_first(self):
        later_lot = self.create_lot(
            'LOT-LATER',
            '500',
            expires_in=30,
        )
        earlier_lot = self.create_lot(
            'LOT-EARLIER',
            '400',
            expires_in=10,
        )
        confirm_sales_order(sales_order=self.order)

        allocations = self.allocate_order()

        self.assertEqual(
            [
                (allocation.stock_lot_id, allocation.quantity)
                for allocation in allocations
            ],
            [
                (earlier_lot.pk, Decimal('400')),
                (later_lot.pk, Decimal('200')),
            ],
        )

        # Separar reserva os produtos, mas ainda não dá baixa.
        self.assertEqual(
            earlier_lot.quantity_at(self.freezer),
            Decimal('400'),
        )
        self.assertEqual(
            later_lot.quantity_at(self.freezer),
            Decimal('500'),
        )

    def test_allocation_skips_expired_and_blocked_lots(self):
        expired_lot = self.create_lot(
            'LOT-EXPIRED',
            '600',
            expires_in=-1,
        )
        blocked_lot = self.create_lot(
            'LOT-BLOCKED',
            '600',
            expires_in=5,
        )
        blocked_lot.is_blocked = True
        blocked_lot.save()

        available_lot = self.create_lot(
            'LOT-AVAILABLE',
            '600',
            expires_in=20,
        )
        confirm_sales_order(sales_order=self.order)

        allocations = self.allocate_order()

        self.assertEqual(len(allocations), 1)
        self.assertEqual(
            allocations[0].stock_lot_id,
            available_lot.pk,
        )
        self.assertEqual(
            expired_lot.quantity_at(self.freezer),
            Decimal('600'),
        )
        self.assertEqual(
            blocked_lot.quantity_at(self.freezer),
            Decimal('600'),
        )

    def test_insufficient_stock_rolls_back_partial_allocation(self):
        lot = self.create_lot('LOT-SHORT', '400')
        confirm_sales_order(sales_order=self.order)

        with self.assertRaisesMessage(
            ValidationError,
            'Estoque insuficiente',
        ):
            self.allocate_order()

        # Os 400 g não podem ficar parcialmente reservados.
        self.assertFalse(
            self.order_item.stock_allocations.exists(),
        )
        self.assertEqual(
            lot.quantity_at(self.freezer),
            Decimal('400'),
        )

    def test_another_order_cannot_use_reserved_stock(self):
        lot = self.create_lot('LOT-RESERVED', '600')
        confirm_sales_order(sales_order=self.order)
        self.allocate_order()

        second_order = SalesOrder.objects.create(
            code='PED-TEST-002',
            source_location=self.freezer,
        )
        second_item = SalesOrderItem.objects.create(
            sales_order=second_order,
            item=self.item,
            commercial_quantity=Decimal('1'),
            commercial_unit=self.package,
            base_quantity=Decimal('300'),
            unit_price=Decimal('25.00'),
        )
        confirm_sales_order(sales_order=second_order)

        with self.assertRaisesMessage(
            ValidationError,
            'Estoque insuficiente',
        ):
            allocate_sales_order_stock(
                sales_order=second_order,
                source_location=self.freezer,
            )

        self.assertFalse(
            second_item.stock_allocations.exists(),
        )
        self.assertEqual(
            self.order_item.allocated_quantity,
            Decimal('600'),
        )
        self.assertEqual(
            lot.quantity_at(self.freezer),
            Decimal('600'),
        )

    def test_completion_dispatches_stock_only_once(self):
        lot = self.create_lot('LOT-DISPATCH', '1000')
        self.prepare_ready_order()

        complete_sales_order(
            sales_order=self.order,
            user=self.user,
        )
        self.order.refresh_from_db()
        allocation = self.order_item.stock_allocations.get()

        self.assertEqual(
            self.order.status,
            SalesOrderStatus.COMPLETED,
        )
        self.assertIsNotNone(self.order.completed_at)
        self.assertEqual(
            lot.quantity_at(self.freezer),
            Decimal('400'),
        )
        self.assertEqual(
            allocation.dispatch_movement.movement_type,
            StockMovementType.SALE_DISPATCH,
        )
        self.assertEqual(
            allocation.dispatch_movement.quantity,
            Decimal('600'),
        )
        self.assertEqual(
            self.order.items_cost_total,
            Decimal('12.00'),
        )
        self.assertEqual(
            self.order.profit,
            Decimal('38.00'),
        )

        with self.assertRaises(ValidationError):
            complete_sales_order(
                sales_order=self.order,
                user=self.user,
            )

        self.assertEqual(
            lot.movements.filter(
                movement_type=StockMovementType.SALE_DISPATCH,
            ).count(),
            1,
        )
        self.assertEqual(
            lot.quantity_at(self.freezer),
            Decimal('400'),
        )

    def test_completion_failure_rolls_back_previous_dispatch(self):
        first_lot = self.create_lot(
            'LOT-FIRST',
            '300',
            expires_in=10,
        )
        second_lot = self.create_lot(
            'LOT-SECOND',
            '300',
            expires_in=20,
        )
        self.prepare_ready_order()

        # Simula uma perda física após a separação do pedido.
        record_stock_movement(
            lot=second_lot,
            movement_type=StockMovementType.ADJUSTMENT_OUT,
            quantity=Decimal('300'),
            source_location=self.freezer,
            user=self.user,
        )

        with self.assertRaises(ValidationError):
            complete_sales_order(
                sales_order=self.order,
                user=self.user,
            )

        self.order.refresh_from_db()

        self.assertEqual(
            self.order.status,
            SalesOrderStatus.READY,
        )
        self.assertIsNone(self.order.completed_at)
        self.assertEqual(
            first_lot.quantity_at(self.freezer),
            Decimal('300'),
        )
        self.assertFalse(
            first_lot.movements.filter(
                movement_type=StockMovementType.SALE_DISPATCH,
            ).exists(),
        )
        self.assertFalse(
            self.order_item.stock_allocations.filter(
                dispatch_movement__isnull=False,
            ).exists(),
        )

    def test_cancellation_returns_stock_without_refunding_payment(self):
        lot = self.create_lot('LOT-RETURN', '1000')
        self.prepare_ready_order()
        payment = self.create_payment('50.00')

        register_sales_payment(
            payment=payment,
            user=self.user,
        )
        complete_sales_order(
            sales_order=self.order,
            user=self.user,
        )

        cancel_sales_order(
            sales_order=self.order,
            user=self.user,
        )
        self.order.refresh_from_db()
        payment.refresh_from_db()
        allocation = self.order_item.stock_allocations.get()

        self.assertEqual(
            self.order.status,
            SalesOrderStatus.CANCELLED,
        )
        self.assertEqual(
            lot.quantity_at(self.freezer),
            Decimal('1000'),
        )
        self.assertEqual(
            allocation.return_movement.movement_type,
            StockMovementType.CUSTOMER_RETURN,
        )
        self.assertEqual(
            allocation.return_movement.quantity,
            Decimal('600'),
        )

        # O estorno financeiro é uma operação separada.
        self.assertEqual(
            payment.status,
            SalesPaymentStatus.PAID,
        )

        with self.assertRaises(ValidationError):
            cancel_sales_order(
                sales_order=self.order,
                user=self.user,
            )

        self.assertEqual(
            lot.movements.filter(
                movement_type=StockMovementType.CUSTOMER_RETURN,
            ).count(),
            1,
        )

    def test_payment_limits_fees_refund_and_cancellation(self):
        confirm_sales_order(sales_order=self.order)
        payment = self.create_payment('50.00', fee='2.00')

        register_sales_payment(
            payment=payment,
            user=self.user,
        )
        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            SalesPaymentStatus.PAID,
        )
        self.assertEqual(payment.received_by_id, self.user.pk)
        self.assertIsNotNone(payment.paid_at)
        self.assertEqual(payment.net_amount, Decimal('48.00'))
        self.assertEqual(self.order.paid_total, Decimal('50.00'))
        self.assertEqual(self.order.balance_due, Decimal('0.00'))
        self.assertEqual(
            self.order.payment_fees_total,
            Decimal('2.00'),
        )

        excess_payment = self.create_payment('0.01')

        with self.assertRaisesMessage(
            ValidationError,
            'não pode ultrapassar',
        ):
            register_sales_payment(
                payment=excess_payment,
                user=self.user,
            )

        excess_payment.refresh_from_db()
        self.assertEqual(
            excess_payment.status,
            SalesPaymentStatus.PENDING,
        )
        self.assertIsNone(excess_payment.paid_at)

        refund_sales_payment(payment=payment)
        payment.refresh_from_db()

        self.assertEqual(
            payment.status,
            SalesPaymentStatus.REFUNDED,
        )
        self.assertEqual(payment.net_amount, Decimal('0.00'))
        self.assertEqual(self.order.paid_total, Decimal('0.00'))

        cancel_sales_payment(payment=excess_payment)
        excess_payment.refresh_from_db()

        self.assertEqual(
            excess_payment.status,
            SalesPaymentStatus.CANCELLED,
        )

        with self.assertRaises(ValidationError):
            register_sales_payment(
                payment=excess_payment,
                user=self.user,
            )