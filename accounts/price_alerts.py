import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings

from django.urls import reverse
from django.utils import timezone

from pricing.models import PriceObservation

from .models import CustomerNotification, PriceAlert

logger = logging.getLogger(__name__)


def _send_alert_sms(notification, observation):
    """Best-effort SMS for an alert; never raises into the worker."""
    from core.templatetags.ariaa_tags import money

    from .sms import SMSBackendNotConfigured, SMSDeliveryFailed, get_sms_backend

    profile = notification.profile
    since = timezone.now() - timedelta(days=1)
    limit = getattr(settings, 'PRICE_ALERT_SMS_DAILY_LIMIT', 5)
    sent_today = CustomerNotification.objects.filter(profile=profile, sms_status='sent', created_at__gte=since).count()
    if sent_today >= limit:
        status = 'limited'
    else:
        try:
            backend = get_sms_backend()
            sender = getattr(backend, 'send_price_alert', None)
            if sender is None:
                raise SMSBackendNotConfigured
            sender(
                profile.mobile,
                product=f'{observation.variant.product.name} {observation.variant.name}',
                amount=money(observation.amount, observation.currency),
            )
            status = 'sent'
        except SMSBackendNotConfigured:
            status = 'skipped'
        except (SMSDeliveryFailed, Exception) as error:  # noqa: BLE001 - worker must continue
            logger.warning('Price alert SMS failed (%s).', type(error).__name__)
            status = 'failed'
    CustomerNotification.objects.filter(pk=notification.pk).update(sms_status=status)


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

        notification, created = CustomerNotification.objects.get_or_create(
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
        if created and alert.notify_sms:
            _send_alert_sms(notification, observation)
        if created:
            updates = {'last_notified_at': timezone.now()}
            if alert.condition_type == PriceAlert.ConditionType.PERCENT_CHANGE:
                updates['is_active'] = False
            PriceAlert.objects.filter(pk=alert.pk).update(**updates)
