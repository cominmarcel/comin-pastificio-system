from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from catalog.models import (
    Item,
    ItemType,
    MeasurementDimension,
    UnitOfMeasure,
)
from purchases.models import (
    Purchase,
    PurchaseItem,
    PurchaseStatus,
)

from .models import (
    StockCount,
    StockCountStatus,
    StockLocation,
    StockLot,
    StockMovementType,
)
from .services import (
    complete_stock_count,
    prepare_stock_count,
    receive_purchase_item,
    record_stock_movement,
)


class InventoryServiceTests(TestCase):
    def setUp(self):
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
            name='Farinha de teste',
            sku='TEST-001',
            item_type=ItemType.INGREDIENT,
            base_unit=self.gram,
            is_purchasable=True,
            tracks_inventory=True,
        )
        self.freezer = StockLocation.objects.create(
            code='FREEZER-01',
            name='Freezer de teste',
            location_type='frozen',
        )
        self.pantry = StockLocation.objects.create(
            code='PANTRY-01',
            name='Despensa de teste',
            location_type='general',
        )
        self.lot = StockLot.objects.create(
            item=self.item,
            code='LOT-TEST-001',
            received_date=timezone.localdate(),
            unit_cost=Decimal('0.00699000'),
        )

    def test_entry_and_output_update_balance(self):
        record_stock_movement(
            lot=self.lot,
            movement_type=StockMovementType.OPENING_BALANCE,
            quantity=Decimal('1000'),
            destination_location=self.pantry,
        )
        record_stock_movement(
            lot=self.lot,
            movement_type=StockMovementType.ADJUSTMENT_OUT,
            quantity=Decimal('250'),
            source_location=self.pantry,
        )

        self.assertEqual(
            self.lot.quantity_at(self.pantry),
            Decimal('750'),
        )
        self.assertEqual(
            self.lot.current_quantity,
            Decimal('750'),
        )

    def test_output_cannot_exceed_available_stock(self):
        record_stock_movement(
            lot=self.lot,
            movement_type=StockMovementType.OPENING_BALANCE,
            quantity=Decimal('100'),
            destination_location=self.pantry,
        )

        with self.assertRaises(ValidationError):
            record_stock_movement(
                lot=self.lot,
                movement_type=StockMovementType.ADJUSTMENT_OUT,
                quantity=Decimal('101'),
                source_location=self.pantry,
            )

    def test_transfer_preserves_total_quantity(self):
        record_stock_movement(
            lot=self.lot,
            movement_type=StockMovementType.OPENING_BALANCE,
            quantity=Decimal('100'),
            destination_location=self.pantry,
        )
        record_stock_movement(
            lot=self.lot,
            movement_type=StockMovementType.TRANSFER,
            quantity=Decimal('40'),
            source_location=self.pantry,
            destination_location=self.freezer,
        )

        self.assertEqual(
            self.lot.quantity_at(self.pantry),
            Decimal('60'),
        )
        self.assertEqual(
            self.lot.quantity_at(self.freezer),
            Decimal('40'),
        )
        self.assertEqual(
            self.lot.current_quantity,
            Decimal('100'),
        )

    def test_expired_lot_cannot_be_used_in_production(self):
        self.lot.expiration_date = (
            timezone.localdate() - timedelta(days=1)
        )
        self.lot.save()

        record_stock_movement(
            lot=self.lot,
            movement_type=StockMovementType.OPENING_BALANCE,
            quantity=Decimal('100'),
            destination_location=self.pantry,
        )

        with self.assertRaises(ValidationError):
            record_stock_movement(
                lot=self.lot,
                movement_type=(
                    StockMovementType.PRODUCTION_CONSUMPTION
                ),
                quantity=Decimal('10'),
                source_location=self.pantry,
            )

    def test_purchase_item_can_be_received_into_stock(self):
        purchase = Purchase.objects.create(
            purchase_date=timezone.localdate(),
            received_date=timezone.localdate(),
            status=PurchaseStatus.RECEIVED,
        )
        purchase_item = PurchaseItem.objects.create(
            purchase=purchase,
            item=self.item,
            commercial_quantity=Decimal('1'),
            commercial_unit=self.package,
            base_quantity=Decimal('1000'),
            unit_price=Decimal('6.99'),
        )

        lot, movement = receive_purchase_item(
            purchase_item=purchase_item,
            destination_location=self.pantry,
            lot_code='LOT-PURCHASE-001',
        )

        self.assertEqual(
            movement.movement_type,
            StockMovementType.PURCHASE_RECEIPT,
        )
        self.assertEqual(
            movement.quantity,
            Decimal('1000'),
        )
        self.assertEqual(
            lot.current_quantity,
            Decimal('1000'),
        )
        self.assertEqual(
            lot.unit_cost,
            Decimal('0.00699000'),
        )

    def test_stock_count_creates_adjustment(self):
        record_stock_movement(
            lot=self.lot,
            movement_type=StockMovementType.OPENING_BALANCE,
            quantity=Decimal('100'),
            destination_location=self.pantry,
        )
        stock_count = StockCount.objects.create(
            location=self.pantry,
        )

        lines = prepare_stock_count(
            stock_count=stock_count,
        )
        line = lines[0]
        line.counted_quantity = Decimal('90')
        line.save()

        movements = complete_stock_count(
            stock_count=stock_count,
        )
        stock_count.refresh_from_db()

        self.assertEqual(len(movements), 1)
        self.assertEqual(
            movements[0].movement_type,
            StockMovementType.ADJUSTMENT_OUT,
        )
        self.assertEqual(
            self.lot.current_quantity,
            Decimal('90'),
        )
        self.assertEqual(
            stock_count.status,
            StockCountStatus.COMPLETED,
        )