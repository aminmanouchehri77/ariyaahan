from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import json_script
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.utils.dateparse import parse_datetime

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

    if isinstance(value, str):
        value = parse_datetime(value)
        if value is None:
            return ''
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


# ---------------------------------------------------------------------------
# Design-system helpers
# ---------------------------------------------------------------------------

from django.core.cache import cache  # noqa: E402
from django.templatetags.static import static  # noqa: E402
from django.utils.html import format_html  # noqa: E402

ICON_SPRITE = 'core/brand/icons.svg'
STEEL_IMAGES = {
    'rebar', 'beam', 'steel-sheet', 'pipe', 'profiles', 'angles-channels',
    'wire-products', 'billets', 'raw-materials', 'ferroalloy',
}
STEEL_IMAGE_ALIASES = {
    'mesh': 'wire-products',
}


@register.simple_tag
def icon(name, extra_class=''):
    """Inline reference to an icon in the shared SVG sprite (decorative)."""
    return format_html(
        '<svg class="i {}" aria-hidden="true" focusable="false"><use href="{}#i-{}"></use></svg>',
        extra_class, static(ICON_SPRITE), name,
    )


def _category_roots():
    roots = cache.get('ariaa:category-roots')
    if roots is None:
        from catalog.models import Category

        rows = {pk: (slug, parent_id) for pk, slug, parent_id in Category.objects.values_list('pk', 'slug', 'parent_id')}
        roots = {}
        for pk in rows:
            cursor, guard = pk, 0
            while rows.get(cursor) and rows[cursor][1] and guard < 10:
                cursor, guard = rows[cursor][1], guard + 1
            roots[pk] = rows[cursor][0] if cursor in rows else ''
        cache.set('ariaa:category-roots', roots, 300)
    return roots


@register.simple_tag
def steel_image(obj=None, size=''):
    """Return the rendered product image URL for a category/product/variant."""
    slug = ''
    category_id = None
    if obj is not None:
        if hasattr(obj, 'product'):
            obj = obj.product
        if hasattr(obj, 'category_id'):
            category_id = obj.category_id
        elif hasattr(obj, 'parent_id'):
            category_id = obj.pk
            slug = obj.slug
        elif isinstance(obj, str):
            slug = obj
    if category_id is not None:
        slug = _category_roots().get(category_id, slug)
    slug = STEEL_IMAGE_ALIASES.get(slug, slug)
    if slug not in STEEL_IMAGES:
        slug = 'beam'
    suffix = '-sm' if size == 'sm' else ''
    return static(f'core/img/products/{slug}{suffix}.webp')


@register.filter
def jalali_date(value):
    if not value:
        return ''
    import jdatetime

    local_value = timezone.localtime(value) if timezone.is_aware(value) else value
    return jdatetime.date.fromgregorian(date=local_value.date()).strftime('%Y/%m/%d').translate(PERSIAN_DIGITS)


@register.filter
def jalali_long(value):
    """e.g. «۱۷ آبان ۱۴۰۵»."""
    if not value:
        return ''
    import jdatetime

    months = ('فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند')
    local_value = timezone.localtime(value) if timezone.is_aware(value) else value
    j = jdatetime.date.fromgregorian(date=local_value.date())
    return f'{j.day} {months[j.month - 1]} {j.year}'.translate(PERSIAN_DIGITS)


@register.filter
def percent_fa(value):
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return ''
    sign = '+' if number > 0 else ('−' if number < 0 else '')
    return f'{sign}{abs(number):.2f}٪'.translate(PERSIAN_DIGITS).replace('.', '٫')
