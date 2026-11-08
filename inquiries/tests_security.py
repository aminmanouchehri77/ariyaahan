"""Security and flow tests for the quote/contact forms and private inquiry tracking."""

import uuid

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomerProfile
from catalog.models import Category, Product, ProductVariant
from marketplace.models import MarketplaceListing

from .models import Inquiry


@override_settings(FORM_SUBMISSION_LIMIT=100)
class InquiryFormTests(TestCase):
    def setUp(self):
        cache.clear()
        category = Category.objects.create(name='میلگرد', slug='rebar-cat')
        product = Product.objects.create(category=category, name='میلگرد آجدار', slug='rebar-p')
        self.variant = ProductVariant.objects.create(product=product, name='۱۴', unit='kg')
        off_product = Product.objects.create(category=category, name='غیرفعال', slug='off-p', is_active=False)
        self.off_variant = ProductVariant.objects.create(product=off_product, name='۱۶', unit='kg')
        self.quote = {'product_variant': self.variant.pk, 'customer_name': 'علی', 'mobile': '+989121234567',
                      'requested_quantity': '12.5', 'message': 'تحویل اصفهان'}
        self.contact = {'customer_name': 'علی', 'mobile': '09121234567', 'message': 'سلام'}

    def test_quote_submission_redirects_to_private_status(self):
        response = self.client.post(reverse('inquiries:quote'), self.quote)
        inquiry = Inquiry.objects.get()
        self.assertRedirects(response, reverse('inquiries:status', args=[inquiry.public_id]))
        self.assertEqual((inquiry.kind, inquiry.mobile, inquiry.quantity_unit), ('quote', '09121234567', 'کیلوگرم'))
        self.assertIn('میلگرد آجدار', inquiry.product_label)

    def test_quote_requires_active_variant(self):
        self.client.post(reverse('inquiries:quote'), dict(self.quote, product_variant=self.off_variant.pk))
        self.client.post(reverse('inquiries:quote'), dict(self.quote, product_variant=''))
        self.assertEqual(Inquiry.objects.count(), 0)
        self.assertEqual(self.client.get(reverse('inquiries:quote'), {'variant': self.off_variant.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse('inquiries:quote'), {'variant': 'abc'}).status_code, 200)
        self.assertEqual(self.client.get(reverse('inquiries:quote'), {'variant': '9' * 30}).status_code, 200)

    def test_invalid_values_rejected(self):
        for bad in ({'mobile': '0912'}, {'requested_quantity': '-1'}, {'requested_quantity': '0'},
                    {'customer_name': ''}, {'message': 'x' * 3001}):
            response = self.client.post(reverse('inquiries:quote'), dict(self.quote, **bad))
            self.assertEqual(response.status_code, 200, bad)
        self.assertEqual(Inquiry.objects.count(), 0)

    def test_honeypot_rendered_and_enforced(self):
        self.assertContains(self.client.get(reverse('inquiries:contact')), 'name="website"')
        self.client.post(reverse('inquiries:contact'), dict(self.contact, website='http://spam.example'))
        self.client.post(reverse('inquiries:quote'), dict(self.quote, website='x'))
        self.assertEqual(Inquiry.objects.count(), 0)

    @override_settings(FORM_SUBMISSION_LIMIT=2)
    def test_per_ip_throttle(self):
        for _ in range(3):
            response = self.client.post(reverse('inquiries:contact'), self.contact, REMOTE_ADDR='7.7.7.7')
        self.assertEqual(Inquiry.objects.count(), 2)
        self.assertContains(response, 'تعداد ارسال‌های شما')

    def test_get_does_not_create_and_other_methods_rejected(self):
        self.client.get(reverse('inquiries:contact'), self.contact)
        self.client.get(reverse('inquiries:quote'), self.quote)
        self.assertEqual(Inquiry.objects.count(), 0)
        self.assertEqual(self.client.delete(reverse('inquiries:contact')).status_code, 405)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('inquiries:contact'), self.contact).status_code, 403)
        self.assertEqual(Inquiry.objects.count(), 0)

    def test_listing_prefill_only_for_public_listings(self):
        common = {'kind': 'offer', 'product_label': 'ورق سیاه', 'quantity': 3, 'quantity_unit': 'ton', 'city': 'یزد',
                  'contact_name': 'فروشنده', 'mobile': '09127776655', 'details': 'جزئیات خصوصی'}
        approved = MarketplaceListing.objects.create(status='approved', **common)
        pending = MarketplaceListing.objects.create(**common)
        expired = MarketplaceListing.objects.create(status='approved', expires_at=timezone.now(), **common)
        response = self.client.get(reverse('inquiries:contact'), {'listing': approved.pk})
        self.assertContains(response, 'ورق سیاه')
        self.assertNotContains(response, '09127776655')
        self.assertNotContains(response, 'فروشنده')
        for listing in (pending, expired):
            self.assertEqual(self.client.get(reverse('inquiries:contact'), {'listing': listing.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse('inquiries:contact'), {'listing': '1;drop'}).status_code, 200)

    def test_profile_linked_only_for_matching_mobile(self):
        user = User.objects.create_user('buyer', password='x')
        profile = CustomerProfile.objects.create(user=user, mobile='09121234567')
        self.client.force_login(user)
        self.client.post(reverse('inquiries:contact'), self.contact)
        self.client.post(reverse('inquiries:contact'), dict(self.contact, mobile='09120000000'))
        self.assertEqual([i.profile_id for i in Inquiry.objects.order_by('pk')], [profile.pk, None])


class InquiryStatusTests(TestCase):
    def setUp(self):
        self.inquiry = Inquiry.objects.create(
            kind='quote', customer_name='نام محرمانه', mobile='09125554433', message='پیام خصوصی', admin_note='یادداشت‌کارشناس‌۷۷',
        )

    def test_status_hides_private_data_and_sets_headers(self):
        response = self.client.get(reverse('inquiries:status', args=[self.inquiry.public_id]))
        self.assertEqual(response.status_code, 200)
        for secret in ('09125554433', 'نام محرمانه', 'پیام خصوصی', 'یادداشت‌کارشناس‌۷۷'):
            self.assertNotContains(response, secret)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('private', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertContains(response, 'noindex')

    def test_unknown_or_sequential_ids_404(self):
        self.assertEqual(self.inquiry.public_id.version, 4)
        self.assertEqual(self.client.get(f'/requests/{uuid.uuid4()}/').status_code, 404)
        self.assertEqual(self.client.get(f'/requests/{self.inquiry.pk}/').status_code, 404)
