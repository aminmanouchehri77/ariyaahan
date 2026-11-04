from django.db import migrations


CATEGORIES = [
    ('میلگرد', 'rebar', 'آجدار، ساده و کلاف', 'RB', 10),
    ('تیرآهن', 'beam', 'انواع تیرآهن و سایزهای مختلف', 'BM', 20),
    ('ورق فولادی', 'steel-sheet', 'ورق سیاه، آلیاژی و پوشش‌دار', 'SH', 30),
    ('لوله', 'pipe', 'لوله‌های صنعتی و ساختمانی', 'PI', 40),
    ('قوطی و پروفیل', 'profiles', 'قوطی، پروفیل و مقاطع باز', 'PF', 50),
    ('نبشی و ناودانی', 'angles-channels', 'مقاطع نبشی و ناودانی', 'AN', 60),
    ('محصولات مفتولی', 'wire-products', 'مفتول، توری و محصولات وابسته', 'WR', 70),
    ('شمش', 'billets', 'شمش فولادی و آلیاژی', 'BL', 80),
    ('مواد اولیه', 'raw-materials', 'مواد اولیه و محصولات میانی فولاد', 'RM', 90),
    ('فروآلیاژ', 'ferroalloy', 'فروآلیاژهای مورد استفاده در تولید فولاد', 'FA', 100),
]


def seed_categories(apps, schema_editor):
    Category = apps.get_model('catalog', 'Category')
    for name, slug, description, icon_key, sort_order in CATEGORIES:
        Category.objects.get_or_create(
            slug=slug,
            defaults={
                'name': name,
                'description': description,
                'icon_key': icon_key,
                'sort_order': sort_order,
                'is_active': True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_categories, migrations.RunPython.noop),
    ]
