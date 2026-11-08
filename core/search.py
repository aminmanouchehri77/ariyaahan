"""Persian-aware product search.

* Normalises Arabic/Persian letter variants, diacritics, ZWNJ and digits.
* Splits the query into tokens; every token must match some searchable field
  (so «آهن آلات», «آهن‌آلات» and «میلگرد ۱۲ ذوب» all work).
* Searches with both Latin and Persian digits, because catalogue data may use
  either.
* When nothing matches, suggests the closest known product/category name
  («منظورتان … بود؟») using difflib, which tolerates typos.
"""

import difflib
import re
from functools import reduce
from operator import and_, or_

from django.core.cache import cache
from django.db.models import Q

ARABIC_TO_PERSIAN = str.maketrans({
    'ي': 'ی', 'ى': 'ی', 'ئ': 'ی', 'ك': 'ک', 'ة': 'ه', 'ۀ': 'ه', 'أ': 'ا', 'إ': 'ا', 'ٱ': 'ا', 'ؤ': 'و',
})
TO_LATIN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
TO_PERSIAN_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
DIACRITICS = re.compile(r'[ً-ٰٟـ]')
CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f]')
STOP_WORDS = {'قیمت', 'خرید', 'فروش', 'روز', 'امروز', 'آهن', 'آلات', 'آهن‌آلات', 'و', 'با', 'در', 'از'}

PRODUCT_FIELDS = (
    'name', 'summary', 'category__name', 'category__parent__name',
    'variants__name', 'variants__size', 'variants__grade', 'variants__standard',
    'variants__manufacturer__name', 'variants__sku',
)


def normalize_fa(text):
    text = str(text or '').translate(ARABIC_TO_PERSIAN).translate(TO_LATIN_DIGITS)
    text = CONTROL_CHARS.sub(' ', DIACRITICS.sub('', text))
    text = text.replace('‌', ' ').replace('‏', '').replace('‎', '')
    text = re.sub(r'[\s\-_/،,]+', ' ', text)
    return text.strip().lower()


def tokens(query):
    parts = [part for part in normalize_fa(query).split(' ') if part]
    meaningful = [part for part in parts if part not in STOP_WORDS]
    return (meaningful or parts)[:6]


def _token_q(token, fields):
    forms = {token, token.translate(TO_PERSIAN_DIGITS)}
    # Data may store the token with a ZWNJ or a plain space inside words.
    return reduce(or_, (_field_q(field, form) for field in fields for form in forms))


def _field_q(field, form):
    # Inactive variants must never make their product discoverable.
    if field.startswith('variants__'):
        return Q(**{f'{field}__icontains': form, 'variants__is_active': True})
    return Q(**{f'{field}__icontains': form})


def match_q(query, fields=PRODUCT_FIELDS):
    parts = tokens(query)
    if not parts:
        return None
    return reduce(and_, (_token_q(part, fields) for part in parts))


def _vocabulary():
    words = cache.get('ariaa:search-vocabulary')
    if words is None:
        from catalog.models import Category, Manufacturer, Product

        names = list(Product.objects.filter(is_active=True, category__is_active=True).values_list('name', flat=True))
        names += list(Category.objects.filter(is_active=True).values_list('name', flat=True))
        names += list(Manufacturer.objects.filter(is_active=True).values_list('name', flat=True))
        words = sorted({normalize_fa(name) for name in names if name})
        cache.set('ariaa:search-vocabulary', words, 600)
    return words


def did_you_mean(query):
    """Return the closest catalogue phrase for a query that found nothing."""
    normalized = normalize_fa(query)
    if len(normalized) < 2:
        return ''
    vocabulary = _vocabulary()
    match = difflib.get_close_matches(normalized, vocabulary, n=1, cutoff=0.6)
    if match:
        return match[0]
    # Fall back to per-word correction («میلگرت ۱۲» → «میلگرد ۱۲»).
    words = {word for phrase in vocabulary for word in phrase.split() if len(word) > 2}
    corrected, changed = [], False
    for part in normalized.split():
        if part.isdigit() or part in words:
            corrected.append(part)
            continue
        close = difflib.get_close_matches(part, words, n=1, cutoff=0.7)
        corrected.append(close[0] if close else part)
        changed = changed or bool(close)
    return ' '.join(corrected) if changed else ''
