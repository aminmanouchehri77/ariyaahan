"""Delete personal data past its retention period (proposal: data minimisation).

Career applications are kept CAREER_RETENTION_DAYS (default 180); other
company requests, quote/contact inquiries and marketplace listings (counted
from their expiry) are kept REQUEST_RETENTION_DAYS (default 730). Use
--dry-run to preview. Schedule it daily in production.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from content.models import CompanyRequest
from inquiries.models import Inquiry
from marketplace.models import MarketplaceListing


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
        request_cutoff = now - timedelta(days=request_days)
        inquiries = Inquiry.objects.filter(created_at__lt=request_cutoff)
        listings = MarketplaceListing.objects.filter(expires_at__lt=request_cutoff, created_at__lt=request_cutoff)
        counts = (careers.count(), others.count(), inquiries.count(), listings.count())
        if not dry_run:
            careers.delete()
            others.delete()
            inquiries.delete()
            listings.delete()
        verb = 'قابل حذف' if dry_run else 'حذف شد'
        self.stdout.write(self.style.SUCCESS(
            f'درخواست استخدام {verb}: {counts[0]} — سایر درخواست‌ها {verb}: {counts[1]} — '
            f'استعلام و پیام تماس {verb}: {counts[2]} — آگهی تالار {verb}: {counts[3]}'
        ))
