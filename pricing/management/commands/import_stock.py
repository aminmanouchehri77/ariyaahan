import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from catalog.models import ProductVariant
from pricing.models import InventoryLocation, PriceObservation, StockObservation


TRUE_VALUES = {'1', 'true', 'yes', 'y', 'بله', 'موجود'}
FALSE_VALUES = {'0', 'false', 'no', 'n', 'خیر', 'ناموجود'}
MAX_QUANTITY = Decimal('99999999999.999')


def parse_bool(value):
    value = (value or '').strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ValueError('is_available باید بله/خیر، yes/no یا 1/0 باشد.')


def parse_datetime(value, *, required=False):
    value = (value or '').strip()
    if not value:
        if required:
            raise ValueError('valid_until لازم است تا اعتبار موجودی مشخص باشد.')
        return None
    parsed = parse_datetime(value)
    if parsed is None or timezone.is_naive(parsed):
        raise ValueError('تاریخ باید ISO 8601 همراه منطقهٔ زمانی باشد؛ نمونه: 2026-11-05T14:30:00+03:30')
    return parsed


class Command(BaseCommand):
    help = 'اعتبارسنجی یا ورود CSV موجودی‌ها به شکل ثبت‌های در انتظار تأیید.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=Path)
        parser.add_argument(
            '--commit', action='store_true',
            help='پس از اعتبارسنجی همهٔ ردیف‌ها، ثبت‌های موجودی را در پایگاه داده ایجاد کن.',
        )

    def handle(self, *args, csv_path, commit=False, **options):
        if not csv_path.is_file():
            raise CommandError(f'فایل پیدا نشد: {csv_path}')

        required = {'variant_sku', 'location_name', 'quantity', 'unit', 'is_available', 'valid_until'}
        rows = []
        errors = []
        try:
            with csv_path.open('r', encoding='utf-8-sig', newline='') as source:
                reader = csv.DictReader(source)
                if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                    missing = ', '.join(sorted(required - set(reader.fieldnames or [])))
                    raise CommandError(f'ستون‌های لازم در CSV نیست: {missing}')
                for line_number, raw in enumerate(reader, start=2):
                    try:
                        rows.append((line_number, self._parse_row(raw)))
                    except (
                        ValueError, InvalidOperation, ProductVariant.DoesNotExist,
                        InventoryLocation.DoesNotExist,
                    ) as error:
                        errors.append(f'ردیف {line_number}: {error}')
        except UnicodeDecodeError as error:
            raise CommandError('فایل CSV باید با UTF-8 ذخیره شده باشد.') from error

        if errors:
            raise CommandError('ورود لغو شد؛ هیچ ردیفی ثبت نشد.\n' + '\n'.join(errors))
        if not rows:
            raise CommandError('فایل CSV ردیفی برای ورود ندارد.')

        if not commit:
            self.stdout.write(self.style.WARNING(
                f'{len(rows)} ردیف معتبر است. برای ثبت آن‌ها دوباره با گزینهٔ --commit اجرا کنید.'
            ))
            return

        with transaction.atomic():
            for _, row in rows:
                StockObservation.objects.create(**row)
        self.stdout.write(self.style.SUCCESS(
            f'{len(rows)} ثبت موجودی ساخته شد؛ وضعیت همه «در انتظار تأیید» است.'
        ))

    def _parse_row(self, raw):
        sku = (raw.get('variant_sku') or '').strip()
        if not sku:
            raise ValueError('variant_sku خالی است.')
        try:
            variant = ProductVariant.objects.get(sku=sku)
        except ProductVariant.DoesNotExist as error:
            raise ValueError(f'گونه‌ای با کد {sku} پیدا نشد.') from error

        location_name = (raw.get('location_name') or '').strip()
        if not location_name:
            raise ValueError('location_name خالی است.')
        try:
            location = InventoryLocation.objects.get(name=location_name, is_active=True)
        except InventoryLocation.DoesNotExist as error:
            raise ValueError(f'محل فعال «{location_name}» در پنل مدیریت ثبت نشده است.') from error

        quantity = Decimal((raw.get('quantity') or '').strip())
        if (
            not quantity.is_finite() or quantity < 0 or quantity > MAX_QUANTITY
            or quantity != quantity.quantize(Decimal('0.001'))
        ):
            raise ValueError('quantity باید عددی بین صفر و ۹۹۹۹۹۹۹۹۹۹۹٫۹۹۹ با حداکثر سه رقم اعشار باشد.')

        unit = (raw.get('unit') or '').strip().lower()
        if unit not in PriceObservation.PriceBasis.values:
            raise ValueError('unit باید kg، ton، piece، bundle، sheet یا meter باشد.')

        observed_at = parse_datetime(raw.get('observed_at')) or timezone.now()
        valid_until = parse_datetime(raw.get('valid_until'), required=True)
        if valid_until <= observed_at:
            raise ValueError('valid_until باید پس از observed_at باشد.')

        return {
            'variant': variant,
            'location': location,
            'quantity': quantity,
            'unit': unit,
            'is_available': parse_bool(raw.get('is_available')),
            'source': (raw.get('source') or '').strip()[:160],
            'observed_at': observed_at,
            'valid_until': valid_until,
            'status': StockObservation.Status.PENDING,
        }
