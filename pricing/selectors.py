from decimal import Decimal

from django.db.models import OuterRef, Subquery
from django.utils import timezone

from .models import PriceObservation, StockObservation


def with_latest_price(queryset):
    """Annotate product variants with their newest price snapshot."""
    latest = PriceObservation.objects.filter(
        variant_id=OuterRef('pk'),
        status=PriceObservation.Status.APPROVED,
    ).order_by('-observed_at', '-pk')
    return queryset.annotate(
        latest_amount=Subquery(latest.values('amount')[:1]),
        latest_currency=Subquery(latest.values('currency')[:1]),
        latest_unit_label=Subquery(latest.values('unit_label')[:1]),
        latest_price_basis=Subquery(latest.values('price_basis')[:1]),
        latest_price_observation_id=Subquery(latest.values('pk')[:1]),
        latest_location=Subquery(latest.values('delivery_location')[:1]),
        latest_source=Subquery(latest.values('source')[:1]),
        latest_observed_at=Subquery(latest.values('observed_at')[:1]),
        latest_valid_until=Subquery(latest.values('valid_until')[:1]),
        latest_available=Subquery(latest.values('is_available')[:1]),
        latest_tax_included=Subquery(latest.values('tax_included')[:1]),
    )


def latest_stock_observations(variants):
    """Return each variant with its latest approved inventory snapshot."""
    latest = StockObservation.objects.filter(
        variant_id=OuterRef('pk'),
        status=StockObservation.Status.APPROVED,
    ).order_by('-observed_at', '-pk')
    return variants.annotate(
        latest_stock_observation_id=Subquery(latest.values('pk')[:1]),
        latest_stock_quantity=Subquery(latest.values('quantity')[:1]),
        latest_stock_unit=Subquery(latest.values('unit')[:1]),
        latest_stock_available=Subquery(latest.values('is_available')[:1]),
        latest_stock_observed_at=Subquery(latest.values('observed_at')[:1]),
        latest_stock_valid_until=Subquery(latest.values('valid_until')[:1]),
        latest_stock_location=Subquery(latest.values('location__name')[:1]),
        latest_stock_source=Subquery(latest.values('source')[:1]),
    )


def mark_price_state(variants):
    now = timezone.now()
    for variant in variants:
        variant.price_expired = bool(
            variant.latest_valid_until and variant.latest_valid_until <= now
        )
        variant.price_validity_unknown = bool(
            variant.latest_amount is not None and variant.latest_valid_until is None
        )
    return variants


def mark_stock_state(variants):
    now = timezone.now()
    unit_labels = dict(PriceObservation.PriceBasis.choices)
    for variant in variants:
        variant.stock_expired = bool(
            variant.latest_stock_valid_until and variant.latest_stock_valid_until <= now
        )
        variant.stock_validity_unknown = bool(
            variant.latest_stock_observation_id and not variant.latest_stock_valid_until
        )
        variant.latest_stock_unit_label = unit_labels.get(variant.latest_stock_unit, '')
        if not variant.latest_stock_observation_id:
            variant.stock_status = 'موجودی جداگانه ثبت نشده'
        elif variant.stock_expired:
            variant.stock_status = 'ثبت موجودی منقضی شده'
        elif variant.stock_validity_unknown:
            variant.stock_status = 'اعتبار موجودی نامشخص'
        elif variant.latest_stock_available and variant.latest_stock_quantity > 0:
            variant.stock_status = 'موجود'
        else:
            variant.stock_status = 'ناموجود'
    return variants


def attach_sparklines(variants, points=12):
    """Attach `variant.spark` (SVG polyline points) and `variant.spark_trend`.

    Uses one query for all variants; only approved prices with the same
    currency/basis as the latest one are plotted, so the line is comparable.
    """
    from collections import defaultdict

    ids = [variant.pk for variant in variants]
    if not ids:
        return variants
    rows = defaultdict(list)
    for variant_id, amount, currency, basis in PriceObservation.objects.filter(
        variant_id__in=ids, status=PriceObservation.Status.APPROVED,
    ).order_by('variant_id', '-observed_at', '-pk').values_list('variant_id', 'amount', 'currency', 'price_basis'):
        series = rows[variant_id]
        if len(series) >= points:
            continue
        if series and (series[0][1], series[0][2]) != (currency, basis):
            continue
        series.append((amount, currency, basis))
    for variant in variants:
        amounts = [row[0] for row in reversed(rows.get(variant.pk, []))]
        variant.spark = ''
        variant.spark_trend = ''
        if len(amounts) < 2:
            continue
        low, high = min(amounts), max(amounts)
        span = (high - low) or 1
        step = 100 / (len(amounts) - 1)
        variant.spark = ' '.join(
            f'{round(index * step, 1)},{round(28 - float((amount - low) / span) * 24, 1)}'
            for index, amount in enumerate(amounts)
        )
        variant.spark_trend = 'up' if amounts[-1] > amounts[-2] else ('down' if amounts[-1] < amounts[-2] else 'flat')
        variant.spark_change = ((amounts[-1] - amounts[-2]) * 100 / amounts[-2]).quantize(Decimal('0.01')) if amounts[-2] else None
    return variants


def mark_best_prices(variants):
    """Flag the cheapest currently-valid price for each size/unit group."""
    groups = {}
    for variant in variants:
        variant.is_best_price = False
        if (
            variant.latest_amount is None or not variant.latest_available
            or getattr(variant, 'price_expired', False) or getattr(variant, 'price_validity_unknown', False)
        ):
            continue
        key = ((variant.size or '').strip(), variant.latest_currency, variant.latest_price_basis, variant.product_id)
        groups.setdefault(key, []).append(variant)
    for members in groups.values():
        if len(members) < 2:
            continue
        best = min(members, key=lambda item: item.latest_amount)
        best.is_best_price = True
    return variants


def attach_unit_prices(variants):
    """Approximate price per piece for kg/ton-priced variants with a known unit weight."""
    for variant in variants:
        variant.piece_price = None
        weight = variant.weight_per_unit_kg
        if not weight or variant.latest_amount is None:
            continue
        if variant.latest_price_basis == 'kg':
            variant.piece_price = (variant.latest_amount * weight).quantize(Decimal('1'))
        elif variant.latest_price_basis == 'ton':
            variant.piece_price = (variant.latest_amount * weight / 1000).quantize(Decimal('1'))
    return variants
