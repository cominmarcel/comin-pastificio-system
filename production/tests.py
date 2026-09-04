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
    StockLocationType,
    StockLot,
    StockMovement,
    StockMovementType,
)
from inventory.services import record_stock_movement
from recipes.models import (
    Recipe,
    RecipeIngredient,
    RecipeStep,
    RecipeVersion,
    RecipeVersionStatus,
)

from .models import (
    ProductionBatch,
    ProductionStatus,
    ProductionStepStatus,
)
from .services import (
    cancel_production_batch,
    complete_production_batch,
    prepare_production_batch,
    start_production_batch,
)


class ProductionServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='production-tester',
            password='test-password',
        )
        self.gram = UnitOfMeasure.objects.create(
            code='g-test',
            name='Grama de teste',
            symbol='g',
            dimension=MeasurementDimension.MASS,
            factor_to_base_unit=Decimal('1.000000'),
        )
        self.ingredient_item = Item.objects.create(
            name='Farinha de teste',
            sku='ING-PROD-TEST',
            item_type=ItemType.INGREDIENT,
            base_unit=self.gram,
            is_purchasable=True,
            tracks_inventory=True,
        )
        self.output_item = Item.objects.create(
            name='Massa fresca de teste',
            sku='FIN-PROD-TEST',
            item_type=ItemType.FINISHED_PRODUCT,
            base_unit=self.gram,
            is_producible=True,
            is_sellable=True,
            tracks_inventory=True,
        )
        self.location = StockLocation.objects.create(
            code='PROD-TEST',
            name='Área de produção de teste',
            location_type=StockLocationType.PRODUCTION,
        )
        self.ingredient_lot = StockLot.objects.create(
            item=self.ingredient_item,
            code='LOT-ING-PROD-TEST',
            received_date=timezone.localdate(),
            expiration_date=(
                timezone.localdate() + timedelta(days=30)
            ),
            unit_cost=Decimal('0.02000000'),
        )
        record_stock_movement(
            lot=self.ingredient_lot,
            movement_type=StockMovementType.OPENING_BALANCE,
            quantity=Decimal('1000.000000'),
            destination_location=self.location,
            reference='Saldo para teste de produção',
            user=self.user,
        )
        self.recipe = Recipe.objects.create(
            code='REC-PROD-TEST',
            name='Receita de produção de teste',
            output_item=self.output_item,
            created_by=self.user,
        )
        self.recipe_version = RecipeVersion.objects.create(
            recipe=self.recipe,
            version=1,
            status=RecipeVersionStatus.ACTIVE,
            yield_quantity=Decimal('100.000000'),
            active_time_minutes=60,
            total_time_minutes=90,
            hourly_labor_cost=Decimal('30.00'),
            approved_by=self.user,
            approved_at=timezone.now(),
        )
        self.recipe_ingredient = RecipeIngredient.objects.create(
            recipe_version=self.recipe_version,
            sequence=1,
            item=self.ingredient_item,
            quantity=Decimal('50.000000'),
        )
        self.recipe_step = RecipeStep.objects.create(
            recipe_version=self.recipe_version,
            sequence=1,
            phase='Massa',
            title='Misturar os ingredientes',
            instructions='Misture até formar uma massa homogênea.',
            duration_minutes=10,
            requires_active_work=True,
        )
        self.production_batch = ProductionBatch.objects.create(
            code='PROD-BATCH-TEST',
            recipe_version=self.recipe_version,
            planned_quantity=Decimal('200.000000'),
            destination_location=self.location,
            expiration_date=(
                timezone.localdate() + timedelta(days=90)
            ),
            responsible=self.user,
            created_by=self.user,
        )

    def prepare_and_start(self):
        prepare_production_batch(
            production_batch=self.production_batch,
        )
        start_production_batch(
            production_batch=self.production_batch,
            user=self.user,
        )
        self.production_batch.refresh_from_db()

    def fill_execution_data(
        self,
        *,
        material_quantity=Decimal('120.000000'),
        output_quantity=Decimal('180.000000'),
    ):
        material = self.production_batch.materials.get()
        material.actual_quantity = material_quantity
        material.stock_lot = self.ingredient_lot
        material.source_location = self.location
        material.full_clean()
        material.save()

        step_execution = self.production_batch.step_executions.get()
        step_execution.status = ProductionStepStatus.COMPLETED
        step_execution.started_at = timezone.now()
        step_execution.completed_at = timezone.now()
        step_execution.performed_by = self.user
        step_execution.full_clean()
        step_execution.save()

        self.production_batch.actual_quantity = output_quantity
        self.production_batch.actual_active_time_minutes = 70
        self.production_batch.actual_additional_cost = Decimal('5.00')
        self.production_batch.save()

    def test_prepare_production_scales_materials_and_creates_steps(self):
        production_batch, materials, steps = prepare_production_batch(
            production_batch=self.production_batch,
        )

        self.assertEqual(
            production_batch.pk,
            self.production_batch.pk,
        )
        self.assertEqual(len(materials), 1)
        self.assertEqual(len(steps), 1)
        self.assertEqual(
            materials[0].planned_quantity,
            Decimal('100.000000'),
        )
        self.assertEqual(
            materials[0].recipe_ingredient,
            self.recipe_ingredient,
        )
        self.assertEqual(
            steps[0].recipe_step,
            self.recipe_step,
        )

    def test_start_production_updates_status_and_start_time(self):
        prepare_production_batch(
            production_batch=self.production_batch,
        )

        started_batch = start_production_batch(
            production_batch=self.production_batch,
            user=self.user,
        )

        self.assertEqual(
            started_batch.status,
            ProductionStatus.IN_PROGRESS,
        )
        self.assertIsNotNone(started_batch.started_at)
        self.assertEqual(started_batch.responsible, self.user)

    def test_complete_production_consumes_stock_and_creates_output(self):
        self.prepare_and_start()
        self.fill_execution_data()

        completed_batch = complete_production_batch(
            production_batch=self.production_batch,
            output_lot_code='LOT-OUTPUT-PROD-TEST',
            user=self.user,
        )

        self.ingredient_lot.refresh_from_db()
        completed_batch.refresh_from_db()

        self.assertEqual(
            completed_batch.status,
            ProductionStatus.COMPLETED,
        )
        self.assertIsNotNone(completed_batch.completed_at)
        self.assertEqual(completed_batch.completed_by, self.user)
        self.assertEqual(
            self.ingredient_lot.quantity_at(self.location),
            Decimal('880.000000'),
        )
        self.assertEqual(
            completed_batch.output_lot.quantity_at(self.location),
            Decimal('180.000000'),
        )
        self.assertEqual(
            completed_batch.output_lot.item,
            self.output_item,
        )
        self.assertEqual(
            completed_batch.output_movement.movement_type,
            StockMovementType.PRODUCTION_OUTPUT,
        )
        self.assertEqual(
            completed_batch.materials.get().movement.movement_type,
            StockMovementType.PRODUCTION_CONSUMPTION,
        )
        self.assertEqual(
            completed_batch.output_lot.unit_cost,
            Decimal('0.23555556'),
        )

    def test_insufficient_stock_rolls_back_completion(self):
        self.prepare_and_start()
        self.fill_execution_data(
            material_quantity=Decimal('1001.000000'),
        )

        with self.assertRaises(ValidationError):
            complete_production_batch(
                production_batch=self.production_batch,
                output_lot_code='LOT-FAILED-PROD-TEST',
                user=self.user,
            )

        self.production_batch.refresh_from_db()

        self.assertEqual(
            self.production_batch.status,
            ProductionStatus.IN_PROGRESS,
        )
        self.assertFalse(
            StockLot.objects.filter(
                code='LOT-FAILED-PROD-TEST',
            ).exists(),
        )
        self.assertFalse(
            StockMovement.objects.filter(
                movement_type=(
                    StockMovementType.PRODUCTION_CONSUMPTION
                ),
                reference=f'Produção {self.production_batch.code}',
            ).exists(),
        )

    def test_cancel_production_without_movements(self):
        prepare_production_batch(
            production_batch=self.production_batch,
        )

        cancelled_batch = cancel_production_batch(
            production_batch=self.production_batch,
        )

        self.assertEqual(
            cancelled_batch.status,
            ProductionStatus.CANCELLED,
        )

        with self.assertRaises(ValidationError):
            start_production_batch(
                production_batch=cancelled_batch,
                user=self.user,
            )

    def test_inactive_recipe_version_cannot_be_prepared(self):
        self.recipe_version.status = RecipeVersionStatus.ARCHIVED
        self.recipe_version.save()

        with self.assertRaises(ValidationError):
            prepare_production_batch(
                production_batch=self.production_batch,
            )