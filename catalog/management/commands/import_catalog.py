import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_slug

from catalog.csv_import import check_file, clean_row, iter_rows
from catalog.models import Category, Manufacturer, Product, ProductVariant


REQUIRED = {
    'category_slug', 'product_slug', 'product_name', 'variant_sku',
    'variant_name', 'unit',
}
MAX_LENGTHS = {
    'product_slug': (Product, 'slug'),
    'product_name': (Product, 'name'),
    'variant_sku': (ProductVariant, 'sku'),
    'variant_name': (ProductVariant, 'name'),
    'size': (ProductVariant, 'size'),
    'grade': (ProductVariant, 'grade'),
    'standard': (ProductVariant, 'standard'),
    'dimensions': (ProductVariant, 'dimensions'),
    'manufacturer_slug': (Manufacturer, 'slug'),
    'manufacturer_name': (Manufacturer, 'name'),
}
MAX_WEIGHT = Decimal('1000000000')


class Command(BaseCommand):
    help = 'اعتبارسنجی یا ورود CSV کاتالوگ؛ ردیف‌های موجود را بازنویسی نمی‌کند.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=Path)
        parser.add_argument('--commit', action='store_true', help='پس از اعتبارسنجی کامل، ردیف‌های جدید را ثبت کن.')

    def handle(self, *args, csv_path, commit=False, **options):
        check_file(csv_path)
        try:
            with csv_path.open('r', encoding='utf-8-sig', newline='') as source:
                reader = csv.DictReader(source)
                if not reader.fieldnames or not REQUIRED.issubset(set(reader.fieldnames)):
                    missing = ', '.join(sorted(REQUIRED - set(reader.fieldnames or [])))
                    raise CommandError(f'ستون‌های لازم در CSV نیست: {missing}')
                records, errors = self._read_rows(reader)
        except UnicodeDecodeError as error:
            raise CommandError('فایل CSV باید با UTF-8 ذخیره شده باشد.') from error

        if errors:
            raise CommandError('ورود لغو شد؛ هیچ ردیفی ثبت نشد.\n' + '\n'.join(errors))
        if not records:
            raise CommandError('فایل CSV ردیفی برای ورود ندارد.')

        self._validate_existing(records)
        if not commit:
            self.stdout.write(self.style.WARNING(
                f'{len(records)} گونه در {len({r["product_slug"] for r in records})} محصول معتبر است. '
                'برای ثبت دوباره با --commit اجرا کنید.'
            ))
            return

        from django.db import transaction

        with transaction.atomic():
            manufacturer_cache = {}
            product_cache = {}
            for row in records:
                manufacturer = None
                if row['manufacturer_slug']:
                    key = row['manufacturer_slug']
                    manufacturer = manufacturer_cache.get(key)
                    if manufacturer is None:
                        manufacturer, created = Manufacturer.objects.get_or_create(
                            slug=key, defaults={'name': row['manufacturer_name']},
                        )
                        if not created and manufacturer.name != row['manufacturer_name']:
                            raise CommandError(f'نام کارخانهٔ {key} با رکورد موجود سازگار نیست.')
                        manufacturer_cache[key] = manufacturer

                category = Category.objects.get(slug=row['category_slug'])
                product = product_cache.get(row['product_slug'])
                if product is None:
                    product = Product.objects.create(
                        category=category,
                        name=row['product_name'],
                        slug=row['product_slug'],
                        summary=row['product_summary'],
                        description=row['product_description'],
                    )
                    product_cache[row['product_slug']] = product
                ProductVariant.objects.create(
                    product=product,
                    manufacturer=manufacturer,
                    sku=row['variant_sku'],
                    name=row['variant_name'],
                    size=row['size'],
                    grade=row['grade'],
                    standard=row['standard'],
                    dimensions=row['dimensions'],
                    unit=row['unit'],
                    weight_per_unit_kg=row['weight_per_unit_kg'],
                )
        self.stdout.write(self.style.SUCCESS(f'{len(records)} گونهٔ محصول ثبت شد.'))

    def _read_rows(self, reader):
        records = []
        errors = []
        seen_skus = set()
        products = {}
        valid_units = set(ProductVariant.Unit.values)

        for line_number, raw in iter_rows(reader):
            try:
                row = clean_row(raw)
                for key in REQUIRED:
                    if not row.get(key):
                        raise ValueError(f'{key} خالی است.')
                if row['unit'] not in valid_units:
                    raise ValueError('unit باید kg، ton، piece، bundle، sheet یا meter باشد.')
                if row['variant_sku'] in seen_skus:
                    raise ValueError(f'SKU تکراری در فایل: {row["variant_sku"]}')
                seen_skus.add(row['variant_sku'])

                for key in ('product_slug', 'manufacturer_slug'):
                    if row.get(key):
                        try:
                            validate_slug(row[key])
                        except ValidationError as error:
                            raise ValueError(f'{key} باید فقط حروف لاتین، عدد، - یا _ داشته باشد.') from error
                for key, (model, field) in MAX_LENGTHS.items():
                    limit = model._meta.get_field(field).max_length
                    if len(row.get(key, '')) > limit:
                        raise ValueError(f'{key} بیش از {limit} نویسه است.')

                category = Category.objects.get(slug=row['category_slug'])
                if not category.is_active:
                    raise ValueError('دسته‌بندی غیرفعال است.')
                product_info = (
                    row['category_slug'], row['product_name'], row.get('product_summary', ''),
                    row.get('product_description', ''),
                )
                previous = products.get(row['product_slug'])
                if previous and previous != product_info:
                    raise ValueError('مشخصات تکرارشدهٔ محصول در CSV یکسان نیست.')
                products[row['product_slug']] = product_info

                manufacturer_slug = row.get('manufacturer_slug', '')
                manufacturer_name = row.get('manufacturer_name', '')
                if bool(manufacturer_slug) != bool(manufacturer_name):
                    raise ValueError('manufacturer_slug و manufacturer_name باید هر دو پر یا هر دو خالی باشند.')
                weight = None
                if row.get('weight_per_unit_kg'):
                    weight = Decimal(row['weight_per_unit_kg'])
                    if (
                        not weight.is_finite() or weight <= 0 or weight >= MAX_WEIGHT
                        or weight != weight.quantize(Decimal('0.001'))
                    ):
                        raise ValueError('weight_per_unit_kg باید عدد مثبت (حداکثر سه رقم اعشار) باشد.')

                records.append({
                    'line_number': line_number,
                    'category_slug': row['category_slug'],
                    'product_slug': row['product_slug'],
                    'product_name': row['product_name'],
                    'product_summary': row.get('product_summary', '')[:300],
                    'product_description': row.get('product_description', ''),
                    'variant_sku': row['variant_sku'],
                    'variant_name': row['variant_name'],
                    'size': row.get('size', ''),
                    'grade': row.get('grade', ''),
                    'standard': row.get('standard', ''),
                    'dimensions': row.get('dimensions', ''),
                    'unit': row['unit'],
                    'weight_per_unit_kg': weight,
                    'manufacturer_slug': manufacturer_slug,
                    'manufacturer_name': manufacturer_name,
                })
            except (Category.DoesNotExist, ValueError, InvalidOperation) as error:
                errors.append(f'ردیف {line_number}: {error}')
        return records, errors

    def _validate_existing(self, records):
        product_slugs = {row['product_slug'] for row in records}
        skus = {row['variant_sku'] for row in records}
        manufacturer_slugs = {row['manufacturer_slug'] for row in records if row['manufacturer_slug']}
        conflicts = []
        existing_products = set(Product.objects.filter(slug__in=product_slugs).values_list('slug', flat=True))
        existing_skus = set(ProductVariant.objects.filter(sku__in=skus).values_list('sku', flat=True))
        if existing_products:
            conflicts.append('شناسهٔ محصول از قبل وجود دارد: ' + ', '.join(sorted(existing_products)))
        if existing_skus:
            conflicts.append('SKU از قبل وجود دارد: ' + ', '.join(sorted(existing_skus)))
        existing_manufacturers = dict(Manufacturer.objects.filter(slug__in=manufacturer_slugs).values_list('slug', 'name'))
        for row in records:
            slug = row['manufacturer_slug']
            if slug in existing_manufacturers and existing_manufacturers[slug] != row['manufacturer_name']:
                conflicts.append(f'نام کارخانهٔ {slug} با رکورد موجود ناسازگار است.')
        if conflicts:
            raise CommandError('ورود لغو شد؛\n' + '\n'.join(dict.fromkeys(conflicts)))
