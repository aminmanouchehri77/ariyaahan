import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from catalog.csv_import import check_file, clean_row, iter_rows
from catalog.models import ProductVariant
from pricing.models import PriceObservation


TRUE_VALUES = {'1', 'true', 'yes', 'y', 'بله', 'موجود'}
FALSE_VALUES = {'0', 'false', 'no', 'n', 'خیر', 'ناموجود'}
MAX_AMOUNT = Decimal(10) ** 18


def parse_bool(value, *, default=None):
    value = (value or '').strip().lower()
    if not value:
        return default
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ValueError('مقدار بولی باید یکی از بله/خیر، yes/no یا 1/0 باشد.')


def parse_optional_datetime(value):
    value = (value or '').strip()
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError('تاریخ باید ISO 8601 باشد؛ نمونه: 2026-11-04T12:30:00+03:30')
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


class Command(BaseCommand):
    help = 'اعتبارسنجی یا ورود CSV قیمت‌ها به شکل ثبت‌های در انتظار تأیید.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=Path)
        parser.add_argument(
            '--commit', action='store_true',
            help='پس از اعتبارسنجی همهٔ ردیف‌ها، ثبت‌های قیمت را در پایگاه داده ایجاد کن.',
        )

    def handle(self, *args, csv_path, commit=False, **options):
        check_file(csv_path)

        required = {'variant_sku', 'amount', 'currency', 'price_basis'}
        rows = []
        errors = []
        try:
            with csv_path.open('r', encoding='utf-8-sig', newline='') as source:
                reader = csv.DictReader(source)
                if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                    missing = ', '.join(sorted(required - set(reader.fieldnames or [])))
                    raise CommandError(f'ستون‌های لازم در CSV نیست: {missing}')
                for line_number, raw in iter_rows(reader):
                    try:
                        row = self._parse_row(clean_row(raw))
                        rows.append((line_number, row))
                    except (ValueError, InvalidOperation, ProductVariant.DoesNotExist) as error:
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

        from django.db import transaction

        with transaction.atomic():
            for _, row in rows:
                PriceObservation.objects.create(**row)
        self.stdout.write(self.style.SUCCESS(
            f'{len(rows)} ثبت قیمت ساخته شد؛ وضعیت همه «در انتظار تأیید» است.'
        ))

    def _parse_row(self, raw):
        sku = (raw.get('variant_sku') or '').strip()
        if not sku:
            raise ValueError('variant_sku خالی است.')
        variant = ProductVariant.objects.select_related('product').get(sku=sku)

        amount = Decimal((raw.get('amount') or '').strip())
        if not amount.is_finite() or amount < 1 or amount >= MAX_AMOUNT or amount != amount.quantize(Decimal('1')):
            raise ValueError('amount باید عدد صحیح مثبت باشد.')
        currency = (raw.get('currency') or '').strip().upper()
        if currency not in PriceObservation.Currency.values:
            raise ValueError('currency باید IRR، IRT یا USD باشد.')
        basis = (raw.get('price_basis') or '').strip().lower()
        if basis not in PriceObservation.PriceBasis.values:
            raise ValueError('price_basis باید kg، ton، piece، bundle، sheet یا meter باشد.')

        observed_at = parse_optional_datetime(raw.get('observed_at')) or timezone.now()
        valid_until = parse_optional_datetime(raw.get('valid_until'))
        if valid_until is not None and valid_until <= observed_at:
            raise ValueError('valid_until باید پس از observed_at باشد.')
        return {
            'variant': variant,
            'amount': amount,
            'currency': currency,
            'unit_label': (raw.get('unit_label') or '').strip()[:40],
            'price_basis': basis,
            'delivery_location': (raw.get('delivery_location') or '').strip()[:140],
            'source': (raw.get('source') or '').strip()[:160],
            'is_available': parse_bool(raw.get('is_available'), default=True),
            'tax_included': parse_bool(raw.get('tax_included'), default=None),
            'observed_at': observed_at,
            'valid_until': valid_until,
            'status': PriceObservation.Status.PENDING,
        }
