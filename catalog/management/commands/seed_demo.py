"""Create clearly-labelled demo catalogue data for local design review.

Refuses to run unless DEBUG is on. Every price/stock row has the source
«دادهٔ نمایشی — غیرواقعی» so it can never be mistaken for company data.
Remove it with ``seed_demo --purge``.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from catalog.models import Category, Manufacturer, Product, ProductVariant
from content.models import Article, MarketNews
from pricing.models import InventoryLocation, PriceObservation, StockObservation

DEMO_SOURCE = 'دادهٔ نمایشی — غیرواقعی'
DEMO_PREFIX = 'demo-'

CATALOG = [
    ('rebar-ribbed', 'میلگرد آجدار', 'میلگرد آجدار A3 مناسب سازه‌های بتنی', 'kg', [
        ('ذوب‌آهن اصفهان', 'سایز ۱۲ — A3', '12', 'A3', 'ISIRI 3132', Decimal('0.888'), 285000),
        ('ذوب‌آهن اصفهان', 'سایز ۱۴ — A3', '14', 'A3', 'ISIRI 3132', Decimal('1.210'), 283500),
        ('فولاد میانه', 'سایز ۱۶ — A3', '16', 'A3', 'ISIRI 3132', Decimal('1.580'), 279000),
        ('فولاد کاوه', 'سایز ۲۰ — A4', '20', 'A4', 'ISIRI 3132', Decimal('2.470'), 291000),
    ]),
    ('beam-ipe', 'تیرآهن IPE', 'تیرآهن استاندارد اروپایی برای اسکلت فلزی', 'kg', [
        ('ذوب‌آهن اصفهان', 'IPE 14 — شاخه ۱۲ متری', '14', 'ST37', 'DIN 1025', Decimal('12.900'), 312000),
        ('ذوب‌آهن اصفهان', 'IPE 16 — شاخه ۱۲ متری', '16', 'ST37', 'DIN 1025', Decimal('15.800'), 309000),
        ('فولاد ظفر بناب', 'IPE 18 — شاخه ۱۲ متری', '18', 'ST37', 'DIN 1025', Decimal('18.800'), 305500),
    ]),
    ('sheet-black', 'ورق سیاه', 'ورق گرم ST37 برای مصارف سازه‌ای و صنعتی', 'kg', [
        ('فولاد مبارکه', 'ضخامت ۱۰ — عرض ۱۵۰۰', '10mm', 'ST37', 'DIN EN 10025', None, 338000),
        ('فولاد مبارکه', 'ضخامت ۱۵ — عرض ۲۰۰۰', '15mm', 'ST52', 'DIN EN 10025', None, 352000),
    ]),
    ('pipe-industrial', 'لوله صنعتی', 'لوله درزدار صنعتی برای سازه و انتقال سیالات', 'kg', [
        ('لوله و پروفیل سپاهان', '۲ اینچ — ضخامت ۳', '2"', 'ST37', 'API 5L', Decimal('25.000'), 362000),
        ('لوله و پروفیل سپاهان', '۴ اینچ — ضخامت ۴', '4"', 'ST37', 'API 5L', Decimal('62.000'), 358000),
    ]),
    ('box-industrial', 'قوطی صنعتی', 'قوطی مربع و مستطیل برای سازه‌های سبک', 'kg', [
        ('فولاد امین', '۴۰×۴۰ — ضخامت ۲', '40x40', 'ST37', 'DIN 59410', Decimal('14.500'), 368000),
        ('فولاد امین', '۸۰×۸۰ — ضخامت ۳', '80x80', 'ST37', 'DIN 59410', Decimal('43.000'), 361000),
    ]),
    ('angle', 'نبشی', 'نبشی بال‌مساوی نورد گرم', 'kg', [
        ('فولاد ظفر بناب', 'نبشی ۵ — ضخامت ۵', '50', 'ST37', 'DIN 1028', Decimal('22.600'), 301000),
    ]),
    ('wire-black', 'سیم مفتولی سیاه', 'سیم آرماتوربندی', 'kg', [
        ('فولاد کاوه', 'قطر ۱.۵ میلی‌متر', '1.5mm', '', '', None, 395000),
    ]),
    ('billet-steel', 'شمش فولادی', 'شمش ۱۵۰ برای تولید مقاطع طویل', 'ton', [
        ('فولاد خوزستان', 'شمش ۱۵۰ — 5SP', '150', '5SP', '', None, 245000000),
    ]),
]


class Command(BaseCommand):
    help = 'Create or purge clearly-labelled demo data (DEBUG only) for previewing the design.'

    def add_arguments(self, parser):
        parser.add_argument('--purge', action='store_true', help='Remove demo products and their records.')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('seed_demo فقط در محیط توسعه (DEBUG=1) اجرا می‌شود.')
        if options['purge']:
            self._purge()
            return
        with transaction.atomic():
            self._seed()
        call_command('process_price_events', limit=200, verbosity=0)
        self.stdout.write(self.style.SUCCESS('دادهٔ نمایشی ساخته شد. برای حذف: manage.py seed_demo --purge'))

    def _seed(self):
        User = get_user_model()
        operator, _ = User.objects.get_or_create(username='demo-price-operator', defaults={'is_staff': False})
        location, _ = InventoryLocation.objects.get_or_create(name='انبار نمایشی اصفهان', defaults={'city': 'اصفهان'})
        now = timezone.now()
        for index, (category_slug, product_name, summary, unit, variants) in enumerate(CATALOG):
            category = Category.objects.filter(slug=category_slug).first()
            if category is None:
                continue
            product, _ = Product.objects.get_or_create(
                slug=f'{DEMO_PREFIX}{category_slug}',
                defaults={
                    'category': category, 'name': product_name, 'summary': summary,
                    'description': f'{product_name} یکی از پرمصرف‌ترین مقاطع فولادی است. این متن و قیمت‌ها نمایشی هستند و فقط برای بازبینی طراحی ساخته شده‌اند.',
                },
            )
            for v_index, (maker, name, size, grade, standard, weight, amount) in enumerate(variants):
                manufacturer, _ = Manufacturer.objects.get_or_create(
                    name=maker, defaults={'slug': f'{DEMO_PREFIX}{index}-{v_index}-{abs(hash(maker)) % 10000}'},
                )
                variant, created = ProductVariant.objects.get_or_create(
                    sku=f'DEMO-{index:02d}{v_index:02d}',
                    defaults={
                        'product': product, 'manufacturer': manufacturer, 'name': name, 'size': size,
                        'grade': grade, 'standard': standard, 'unit': unit, 'weight_per_unit_kg': weight,
                        'sort_order': v_index,
                    },
                )
                if not created:
                    continue
                basis_label = 'کیلوگرم' if unit == 'kg' else 'تن'
                for days_ago, factor in ((3, Decimal('0.97') if v_index % 2 else Decimal('1.02')), (0, Decimal('1'))):
                    observation = PriceObservation.objects.create(
                        variant=variant, amount=(Decimal(amount) * factor).quantize(Decimal('1000')),
                        currency='IRR', unit_label=basis_label, price_basis=unit,
                        delivery_location='درب کارخانه' if v_index % 2 else 'انبار اصفهان',
                        source=DEMO_SOURCE, is_available=True, tax_included=False,
                        observed_at=now - timedelta(days=days_ago, hours=v_index),
                        valid_until=now + timedelta(days=2) if days_ago == 0 else now + timedelta(hours=1),
                        created_by=operator,
                    )
                    observation.approve(operator)
                stock = StockObservation.objects.create(
                    variant=variant, location=location, quantity=Decimal(40 + v_index * 15),
                    unit='ton', is_available=True, source=DEMO_SOURCE,
                    observed_at=now - timedelta(hours=2), valid_until=now + timedelta(days=1), created_by=operator,
                )
                stock.approve(operator)

        Article.objects.get_or_create(
            slug=f'{DEMO_PREFIX}rebar-weight-guide',
            defaults={
                'title': 'راهنمای انتخاب سایز میلگرد و محاسبهٔ وزن (نمایشی)',
                'excerpt': 'چطور سایز، گرید و وزن میلگرد را برای پروژه انتخاب کنیم؛ نمونهٔ نمایشی برای بازبینی طراحی مجله.',
                'body': 'این مقاله نمایشی است.\n\nوزن هر متر میلگرد از رابطهٔ قطر² × ۰٫۰۰۶۱۶۵ به دست می‌آید.',
                'category': 'راهنمای خرید', 'author_name': 'تحریریهٔ آریا',
                'status': Article.Status.PUBLISHED, 'published_at': now - timedelta(days=1),
            },
        )

    def _purge(self):
        with transaction.atomic():
            variants = ProductVariant.objects.filter(sku__startswith='DEMO-')
            MarketNews.objects.filter(variant__in=variants).delete()
            from pricing.models import PriceObservationTask, PriceReviewEvent

            observations = PriceObservation.objects.filter(variant__in=variants)
            PriceObservationTask.objects.filter(observation__in=observations).delete()
            PriceReviewEvent.objects.filter(observation__in=observations).delete()
            observations.delete()
            StockObservation.objects.filter(variant__in=variants).delete()
            variants.delete()
            Product.objects.filter(slug__startswith=DEMO_PREFIX).delete()
            Manufacturer.objects.filter(slug__startswith=DEMO_PREFIX, variants__isnull=True).delete()
            Article.objects.filter(slug__startswith=DEMO_PREFIX).delete()
        self.stdout.write(self.style.SUCCESS('دادهٔ نمایشی حذف شد.'))
