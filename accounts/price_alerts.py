from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from pricing.models import PriceObservation

from .models import CustomerNotification, PriceAlert


def notify_price_alerts(observation):
    now = timezone.now()
    if (
        observation.status != PriceObservation.Status.APPROVED
        or not observation.is_available
        or not observation.valid_until
        or observation.valid_until <= now
    ):
        return
    latest_id = PriceObservation.objects.filter(
        variant_id=observation.variant_id,
        status=PriceObservation.Status.APPROVED,
    ).order_by('-observed_at', '-pk').values_list('pk', flat=True).first()
    if latest_id != observation.pk:
        return

    matching = PriceAlert.objects.filter(
        variant_id=observation.variant_id,
        is_active=True,
        currency=observation.currency,
        price_basis=observation.price_basis,
        profile__allow_price_notifications=True,
    ).select_related('profile')
    for alert in matching.iterator():
        if alert.condition_type == PriceAlert.ConditionType.PERCENT_CHANGE:
            if (
                alert.baseline_amount is None
                or alert.baseline_location != observation.delivery_location
                or alert.baseline_tax_included != observation.tax_included
            ):
                continue
            fraction = alert.percent_change / Decimal('100')
            threshold = (
                alert.baseline_amount * (Decimal('1') - fraction)
                if alert.direction == PriceAlert.Direction.BELOW
                else alert.baseline_amount * (Decimal('1') + fraction)
            )
            reached = (
                observation.amount <= threshold
                if alert.direction == PriceAlert.Direction.BELOW
                else observation.amount >= threshold
            )
        else:
            reached = (
                observation.amount <= alert.target_amount
                if alert.direction == PriceAlert.Direction.BELOW
                else observation.amount >= alert.target_amount
            )
        if not reached:
            continue

        _, created = CustomerNotification.objects.get_or_create(
            profile=alert.profile,
            price_alert=alert,
            price_observation=observation,
            defaults={
                'kind': CustomerNotification.Kind.PRICE,
                'title': f'قیمت {observation.variant.product.name} به شرط شما رسید',
                'body': (
                    f'قیمت ثبت‌شده {observation.amount} {observation.get_currency_display()} '
                    f'برای هر {observation.get_price_basis_display()} است.'
                ),
                'target_url': reverse(
                    'catalog:product_detail',
                    kwargs={'slug': observation.variant.product.slug},
                ),
            },
        )
        if created:
            updates = {'last_notified_at': timezone.now()}
            if alert.condition_type == PriceAlert.ConditionType.PERCENT_CHANGE:
                updates['is_active'] = False
            PriceAlert.objects.filter(pk=alert.pk).update(**updates)
