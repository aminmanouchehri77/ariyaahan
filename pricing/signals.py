from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PriceObservation


def _publish_market_news(observation_id):
    observation = PriceObservation.objects.select_related('variant__product').filter(
        pk=observation_id,
        status=PriceObservation.Status.APPROVED,
    ).first()
    if not observation:
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
        currency=observation.currency,
        price_basis=observation.price_basis,
        tax_included=observation.tax_included,
        delivery_location=observation.delivery_location,
    ).exclude(pk=observation.pk).order_by('-observed_at', '-pk').first()
    if not previous:
        return

    difference = observation.amount - previous.amount
    percent = (difference * Decimal('100') / previous.amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if difference > 0:
        trend = 'rising'
        label = 'افزایش'
    elif difference < 0:
        trend = 'falling'
        label = 'کاهش'
    else:
        trend = 'unchanged'
        label = 'ثبات'
    variant = observation.variant
    headline = f'{label} قیمت {variant.product.name} — {variant.name}'[:240]
    location_text = f' در محل تحویل {observation.delivery_location}' if observation.delivery_location else ''
    summary = (
        f'قیمت از {previous.amount} {observation.get_currency_display()} به '
        f'{observation.amount} {observation.get_currency_display()} برای هر '
        f'{observation.get_price_basis_display()} رسید ({percent:+}%){location_text}.'
    )[:500]
    from content.models import MarketNews

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


@receiver(post_save, sender=PriceObservation)
def create_market_news(sender, instance, created, update_fields=None, **kwargs):
    if instance.status != PriceObservation.Status.APPROVED:
        return
    if not created and update_fields is not None and 'status' not in update_fields:
        return
    transaction.on_commit(lambda: _publish_market_news(instance.pk))
