from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import json_script
from django.utils.safestring import mark_safe
from django.utils import timezone

register = template.Library()
PERSIAN_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
CURRENCY_LABELS = {
    'IRR': 'ریال',
    'IRT': 'تومان',
    'USD': 'دلار',
}


@register.filter
def fa_digits(value):
    return str(value).translate(PERSIAN_DIGITS)


@register.filter
def money(value, currency='IRR'):
    if value in (None, ''):
        return 'استعلام'
    try:
        amount = int(Decimal(value))
    except (InvalidOperation, TypeError, ValueError):
        return 'استعلام'
    formatted = f'{amount:,}'.replace(',', '٬').translate(PERSIAN_DIGITS)
    return f'{formatted} {CURRENCY_LABELS.get(currency, currency)}'


@register.filter
def jalali_datetime(value):
    if not value:
        return ''
    import jdatetime

    local_value = timezone.localtime(value) if timezone.is_aware(value) else value
    jalali_value = jdatetime.datetime.fromgregorian(datetime=local_value)
    return jalali_value.strftime('%Y/%m/%d %H:%M').translate(PERSIAN_DIGITS)


@register.filter
def json_ld(value):
    """Render safely escaped JSON using the MIME type read by search engines."""
    return mark_safe(
        json_script(value, 'product-jsonld').replace(
            'type="application/json"',
            'type="application/ld+json"',
        )
    )
