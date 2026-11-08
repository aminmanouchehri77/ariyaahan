"""Shared guards for the CSV importers (catalogue, prices, stock)."""

import csv

from django.core.management.base import CommandError

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20000


def check_file(csv_path):
    if not csv_path.is_file():
        raise CommandError(f'فایل پیدا نشد: {csv_path}')
    if csv_path.stat().st_size > MAX_FILE_BYTES:
        raise CommandError(f'حجم فایل CSV بیش از {MAX_FILE_BYTES // (1024 * 1024)} مگابایت است؛ آن را چند بخش کنید.')


def iter_rows(reader):
    """Yield (line_number, raw_row) and stop with CommandError on malformed CSV."""
    try:
        for index, raw in enumerate(reader, start=2):
            if index - 1 > MAX_ROWS:
                raise CommandError(f'تعداد ردیف‌ها بیش از {MAX_ROWS} است؛ فایل را چند بخش کنید.')
            yield reader.line_num, raw
    except csv.Error as error:
        raise CommandError(f'ساختار CSV نامعتبر است (ردیف {reader.line_num}): {error}') from error


def clean_row(raw):
    """Strip values; reject rows with extra cells or NUL characters."""
    if None in raw:
        raise ValueError('تعداد خانه‌های این ردیف بیش از ستون‌های سرستون است.')
    row = {key: (value or '').strip() for key, value in raw.items()}
    if any('\x00' in value for value in row.values()):
        raise ValueError('ردیف شامل نویسهٔ نامعتبر (NUL) است.')
    return row
