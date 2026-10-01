from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import (
    FinancialAccount,
    FinancialMovement,
    FinancialMovementDirection,
    FinancialMovementKind,
)
from .services import (
    _record_financial_movement,
    _reverse_financial_movement,
)
from unittest.mock import patch

from django.utils import timezone

from catalog.models import (
    Item,
    ItemType,
    MeasurementDimension,
    UnitOfMeasure,
)
from sales.models import (
    SalesOrder,
    SalesOrderItem,
    SalesOrderPayment,
    SalesPaymentMethod,
    SalesPaymentStatus,
)
from sales.services import register_sales_payment, refund_sales_payment

from .services import post_sales_payment

class FinancialMovementServiceTests(TestCase):
    def setUp(self):
        self.account = FinancialAccount.objects.create(
            code='TEST-ACCOUNT',
            name='Conta para testes',
        )
        self.movement_date = date(2026, 1, 10)

    def _record(
        self,
        *,
        key,
        amount='100.00',
        direction=FinancialMovementDirection.INCOMING,
    ):
        return _record_financial_movement(
            financial_account=self.account,
            direction=direction,
            kind=FinancialMovementKind.ADJUSTMENT,
            amount=Decimal(amount),
            occurred_on=self.movement_date,
            description='Movimentação de teste',
            source_key=key,
        )

    def test_entries_and_outputs_update_balance(self):
        self._record(key='test:incoming', amount='100.00')
        self._record(
            key='test:outgoing',
            amount='35.50',
            direction=FinancialMovementDirection.OUTGOING,
        )

        self.assertEqual(
            self.account.current_balance,
            Decimal('64.50'),
        )

    def test_retry_does_not_duplicate_movement(self):
        first = self._record(key='test:retry')
        second = self._record(key='test:retry')

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(FinancialMovement.objects.count(), 1)
        self.assertEqual(
            self.account.current_balance,
            Decimal('100.00'),
        )

    def test_reused_key_with_different_amount_is_rejected(self):
        self._record(key='test:conflict', amount='100.00')

        with self.assertRaises(ValidationError):
            self._record(key='test:conflict', amount='120.00')

        self.assertEqual(FinancialMovement.objects.count(), 1)
        self.assertEqual(
            self.account.current_balance,
            Decimal('100.00'),
        )

    def test_reversal_preserves_original_and_is_not_duplicated(self):
        original = self._record(key='test:original')

        reversal = _reverse_financial_movement(
            movement=original,
            occurred_on=self.movement_date,
        )
        repeated = _reverse_financial_movement(
            movement=original,
            occurred_on=self.movement_date,
        )

        original.refresh_from_db()

        self.assertEqual(reversal.pk, repeated.pk)
        self.assertEqual(reversal.reversal_of_id, original.pk)
        self.assertEqual(original.amount, Decimal('100.00'))
        self.assertEqual(
            original.direction,
            FinancialMovementDirection.INCOMING,
        )
        self.assertEqual(FinancialMovement.objects.count(), 2)
        self.assertEqual(
            self.account.current_balance,
            Decimal('0.00'),
        )

    def test_reversal_before_original_date_is_rejected(self):
        original = self._record(key='test:date')

        with self.assertRaises(ValidationError):
            _reverse_financial_movement(
                movement=original,
                occurred_on=self.movement_date - timedelta(days=1),
            )

        self.assertEqual(FinancialMovement.objects.count(), 1)
        self.assertEqual(
            self.account.current_balance,
            Decimal('100.00'),
        )

    def test_nonpositive_amount_is_rejected(self):
        for amount in ('0.00', '-1.00'):
            with self.subTest(amount=amount):
                with self.assertRaises(ValidationError):
                    self._record(
                        key=f'test:invalid:{amount}',
                        amount=amount,
                    )

        self.assertEqual(FinancialMovement.objects.count(), 0)

    def test_inactive_account_rejects_new_movement(self):
        self.account.is_active = False
        self.account.save()

        with self.assertRaises(ValidationError):
            self._record(key='test:inactive')

        self.assertEqual(FinancialMovement.objects.count(), 0)

    def test_reversal_of_reversal_is_rejected(self):
        original = self._record(key='test:double-reversal')
        reversal = _reverse_financial_movement(
            movement=original,
            occurred_on=self.movement_date,
        )

        with self.assertRaises(ValidationError):
            _reverse_financial_movement(
                movement=reversal,
                occurred_on=self.movement_date,
            )

        self.assertEqual(FinancialMovement.objects.count(), 2)
        self.assertEqual(
            self.account.current_balance,
            Decimal('0.00'),
        )
class SalesPaymentFinanceTests(TestCase):
    def setUp(self):
        self.account = FinancialAccount.objects.create(
            code='SALES-TEST',
            name='Conta de recebimentos para testes',
        )
        unit = UnitOfMeasure.objects.create(
            code='FIN-UN',
            name='Unidade para testes',
            symbol='un',
            dimension=MeasurementDimension.COUNT,
        )
        item = Item.objects.create(
            name='Produto para teste financeiro',
            item_type=ItemType.FINISHED_PRODUCT,
            base_unit=unit,
            is_sellable=True,
            tracks_inventory=False,
        )
        self.order = SalesOrder.objects.create(code='FIN-TEST-001')
        SalesOrderItem.objects.create(
            sales_order=self.order,
            item=item,
            commercial_quantity=Decimal('1'),
            commercial_unit=unit,
            base_quantity=Decimal('1'),
            unit_price=Decimal('100.00'),
        )
        self.payment = SalesOrderPayment.objects.create(
            sales_order=self.order,
            financial_account=self.account,
            amount=Decimal('100.00'),
            fee_amount=Decimal('3.00'),
            method=SalesPaymentMethod.CREDIT_CARD,
        )

    def test_receipt_creates_gross_entry_and_fee(self):
        register_sales_payment(payment=self.payment)

        self.payment.refresh_from_db()

        self.assertEqual(self.payment.status, SalesPaymentStatus.PAID)
        self.assertEqual(
            self.account.current_balance,
            Decimal('97.00'),
        )
        self.assertEqual(self.payment.financial_movements.count(), 2)

    def test_posting_again_does_not_duplicate_entries(self):
        register_sales_payment(payment=self.payment)

        first = post_sales_payment(payment=self.payment)
        second = post_sales_payment(payment=self.payment)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(self.payment.financial_movements.count(), 2)
        self.assertEqual(
            self.account.current_balance,
            Decimal('97.00'),
        )

    def test_refund_reverses_receipt_and_keeps_fee(self):
        register_sales_payment(payment=self.payment)
        refund_sales_payment(payment=self.payment)

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            SalesPaymentStatus.REFUNDED,
        )
        self.assertEqual(self.payment.financial_movements.count(), 3)
        self.assertEqual(
            self.account.current_balance,
            Decimal('-3.00'),
        )

    def test_missing_account_rolls_back_payment_registration(self):
        self.payment.financial_account = None
        self.payment.save()

        with self.assertRaises(ValidationError):
            register_sales_payment(payment=self.payment)

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            SalesPaymentStatus.PENDING,
        )
        self.assertIsNone(self.payment.paid_at)
        self.assertEqual(FinancialMovement.objects.count(), 0)

    def test_fee_failure_rolls_back_receipt_and_payment(self):
        def fail_on_fee(**kwargs):
            if kwargs['kind'] == FinancialMovementKind.SALE_FEE:
                raise ValidationError('Falha simulada na taxa.')

            return _record_financial_movement(**kwargs)

        with patch(
            'finance.services._record_financial_movement',
            side_effect=fail_on_fee,
        ):
            with self.assertRaises(ValidationError):
                register_sales_payment(payment=self.payment)

        self.payment.refresh_from_db()

        self.assertEqual(
            self.payment.status,
            SalesPaymentStatus.PENDING,
        )
        self.assertIsNone(self.payment.paid_at)
        self.assertEqual(FinancialMovement.objects.count(), 0)

    def test_payment_without_fee_creates_only_receipt(self):
        self.payment.fee_amount = Decimal('0.00')
        self.payment.save()

        register_sales_payment(payment=self.payment)

        self.assertEqual(self.payment.financial_movements.count(), 1)
        self.assertEqual(
            self.account.current_balance,
            Decimal('100.00'),
        )

    def test_changed_fee_is_rejected_when_posting_again(self):
        register_sales_payment(payment=self.payment)

        SalesOrderPayment.objects.filter(pk=self.payment.pk).update(
            fee_amount=Decimal('0.00'),
        )

        with self.assertRaises(ValidationError):
            post_sales_payment(payment=self.payment)

        self.assertEqual(self.payment.financial_movements.count(), 2)
        self.assertEqual(
            self.account.current_balance,
            Decimal('97.00'),
        )

    def test_refund_without_original_entry_is_rejected(self):
        self.payment.status = SalesPaymentStatus.PAID
        self.payment.paid_at = timezone.now()
        self.payment.save()

        with self.assertRaises(ValidationError):
            refund_sales_payment(payment=self.payment)

        self.payment.refresh_from_db()

        self.assertEqual(self.payment.status, SalesPaymentStatus.PAID)
        self.assertEqual(FinancialMovement.objects.count(), 0)