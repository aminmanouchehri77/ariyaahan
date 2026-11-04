from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from pricing.models import PriceObservation

from .models import CustomerNotification, PriceAlert


def _notify_price_alerts(observation_id):
    observation = PriceObservation.objects.select_related('variant__product').filter(
        pk=observation_id, status=PriceObservation.Status.APPROVED,
    ).first()
    if not observation:
        return

    matching = PriceAlert.objects.filter(
        variant_id=observation.variant_id,
        is_active=True,
        currency=observation.currency,
        price_basis=observation.price_basis,
        profile__allow_price_notifications=True,
    ).select_related('profile')
    for alert in matching.iterator():
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
                'body': f'قیمت ثبت‌شده {observation.amount} {observation.get_currency_display()} برای هر {observation.get_price_basis_display()} است.',
                'target_url': reverse('catalog:product_detail', kwargs={'slug': observation.variant.product.slug}),
            },
        )
        if created:
            PriceAlert.objects.filter(pk=alert.pk).update(last_notified_at=timezone.now())


@receiver(post_save, sender=PriceObservation)
def dispatch_price_alerts(sender, instance, created, update_fields=None, **kwargs):
    if instance.status != PriceObservation.Status.APPROVED:
        return
    if created or update_fields is None or 'status' in update_fields:
        from django.db import transaction

        transaction.on_commit(lambda: _notify_price_alerts(instance.pk))
