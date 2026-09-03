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
from inventory.models import StockLot

from .models import (
    AdditionalCostType,
    Recipe,
    RecipeAdditionalCost,
    RecipeIngredient,
    RecipeVersion,
    RecipeVersionStatus,
)
from .services import activate_recipe_version


class RecipeTests(TestCase):
    def setUp(self):
        self.gram = UnitOfMeasure.objects.create(
            code='G',
            name='Grama',
            symbol='g',
            dimension=MeasurementDimension.MASS,
            factor_to_base_unit=Decimal('1'),
        )
        self.flour = Item.objects.create(
            name='Farinha de teste',
            sku='ING-TEST-001',
            item_type=ItemType.INGREDIENT,
            base_unit=self.gram,
            is_purchasable=True,
            tracks_inventory=True,
        )
        self.pasta = Item.objects.create(
            name='Massa fresca de teste',
            sku='PROD-TEST-001',
            item_type=ItemType.INTERMEDIATE,
            base_unit=self.gram,
            is_producible=True,
            tracks_inventory=True,
        )
        self.recipe = Recipe.objects.create(
            code='REC-TEST-001',
            name='Massa fresca de teste',
            output_item=self.pasta,
        )
        self.version = RecipeVersion.objects.create(
            recipe=self.recipe,
            version=1,
            yield_quantity=Decimal('900'),
            active_time_minutes=60,
            total_time_minutes=90,
            hourly_labor_cost=Decimal('25.00'),
        )

    def add_costed_ingredient(self, version=None):
        version = version or self.version

        StockLot.objects.get_or_create(
            item=self.flour,
            code='LOT-FLOUR-001',
            defaults={
                'received_date': timezone.localdate(),
                'unit_cost': Decimal('0.01000000'),
            },
        )

        return RecipeIngredient.objects.create(
            recipe_version=version,
            sequence=1,
            item=self.flour,
            quantity=Decimal('600'),
        )

    def test_recipe_calculates_all_costs(self):
        self.add_costed_ingredient()

        RecipeAdditionalCost.objects.create(
            recipe_version=self.version,
            cost_type=AdditionalCostType.GAS,
            description='Gás utilizado',
            amount=Decimal('2.00'),
        )

        self.assertEqual(
            self.version.ingredients_cost,
            Decimal('6.00'),
        )
        self.assertEqual(
            self.version.labor_cost,
            Decimal('25.00'),
        )
        self.assertEqual(
            self.version.additional_costs_total,
            Decimal('2.00'),
        )
        self.assertEqual(
            self.version.total_cost,
            Decimal('33.00'),
        )
        self.assertEqual(
            self.version.cost_per_base_unit.quantize(
                Decimal('0.00000001'),
            ),
            Decimal('0.03666667'),
        )

    def test_activation_archives_previous_version(self):
        self.add_costed_ingredient()
        activate_recipe_version(
            recipe_version=self.version,
        )

        second_version = RecipeVersion.objects.create(
            recipe=self.recipe,
            version=2,
            yield_quantity=Decimal('950'),
            active_time_minutes=55,
            hourly_labor_cost=Decimal('25.00'),
        )
        self.add_costed_ingredient(
            version=second_version,
        )

        activate_recipe_version(
            recipe_version=second_version,
        )

        self.version.refresh_from_db()
        second_version.refresh_from_db()

        self.assertEqual(
            self.version.status,
            RecipeVersionStatus.ARCHIVED,
        )
        self.assertEqual(
            second_version.status,
            RecipeVersionStatus.ACTIVE,
        )
        self.assertIsNotNone(second_version.approved_at)

    def test_version_without_ingredient_cannot_be_activated(self):
        with self.assertRaises(ValidationError):
            activate_recipe_version(
                recipe_version=self.version,
            )

    def test_ingredient_without_cost_blocks_activation(self):
        RecipeIngredient.objects.create(
            recipe_version=self.version,
            sequence=1,
            item=self.flour,
            quantity=Decimal('600'),
        )

        with self.assertRaises(ValidationError):
            activate_recipe_version(
                recipe_version=self.version,
            )

    def test_total_time_cannot_be_shorter_than_active_time(self):
        self.version.total_time_minutes = 30

        with self.assertRaises(ValidationError):
            self.version.full_clean()

    def test_product_cannot_be_its_own_ingredient(self):
        ingredient = RecipeIngredient(
            recipe_version=self.version,
            sequence=1,
            item=self.pasta,
            quantity=Decimal('100'),
        )

        with self.assertRaises(ValidationError):
            ingredient.full_clean()