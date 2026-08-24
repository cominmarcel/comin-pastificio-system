from decimal import Decimal

from django.db import migrations


UNITS = [
    {
        'code': 'mg',
        'name': 'Miligrama',
        'symbol': 'mg',
        'dimension': 'mass',
        'factor_to_base_unit': Decimal('0.001'),
    },
    {
        'code': 'g',
        'name': 'Grama',
        'symbol': 'g',
        'dimension': 'mass',
        'factor_to_base_unit': Decimal('1'),
    },
    {
        'code': 'kg',
        'name': 'Quilograma',
        'symbol': 'kg',
        'dimension': 'mass',
        'factor_to_base_unit': Decimal('1000'),
    },
    {
        'code': 'ml',
        'name': 'Mililitro',
        'symbol': 'mL',
        'dimension': 'volume',
        'factor_to_base_unit': Decimal('1'),
    },
    {
        'code': 'l',
        'name': 'Litro',
        'symbol': 'L',
        'dimension': 'volume',
        'factor_to_base_unit': Decimal('1000'),
    },
    {
        'code': 'm3',
        'name': 'Metro cúbico',
        'symbol': 'm³',
        'dimension': 'volume',
        'factor_to_base_unit': Decimal('1000000'),
    },
    {
        'code': 'un',
        'name': 'Unidade',
        'symbol': 'un',
        'dimension': 'count',
        'factor_to_base_unit': Decimal('1'),
    },
    {
        'code': 'dz',
        'name': 'Dúzia',
        'symbol': 'dz',
        'dimension': 'count',
        'factor_to_base_unit': Decimal('12'),
    },
    {
        'code': 'pkg',
        'name': 'Pacote',
        'symbol': 'pct',
        'dimension': 'count',
        'factor_to_base_unit': Decimal('1'),
    },
    {
        'code': 'min',
        'name': 'Minuto',
        'symbol': 'min',
        'dimension': 'time',
        'factor_to_base_unit': Decimal('1'),
    },
    {
        'code': 'h',
        'name': 'Hora',
        'symbol': 'h',
        'dimension': 'time',
        'factor_to_base_unit': Decimal('60'),
    },
    {
        'code': 'kwh',
        'name': 'Quilowatt-hora',
        'symbol': 'kWh',
        'dimension': 'energy',
        'factor_to_base_unit': Decimal('1'),
    },
    {
        'code': 'cm',
        'name': 'Centímetro',
        'symbol': 'cm',
        'dimension': 'length',
        'factor_to_base_unit': Decimal('0.01'),
    },
    {
        'code': 'm',
        'name': 'Metro',
        'symbol': 'm',
        'dimension': 'length',
        'factor_to_base_unit': Decimal('1'),
    },
]


def seed_units(apps, schema_editor):
    unit_model = apps.get_model('catalog', 'UnitOfMeasure')

    for unit in UNITS:
        code = unit['code']
        defaults = {
            **unit,
            'is_active': True,
        }
        defaults.pop('code')

        unit_model.objects.update_or_create(
            code=code,
            defaults=defaults,
        )


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            seed_units,
            reverse_code=migrations.RunPython.noop,
        ),
    ]