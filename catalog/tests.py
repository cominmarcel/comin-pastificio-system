from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Item, ItemType, UnitOfMeasure


class UnitOfMeasureModelTests(TestCase):
    def test_seeded_mass_units_exist_with_correct_factors(self):
        gram = UnitOfMeasure.objects.get(code='g')
        kilogram = UnitOfMeasure.objects.get(code='kg')

        self.assertEqual(gram.factor_to_base_unit, Decimal('1'))
        self.assertEqual(kilogram.factor_to_base_unit, Decimal('1000'))


class ItemModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.unit = UnitOfMeasure.objects.get(code='un')
        cls.gram = UnitOfMeasure.objects.get(code='g')

    def test_item_string_contains_name_and_sku(self):
        item = Item.objects.create(
            name='Ravioli al Ragù 300 g',
            sku='RAV-RAG-300',
            item_type=ItemType.FINISHED_PRODUCT,
            base_unit=self.unit,
            net_content_quantity=Decimal('300'),
            net_content_unit=self.gram,
            is_producible=True,
            is_sellable=True,
        )

        self.assertEqual(
            str(item),
            'Ravioli al Ragù 300 g [RAV-RAG-300]',
        )

    def test_net_content_quantity_requires_a_unit(self):
        item = Item(
            name='Produto inválido',
            item_type=ItemType.FINISHED_PRODUCT,
            base_unit=self.unit,
            net_content_quantity=Decimal('300'),
            net_content_unit=None,
        )

        with self.assertRaises(ValidationError):
            item.full_clean()