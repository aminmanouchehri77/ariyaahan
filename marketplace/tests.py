from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ListingReport, MarketplaceListing


@override_settings(FORM_SUBMISSION_LIMIT=100)
class ListingReportTests(TestCase):
    def setUp(self):
        self.listing = MarketplaceListing.objects.create(
            kind=MarketplaceListing.Kind.OFFER, product_label='میلگرد ۱۴', quantity=Decimal('20'),
            quantity_unit='ton', city='اصفهان', contact_name='الف', mobile='09120000000',
            status=MarketplaceListing.Status.APPROVED,
        )

    def _report(self, ip):
        return self.client.post(reverse('marketplace:report_listing', args=[self.listing.pk]), {'reason': 'fake'}, REMOTE_ADDR=ip)

    def test_duplicate_report_is_ignored(self):
        self._report('1.1.1.1')
        self._report('1.1.1.1')
        self.assertEqual(ListingReport.objects.count(), 1)

    def test_three_reports_pull_listing_back_to_review(self):
        for ip in ('1.1.1.1', '2.2.2.2', '3.3.3.3'):
            self._report(ip)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, MarketplaceListing.Status.PENDING)

    def test_hall_filter_by_city(self):
        response = self.client.get(reverse('marketplace:sell'), {'city': 'تهران'})
        self.assertNotContains(response, 'میلگرد ۱۴')
        response = self.client.get(reverse('marketplace:sell'), {'q': 'ميلگرد'})
        self.assertContains(response, 'میلگرد ۱۴')
