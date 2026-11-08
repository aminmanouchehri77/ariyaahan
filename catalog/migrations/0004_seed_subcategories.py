from django.db import migrations

# Sub-groups listed in the proposal's appendix (reference category map).
# Only the taxonomy is seeded; no prices, products or stock are created.
SUBCATEGORIES = {
    'rebar': [
        ('میلگرد آجدار', 'rebar-ribbed', 'میلگرد آجدار A3 و A4 کارخانه‌های داخلی'),
        ('میلگرد ساده', 'rebar-plain', 'میلگرد ساده A1 برای مصارف عمومی و صنعتی'),
        ('میلگرد کلاف', 'rebar-coil', 'میلگرد کلاف ساده و آجدار'),
        ('خاموت', 'stirrup', 'خاموت آماده در سایزها و ابعاد استاندارد'),
    ],
    'beam': [
        ('تیرآهن معمولی IPE', 'beam-ipe', 'تیرآهن استاندارد اروپایی IPE'),
        ('تیرآهن بال‌پهن', 'beam-ipb', 'تیرآهن هاش و بال‌پهن IPB'),
    ],
    'steel-sheet': [
        ('ورق سیاه', 'sheet-black', 'ورق گرم ST37 و ST52 در ضخامت‌های مختلف'),
        ('ورق آلیاژی', 'sheet-alloy', 'ورق‌های A516، A283 و آلیاژی خاص'),
        ('ورق گالوانیزه', 'sheet-galvanized', 'ورق با پوشش روی برای مقاومت در برابر خوردگی'),
        ('ورق رنگی', 'sheet-coated', 'ورق پیش‌رنگ‌شده برای سقف و نما'),
        ('ورق روغنی', 'sheet-cold-rolled', 'ورق نورد سرد روغنی'),
        ('ورق آجدار', 'sheet-checkered', 'ورق آجدار برای کف و پله'),
        ('تسمه', 'flat-bar', 'تسمهٔ فولادی در عرض و ضخامت‌های مختلف'),
    ],
    'pipe': [
        ('لوله داربستی', 'pipe-scaffold', 'لوله داربست ساختمانی'),
        ('لوله صنعتی', 'pipe-industrial', 'لوله درزدار صنعتی'),
        ('لوله گازی', 'pipe-gas', 'لوله گازی با پوشش و بدون پوشش'),
        ('لوله اسپیرال', 'pipe-spiral', 'لوله اسپیرال قطر بالا'),
        ('لوله تست آب', 'pipe-hydrotest', 'لوله تست‌شده با فشار آب'),
        ('لوله مانیسمان', 'pipe-seamless', 'لوله بدون درز'),
        ('لوله جداره چاه', 'pipe-well-casing', 'لوله جداره برای چاه آب'),
    ],
    'profiles': [
        ('قوطی صنعتی', 'box-industrial', 'قوطی مربع و مستطیل صنعتی'),
        ('قوطی ستونی', 'box-column', 'قوطی ستونی ضخامت بالا'),
        ('پروفیل Z', 'profile-z', 'پروفیل Z برای سازه‌های سبک'),
        ('پروفیل آبرو', 'profile-gutter', 'پروفیل آبرو و ناودانی سبک'),
        ('سی پرلین', 'c-purlin', 'پروفیل C برای سقف و دیوار سوله'),
    ],
    'angles-channels': [
        ('نبشی', 'angle', 'نبشی بال‌مساوی و بال‌نامساوی'),
        ('ناودانی', 'channel', 'ناودانی UNP و سبک'),
    ],
    'wire-products': [
        ('سیم مفتولی سیاه', 'wire-black', 'سیم مفتولی سیاه برای آرماتوربندی'),
        ('زیگزاگ و حرارتی', 'wire-annealed', 'سیم حرارتی و زیگزاگ'),
        ('توری', 'wire-mesh', 'توری مرغی، حصاری و صنعتی'),
        ('مش', 'mesh', 'مش ساده و آجدار'),
        ('سیم خاردار', 'barbed-wire', 'سیم خاردار حفاظتی'),
    ],
    'billets': [
        ('شمش فولادی', 'billet-steel', 'شمش فولادی 5SP و 3SP'),
        ('شمش آلیاژی', 'billet-alloy', 'شمش آلیاژی برای تولید مقاطع خاص'),
    ],
    'raw-materials': [
        ('آهن اسفنجی', 'dri', 'آهن اسفنجی (DRI) برای فولادسازی'),
        ('گندله', 'pellet', 'گندلهٔ سنگ‌آهن'),
    ],
}


def seed(apps, schema_editor):
    Category = apps.get_model('catalog', 'Category')
    for parent_slug, children in SUBCATEGORIES.items():
        parent = Category.objects.filter(slug=parent_slug).first()
        if parent is None:
            continue
        for index, (name, slug, description) in enumerate(children, start=1):
            Category.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'parent': parent,
                    'description': description,
                    'sort_order': index * 10,
                    'is_active': True,
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0003_savedcomparison_savedcomparisonitem'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
