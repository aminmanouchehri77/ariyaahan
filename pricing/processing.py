from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from accounts.price_alerts import notify_price_alerts
from catalog.models import ProductVariant
from content.models import MarketNews

from .models import PriceObservation


def _publish_market_news(observation):
    if (
        observation.status != PriceObservation.Status.APPROVED
        or not observation.is_available
        or not observation.valid_until
        or observation.valid_until <= observation.observed_at
    ):
        return

    latest = PriceObservation.objects.filter(
        variant_id=observation.variant_id,
        status=PriceObservation.Status.APPROVED,
    ).order_by('-observed_at', '-pk').first()
    if not latest or latest.pk != observation.pk:
        return

    previous = PriceObservation.objects.filter(
        variant_id=observation.variant_id,
        status=PriceObservation.Status.APPROVED,
        is_available=True,
        valid_until__gt=observation.observed_at,
        currency=observation.currency,
        price_basis=observation.price_basis,
        tax_included=observation.tax_included,
        delivery_location=observation.delivery_location,
    ).exclude(pk=observation.pk).order_by('-observed_at', '-pk').first()
    if not previous:
        return

    difference = observation.amount - previous.amount
    percent = (difference * Decimal('100') / previous.amount).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP,
    )
    if difference > 0:
        trend, label = MarketNews.Trend.RISING, 'افزایش'
    elif difference < 0:
        trend, label = MarketNews.Trend.FALLING, 'کاهش'
    else:
        trend, label = MarketNews.Trend.UNCHANGED, 'ثبات'

    variant = observation.variant
    headline = f'{label} قیمت {variant.product.name} — {variant.name}'[:240]
    location_text = f' در محل تحویل {observation.delivery_location}' if observation.delivery_location else ''
    summary = (
        f'قیمت از {previous.amount} {observation.get_currency_display()} به '
        f'{observation.amount} {observation.get_currency_display()} برای هر '
        f'{observation.get_price_basis_display()} رسید ({percent:+}%){location_text}.'
    )[:500]
    MarketNews.objects.get_or_create(
        price_observation=observation,
        defaults={
            'previous_observation': previous,
            'variant': variant,
            'headline': headline,
            'summary': summary,
            'trend': trend,
            'previous_amount': previous.amount,
            'current_amount': observation.amount,
            'currency': observation.currency,
            'price_basis': observation.price_basis,
            'tax_included': observation.tax_included,
            'delivery_location': observation.delivery_location,
            'change_percent': percent,
            'published_at': observation.observed_at,
        },
    )


@transaction.atomic
def process_approved_price_observation(observation_id):
    variant_id = PriceObservation.objects.filter(pk=observation_id).values_list(
        'variant_id', flat=True,
    ).first()
    if not variant_id:
        return
    ProductVariant.objects.select_for_update().get(pk=variant_id)
    observation = PriceObservation.objects.select_for_update().select_related(
        'variant__product',
    ).filter(pk=observation_id).first()
    if not observation or observation.status != PriceObservation.Status.APPROVED:
        return

    _publish_market_news(observation)
    notify_price_alerts(observation)
