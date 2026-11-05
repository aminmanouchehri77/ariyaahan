from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from pricing.models import PriceObservationTask
from pricing.processing import process_approved_price_observation


MAX_ATTEMPTS = 8
BASE_RETRY_SECONDS = 30
MAX_RETRY_SECONDS = 3600


class Command(BaseCommand):
    help = 'پردازش صف خبر تغییر قیمت و هشدارهای درون‌حسابی.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, limit=100, **options):
        if limit < 1 or limit > 10000:
            raise CommandError('--limit باید بین ۱ و ۱۰۰۰۰ باشد.')

        processed = 0
        pending = 0
        failed = 0
        for _ in range(limit):
            with transaction.atomic():
                event = PriceObservationTask.objects.select_for_update().filter(
                    status=PriceObservationTask.Status.PENDING,
                    available_at__lte=timezone.now(),
                ).order_by('available_at', 'pk').first()
                if event is None:
                    break

                try:
                    # Isolate derived rows so a failed processing attempt rolls
                    # them back while the retry metadata remains committed.
                    with transaction.atomic():
                        process_approved_price_observation(event.observation_id)
                except Exception as error:
                    event.attempts += 1
                    event.last_error = type(error).__name__[:80]
                    if event.attempts >= MAX_ATTEMPTS:
                        event.status = PriceObservationTask.Status.FAILED
                        failed += 1
                    else:
                        delay = min(
                            MAX_RETRY_SECONDS,
                            BASE_RETRY_SECONDS * (2 ** (event.attempts - 1)),
                        )
                        event.available_at = timezone.now() + timedelta(seconds=delay)
                        pending += 1
                    event.save(update_fields=(
                        'attempts', 'last_error', 'status', 'available_at', 'updated_at',
                    ))
                    continue

                event.attempts += 1
                event.status = PriceObservationTask.Status.COMPLETE
                event.completed_at = timezone.now()
                event.last_error = ''
                event.save(update_fields=(
                    'attempts', 'status', 'completed_at', 'last_error', 'updated_at',
                ))
                processed += 1

        self.stdout.write(self.style.SUCCESS(
            f'پردازش موفق: {processed}؛ در انتظار تلاش دوباره: {pending}؛ نیازمند بازبینی: {failed}.'
        ))
