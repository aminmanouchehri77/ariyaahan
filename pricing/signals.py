from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PriceObservation, PriceObservationTask


@receiver(post_save, sender=PriceObservation)
def enqueue_approved_price(sender, instance, created, update_fields=None, **kwargs):
    if instance.status != PriceObservation.Status.APPROVED:
        return
    if not created and update_fields is not None and 'status' not in update_fields:
        return
    PriceObservationTask.objects.get_or_create(observation_id=instance.pk)
