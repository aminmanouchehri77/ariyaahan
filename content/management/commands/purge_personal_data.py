"""Delete personal data past its retention period (proposal: data minimisation).

Career applications are kept CAREER_RETENTION_DAYS (default 180) and other
company requests REQUEST_RETENTION_DAYS (default 730). Use --dry-run to
preview. Schedule it daily in production.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from content.models import CompanyRequest


class Command(BaseCommand):
    help = 'حذف داده‌های شخصی درخواست‌های قدیمی طبق دورهٔ نگهداری.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, dry_run=False, **options):
        now = timezone.now()
        career_days = getattr(settings, 'CAREER_RETENTION_DAYS', 180)
        request_days = getattr(settings, 'REQUEST_RETENTION_DAYS', 730)
        careers = CompanyRequest.objects.filter(
            kind=CompanyRequest.Kind.CAREER, created_at__lt=now - timedelta(days=career_days),
        )
        others = CompanyRequest.objects.exclude(kind=CompanyRequest.Kind.CAREER).filter(
            created_at__lt=now - timedelta(days=request_days),
        )
        counts = (careers.count(), others.count())
        if not dry_run:
            careers.delete()
            others.delete()
        verb = 'قابل حذف' if dry_run else 'حذف شد'
        self.stdout.write(self.style.SUCCESS(f'درخواست استخدام {verb}: {counts[0]} — سایر درخواست‌ها {verb}: {counts[1]}'))
