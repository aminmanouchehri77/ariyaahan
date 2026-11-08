"""Report price freshness: expired, expiring soon, missing, and stale by age.

Exit code 1 when any active variant has no valid price, so the command can
alert from cron. Use --hours to define «stale».
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from catalog.models import ProductVariant
from pricing.selectors import with_latest_price


class Command(BaseCommand):
    help = 'شاخص تازگی قیمت‌ها: قیمت منقضی، نزدیک به انقضا، بدون قیمت و قدیمی.'

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=24, help='قیمت قدیمی‌تر از این چند ساعت «کهنه» حساب می‌شود.')
        parser.add_argument('--soon', type=int, default=6, help='انقضا در چند ساعت آینده.')

    def handle(self, *args, hours, soon, **options):
        now = timezone.now()
        variants = list(with_latest_price(ProductVariant.objects.filter(
            is_active=True, product__is_active=True, product__category__is_active=True,
        ).select_related('product')))
        missing = [v for v in variants if v.latest_amount is None]
        expired = [v for v in variants if v.latest_amount is not None and (not v.latest_valid_until or v.latest_valid_until <= now)]
        expiring = [v for v in variants if v.latest_valid_until and now < v.latest_valid_until <= now + timedelta(hours=soon)]
        stale = [v for v in variants if v.latest_observed_at and v.latest_observed_at < now - timedelta(hours=hours)]
        fresh = len(variants) - len(missing) - len(expired)
        score = round(100 * fresh / len(variants)) if variants else 100
        self.stdout.write(f'شاخص تازگی: {score}٪ — {fresh} از {len(variants)} گونه قیمت معتبر دارند.')
        for title, rows in (('بدون قیمت', missing), ('منقضی/بدون اعتبار', expired), (f'انقضا تا {soon} ساعت', expiring), (f'قدیمی‌تر از {hours} ساعت', stale)):
            self.stdout.write(self.style.WARNING(f'{title}: {len(rows)}'))
            for variant in rows[:50]:
                self.stdout.write(f'  - {variant.product.name} — {variant.name}')
        if missing or expired:
            raise SystemExit(1)
