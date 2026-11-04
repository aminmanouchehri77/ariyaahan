from django.db.models import OuterRef, Subquery
from django.utils import timezone

from .models import PriceObservation


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
    from .models import StockObservation

    latest = StockObservation.objects.filter(
        variant_id=OuterRef('pk'),
        status=StockObservation.Status.APPROVED,
    ).order_by('-observed_at', '-pk')
    return variants.annotate(
        latest_stock_quantity=Subquery(latest.values('quantity')[:1]),
        latest_stock_unit=Subquery(latest.values('unit')[:1]),
        latest_stock_available=Subquery(latest.values('is_available')[:1]),
        latest_stock_observed_at=Subquery(latest.values('observed_at')[:1]),
        latest_stock_valid_until=Subquery(latest.values('valid_until')[:1]),
        latest_stock_location=Subquery(latest.values('location__name')[:1]),
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
