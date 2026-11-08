"""Shared shipping-rate lookup used by the calculator and the cart."""

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from .models import ShippingRate

RIAL_FACTORS = {'IRR': Decimal('1'), 'IRT': Decimal('10')}


def active_routes():
    now = timezone.now()
    rates = ShippingRate.objects.filter(is_active=True, valid_until__gt=now)
    origins = sorted(set(rates.values_list('origin_city', flat=True)))
    destinations = sorted(set(rates.values_list('destination_city', flat=True)))
    return origins, destinations


def find_rate(origin, destination, weight_tonnes):
    return ShippingRate.objects.filter(
        origin_city=origin,
        destination_city=destination,
        is_active=True,
        valid_until__gt=timezone.now(),
        minimum_tonnes__lte=weight_tonnes,
    ).filter(
        Q(maximum_tonnes__isnull=True) | Q(maximum_tonnes__gte=weight_tonnes)
    ).order_by('-minimum_tonnes', 'per_tonne').first()


def estimate(origin, destination, weight_tonnes):
    rate = find_rate(origin, destination, weight_tonnes)
    if rate is None:
        return None
    amount = (rate.base_fee + rate.per_tonne * weight_tonnes).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return {'rate': rate, 'amount': amount, 'currency': rate.currency, 'weight_tonnes': weight_tonnes}


def combined_total(goods_totals, shipping):
    """Sum goods + shipping in Rial when every amount is IRR/IRT; else None."""
    if shipping is None or not goods_totals:
        return None
    total = Decimal('0')
    for currency, amount in goods_totals:
        if currency not in RIAL_FACTORS:
            return None
        total += amount * RIAL_FACTORS[currency]
    if shipping['currency'] not in RIAL_FACTORS:
        return None
    return total + shipping['amount'] * RIAL_FACTORS[shipping['currency']]
