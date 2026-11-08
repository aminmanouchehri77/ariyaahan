"""Security and flow tests for the buy/sell halls, listing tracking and abuse reports."""

from datetime import timedelta
from decimal import Decimal
import uuid

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Product, ProductVariant

from .models import ListingReport, MarketplaceListing


def make_listing(**extra):
    data = {
        'kind': MarketplaceListing.Kind.OFFER, 'product_label': 'تیرآهن ۱۴', 'quantity': Decimal('10'),
        'quantity_unit': 'ton', 'city': 'اصفهان', 'contact_name': 'رضا محرمانه', 'mobile': '09123332211',
        'company_name': 'شرکت پنهان', 'status': MarketplaceListing.Status.APPROVED,
    }
    data.update(extra)
    return MarketplaceListing.objects.create(**data)


@override_settings(FORM_SUBMISSION_LIMIT=100)
class HallSubmissionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.data = {
            'product_label': 'ورق گالوانیزه', 'quantity': '5', 'quantity_unit': 'ton', 'currency': 'IRT',
            'city': 'تهران', 'contact_name': 'مینا', 'mobile': '۰۹۱۲۱۲۳۴۵۶۷', 'contact_consent': 'on',
        }

    def test_submission_is_pending_and_redirects_to_status(self):
        response = self.client.post(reverse('marketplace:buy'), self.data)
        listing = MarketplaceListing.objects.get()
        self.assertRedirects(response, reverse('marketplace:listing_status', args=[listing.public_id]))
        self.assertEqual((listing.kind, listing.status, listing.mobile), ('request', 'pending', '09121234567'))
        self.assertNotContains(self.client.get(reverse('marketplace:buy')), 'ورق گالوانیزه</h3>')

    def test_client_cannot_set_status_or_kind(self):
        self.client.post(reverse('marketplace:sell'), dict(self.data, status='approved', kind='request', admin_note='x'))
        listing = MarketplaceListing.objects.get()
        self.assertEqual((listing.kind, listing.status, listing.admin_note), ('offer', 'pending', ''))

    def test_invalid_input_rejected(self):
        for bad in ({'quantity': '0'}, {'quantity': '2000000'}, {'price_amount': '0'}, {'mobile': '123'},
                    {'contact_consent': ''}, {'quantity_unit': 'gallon'}, {'product_label': ''}, {'details': 'x' * 1300}):
            self.client.post(reverse('marketplace:sell'), dict(self.data, **bad))
        self.assertEqual(MarketplaceListing.objects.count(), 0)

    def test_honeypot(self):
        self.client.post(reverse('marketplace:sell'), dict(self.data, website='spam'))
        self.assertEqual(MarketplaceListing.objects.count(), 0)

    @override_settings(FORM_SUBMISSION_LIMIT=2)
    def test_per_ip_throttle(self):
        for _ in range(3):
            response = self.client.post(reverse('marketplace:sell'), self.data, REMOTE_ADDR='8.8.8.8')
        self.assertEqual(MarketplaceListing.objects.count(), 2)
        self.assertContains(response, 'تعداد ارسال‌های شما')

    def test_get_and_csrf(self):
        self.client.get(reverse('marketplace:sell'), self.data)
        self.assertEqual(MarketplaceListing.objects.count(), 0)
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('marketplace:sell'), self.data).status_code, 403)
        self.assertEqual(MarketplaceListing.objects.count(), 0)

    def test_company_name_hidden_without_consent(self):
        self.client.post(reverse('marketplace:sell'), dict(self.data, company_name='', show_company_name='on'))
        self.assertFalse(MarketplaceListing.objects.get().show_company_name)


class HallVisibilityTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_only_approved_unexpired_listings_and_no_private_data(self):
        make_listing(product_label='آگهی تأییدشده', details='<script>alert("x")</script>')
        make_listing(product_label='آگهی در انتظار', status='pending')
        make_listing(product_label='آگهی ردشده', status='rejected')
        make_listing(product_label='آگهی منقضی', expires_at=timezone.now() - timedelta(minutes=1))
        make_listing(product_label='آگهی خرید', kind='request')
        response = self.client.get(reverse('marketplace:sell'))
        self.assertContains(response, 'آگهی تأییدشده')
        for hidden in ('آگهی در انتظار', 'آگهی ردشده', 'آگهی منقضی', 'آگهی خرید', '09123332211', 'رضا محرمانه', 'شرکت پنهان'):
            self.assertNotContains(response, hidden)
        self.assertNotContains(response, '<script>alert("x")')
        self.assertContains(response, '&lt;script&gt;')

    def test_inactive_catalog_variant_hides_listing(self):
        category = Category.objects.create(name='ورق', slug='sheet-cat')
        product = Product.objects.create(category=category, name='ورق', slug='sheet-p', is_active=False)
        variant = ProductVariant.objects.create(product=product, name='۲', unit='kg')
        make_listing(product_label='آگهی کالای غیرفعال', product_variant=variant)
        self.assertNotContains(self.client.get(reverse('marketplace:sell')), 'آگهی کالای غیرفعال')

    def test_city_and_search_filters(self):
        make_listing(product_label='میلگرد ۱۶', city='شیراز')
        make_listing(product_label='نبشی ۵', city='تبریز')
        response = self.client.get(reverse('marketplace:sell'), {'city': 'شیراز'})
        self.assertContains(response, 'میلگرد ۱۶')
        self.assertNotContains(response, 'نبشی ۵')
        response = self.client.get(reverse('marketplace:sell'), {'q': 'نبشی', 'city': '', 'page': 'abc'})
        self.assertContains(response, 'نبشی ۵')
        self.assertNotContains(response, 'میلگرد ۱۶')
        response = self.client.get(reverse('marketplace:sell'), {'city': '"><script>alert(1)</script>'})
        self.assertNotContains(response, '"><script>alert(1)')

    def test_status_page_private(self):
        listing = make_listing(status='pending', details='جزئیات محرمانه')
        response = self.client.get(reverse('marketplace:listing_status', args=[listing.public_id]))
        self.assertEqual(response.status_code, 200)
        for secret in ('09123332211', 'رضا محرمانه', 'شرکت پنهان', 'جزئیات محرمانه'):
            self.assertNotContains(response, secret)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(listing.public_id.version, 4)
        self.assertEqual(self.client.get(f'/market/listings/{uuid.uuid4()}/').status_code, 404)


@override_settings(FORM_SUBMISSION_LIMIT=100)
class ListingReportAbuseTests(TestCase):
    def setUp(self):
        cache.clear()
        self.listing = make_listing()
        self.url = reverse('marketplace:report_listing', args=[self.listing.pk])

    def _report(self, ip, client=None, **data):
        return (client or self.client).post(self.url, {'reason': 'fake', **data}, REMOTE_ADDR=ip)

    def test_get_and_csrf_rejected(self):
        self.assertEqual(self.client.get(self.url, {'reason': 'fake'}).status_code, 405)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, {'reason': 'fake'}).status_code, 403)
        self.assertEqual(ListingReport.objects.count(), 0)

    def test_invalid_reason_and_non_public_listing(self):
        self._report('1.1.1.1', reason='bogus')
        self.assertEqual(ListingReport.objects.count(), 0)
        pending = make_listing(status='pending')
        response = self.client.post(reverse('marketplace:report_listing', args=[pending.pk]), {'reason': 'fake'})
        self.assertEqual(response.status_code, 404)

    def test_one_ip_with_several_accounts_cannot_unpublish(self):
        for index in range(4):
            user = User.objects.create_user(f'user{index}', password='x')
            client = Client()
            client.force_login(user)
            self._report('9.9.9.9', client=client)
        self._report('9.9.9.9')
        self.assertEqual(ListingReport.objects.count(), 1)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, MarketplaceListing.Status.APPROVED)

    def test_reapproved_listing_needs_fresh_reports(self):
        for ip in ('1.1.1.1', '2.2.2.2', '3.3.3.3'):
            self._report(ip)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, MarketplaceListing.Status.PENDING)
        # A moderator re-approves after reviewing; old reports stay open in the queue.
        MarketplaceListing.objects.filter(pk=self.listing.pk).update(status='approved', reviewed_at=timezone.now())
        self._report('4.4.4.4')
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, MarketplaceListing.Status.APPROVED)
        self._report('5.5.5.5')
        self._report('6.6.6.6')
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.status, MarketplaceListing.Status.PENDING)

    def test_report_rate_limited_per_ip(self):
        listings = [make_listing(product_label=f'آگهی {index}') for index in range(12)]
        for listing in listings:
            self.client.post(reverse('marketplace:report_listing', args=[listing.pk]), {'reason': 'fake'}, REMOTE_ADDR='3.3.3.3')
        self.assertEqual(ListingReport.objects.count(), 10)

    def test_details_truncated_and_stored_raw_for_admin_escaping(self):
        self._report('1.1.1.1', details='<b>x</b>' * 100)
        self.assertEqual(len(ListingReport.objects.get().details), 400)
