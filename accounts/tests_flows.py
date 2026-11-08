"""Functional tests for account pages: profile, addresses, price alerts, notifications and web push."""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Product, ProductVariant
from pricing.models import PriceObservation

from .models import CustomerAddress, CustomerNotification, CustomerProfile, PriceAlert, PushSubscription


ADDRESS = {
    'title': 'کارگاه', 'recipient': 'رضا', 'mobile': '09123334455', 'province': 'تهران', 'city': 'تهران',
    'postal_code': '', 'address': 'خیابان آزادی', 'delivery_note': '',
}


class AccountBase(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.user = users.create_user('owner')
        self.other_user = users.create_user('other')
        self.profile = CustomerProfile.objects.create(user=self.user, mobile='09121111111')
        self.other_profile = CustomerProfile.objects.create(user=self.other_user, mobile='09122222222')
        self.client.force_login(self.user)


class ProfileTests(AccountBase):
    def test_profile_renders_and_updates(self):
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '09121111111')
        response = self.client.post(reverse('accounts:profile'), {'full_name': 'مریم'})
        self.assertRedirects(response, reverse('accounts:profile'))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.full_name, 'مریم')
        self.assertFalse(self.profile.allow_price_notifications)

    def test_profile_invalid_rerenders(self):
        response = self.client.post(reverse('accounts:profile'), {'full_name': 'x' * 200})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['profile_form'].errors)

    def test_staff_user_without_profile(self):
        staff = get_user_model().objects.create_user('staff', is_staff=True)
        client = Client()
        client.force_login(staff)
        for name in ('profile', 'addresses', 'notifications', 'orders', 'requests'):
            self.assertEqual(client.get(reverse(f'accounts:{name}')).status_code, 200, name)
        self.assertEqual(client.post(reverse('accounts:profile'), {'full_name': 'x'}).status_code, 200)
        self.assertRedirects(client.get(reverse('accounts:address_add')), reverse('accounts:profile'))
        self.assertRedirects(client.get(reverse('accounts:price_alerts')), reverse('accounts:profile'))
        self.assertEqual(client.get(reverse('accounts:address_edit', args=[1])).status_code, 404)
        self.assertEqual(client.post(reverse('accounts:notifications_read')).status_code, 302)
        self.assertEqual(client.post(reverse('accounts:notification_read', args=[1])).status_code, 302)
        self.assertEqual(client.post(reverse('accounts:notification_open', args=[1])).status_code, 404)

    def test_method_not_allowed(self):
        self.assertEqual(self.client.put(reverse('accounts:profile')).status_code, 405)
        self.assertEqual(self.client.get(reverse('accounts:notifications_read')).status_code, 405)


class AddressTests(AccountBase):
    def test_add_list_edit_delete(self):
        self.assertEqual(self.client.get(reverse('accounts:address_add')).status_code, 200)
        response = self.client.post(reverse('accounts:address_add'), ADDRESS)
        self.assertRedirects(response, reverse('accounts:addresses'))
        address = CustomerAddress.objects.get()
        self.assertEqual(address.profile, self.profile)
        self.assertContains(self.client.get(reverse('accounts:addresses')), 'خیابان آزادی')
        self.assertEqual(self.client.get(reverse('accounts:address_edit', args=[address.pk])).status_code, 200)
        response = self.client.post(reverse('accounts:address_edit', args=[address.pk]), {**ADDRESS, 'city': 'کرج'})
        self.assertRedirects(response, reverse('accounts:addresses'))
        address.refresh_from_db()
        self.assertEqual(address.city, 'کرج')
        self.assertEqual(self.client.get(reverse('accounts:address_delete', args=[address.pk])).status_code, 405)
        self.client.post(reverse('accounts:address_delete', args=[address.pk]))
        self.assertFalse(CustomerAddress.objects.exists())

    def test_mobile_and_postal_code_normalised(self):
        for mobile in ('+989123334455', '0912 333 4455', '۰۹۱۲۳۳۳۴۴۵۵', '00989123334455'):
            response = self.client.post(reverse('accounts:address_add'), {
                **ADDRESS, 'mobile': mobile, 'postal_code': '۱۲۳۴۵۶۷۸۹۰',
            })
            self.assertEqual(response.status_code, 302, mobile)
        self.assertEqual(set(CustomerAddress.objects.values_list('mobile', flat=True)), {'09123334455'})
        self.assertEqual(set(CustomerAddress.objects.values_list('postal_code', flat=True)), {'1234567890'})

    def test_invalid_address_rejected(self):
        for bad in ({'mobile': '0212222'}, {'mobile': '09१२३४५६७८९'}, {'postal_code': '123'},
                    {'recipient': ''}, {'address': 'x' * 701}):
            response = self.client.post(reverse('accounts:address_add'), {**ADDRESS, **bad})
            self.assertEqual(response.status_code, 200, bad)
        self.assertFalse(CustomerAddress.objects.exists())

    def test_single_default_address(self):
        self.client.post(reverse('accounts:address_add'), {**ADDRESS, 'is_default': 'on'})
        self.client.post(reverse('accounts:address_add'), {**ADDRESS, 'title': 'دوم', 'is_default': 'on'})
        CustomerAddress.objects.create(profile=self.other_profile, is_default=True, **{
            k: v for k, v in ADDRESS.items()
        })
        defaults = CustomerAddress.objects.filter(profile=self.profile, is_default=True)
        self.assertEqual(list(defaults.values_list('title', flat=True)), ['دوم'])
        self.assertTrue(CustomerAddress.objects.filter(profile=self.other_profile, is_default=True).exists())


class PriceAlertTests(AccountBase):
    def setUp(self):
        super().setUp()
        self.operator = get_user_model().objects.create_user('operator')
        category = Category.objects.create(name='میلگرد', slug='acct-test-cat')
        product = Product.objects.create(category=category, name='میلگرد آجدار', slug='acct-test-product')
        self.variant = ProductVariant.objects.create(product=product, name='۱۲', unit='kg')

    def _payload(self, **extra):
        return {
            'variant': self.variant.pk, 'condition_type': 'target', 'direction': 'below',
            'target_amount': '300000', 'percent_change': '', 'currency': 'IRR', 'price_basis': 'kg',
            'consent': 'on', **extra,
        }

    def _observe(self, amount):
        observation = PriceObservation.objects.create(
            variant=self.variant, amount=Decimal(amount), currency='IRR', price_basis='kg',
            valid_until=timezone.now() + timedelta(days=1), created_by=self.operator,
        )
        observation.approve(self.operator)
        return observation

    def test_create_target_alert(self):
        response = self.client.post(reverse('accounts:price_alerts'), self._payload(notify_sms='on'))
        self.assertRedirects(response, reverse('accounts:price_alerts'))
        alert = PriceAlert.objects.get()
        self.assertEqual(alert.profile, self.profile)
        self.assertTrue(alert.notify_sms)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.allow_price_notifications)
        self.assertContains(self.client.get(reverse('accounts:price_alerts')), 'میلگرد آجدار')

    def test_consent_required_and_sms_opt_in_default_off(self):
        payload = self._payload()
        payload.pop('consent')
        self.assertEqual(self.client.post(reverse('accounts:price_alerts'), payload).status_code, 200)
        self.assertFalse(PriceAlert.objects.exists())
        self.client.post(reverse('accounts:price_alerts'), self._payload())
        self.assertFalse(PriceAlert.objects.get().notify_sms)

    def test_duplicate_alert(self):
        self.client.post(reverse('accounts:price_alerts'), self._payload())
        response = self.client.post(reverse('accounts:price_alerts'), self._payload())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(PriceAlert.objects.count(), 1)
        # Editing a second alert into a duplicate of the first is rejected cleanly too.
        self.client.post(reverse('accounts:price_alerts'), self._payload(target_amount='200000'))
        second = PriceAlert.objects.get(target_amount=Decimal('200000'))
        response = self.client.post(reverse('accounts:price_alert_edit', args=[second.pk]), self._payload())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        second.refresh_from_db()
        self.assertEqual(second.target_amount, Decimal('200000'))

    def test_invalid_inputs(self):
        cases = (
            {'target_amount': ''}, {'target_amount': '-5'}, {'price_basis': 'ton'}, {'variant': '999999'},
            {'condition_type': 'percent', 'percent_change': '5'},  # no baseline price
            {'condition_type': 'percent', 'percent_change': '150'},
            {'currency': 'BTC'}, {'direction': 'sideways'},
        )
        for case in cases:
            response = self.client.post(reverse('accounts:price_alerts'), self._payload(**case))
            self.assertEqual(response.status_code, 200, case)
        self.assertFalse(PriceAlert.objects.exists())

    def test_percent_alert_uses_baseline(self):
        self._observe(400000)
        response = self.client.post(reverse('accounts:price_alerts'), self._payload(
            condition_type='percent', percent_change='10', target_amount='',
        ))
        self.assertEqual(response.status_code, 302)
        alert = PriceAlert.objects.get()
        self.assertEqual(alert.baseline_amount, Decimal('400000'))
        self.assertEqual(alert.target_amount, 0)
        with override_settings(PUSH_DELIVERY_ENABLED=True, VAPID_PUBLIC_KEY='BKey'):
            response = self.client.get(reverse('accounts:price_alerts'))
        self.assertContains(response, '۱۰')
        self.assertContains(response, 'push-subscribe-button')
        self.assertEqual(self.client.get(reverse('accounts:price_alert_edit', args=[alert.pk])).status_code, 200)

    def test_inactive_variant_not_selectable(self):
        self.variant.is_active = False
        self.variant.save()
        self.assertEqual(self.client.post(reverse('accounts:price_alerts'), self._payload()).status_code, 200)
        self.assertFalse(PriceAlert.objects.exists())

    def test_variant_query_param(self):
        response = self.client.get(reverse('accounts:price_alerts'), {'variant': self.variant.pk})
        self.assertEqual(response.context['form'].initial['variant'], self.variant.pk)
        for junk in ('abc', '²', '٣', '99999999999999999999999', '-1', ''):
            self.assertEqual(self.client.get(reverse('accounts:price_alerts'), {'variant': junk}).status_code, 200, junk)

    def test_edit_toggle_delete(self):
        self.client.post(reverse('accounts:price_alerts'), self._payload())
        alert = PriceAlert.objects.get()
        self.assertEqual(self.client.get(reverse('accounts:price_alert_edit', args=[alert.pk])).status_code, 200)
        response = self.client.post(reverse('accounts:price_alert_edit', args=[alert.pk]), self._payload(
            target_amount='250000', notify_sms='on',
        ))
        self.assertRedirects(response, reverse('accounts:price_alerts'))
        alert.refresh_from_db()
        self.assertEqual(alert.target_amount, Decimal('250000'))
        self.assertTrue(alert.notify_sms)
        self.client.post(reverse('accounts:price_alert_edit', args=[alert.pk]), self._payload(target_amount='250000'))
        alert.refresh_from_db()
        self.assertFalse(alert.notify_sms)
        self.client.post(reverse('accounts:price_alert_toggle', args=[alert.pk]))
        alert.refresh_from_db()
        self.assertFalse(alert.is_active)
        self.client.post(reverse('accounts:price_alert_toggle', args=[alert.pk]))
        alert.refresh_from_db()
        self.assertTrue(alert.is_active)
        self.assertEqual(self.client.get(reverse('accounts:price_alert_delete', args=[alert.pk])).status_code, 405)
        self.client.post(reverse('accounts:price_alert_delete', args=[alert.pk]))
        self.assertFalse(PriceAlert.objects.exists())

    def test_reactivating_percent_alert_requires_fresh_baseline(self):
        observation = self._observe(400000)
        self.client.post(reverse('accounts:price_alerts'), self._payload(
            condition_type='percent', percent_change='10', target_amount='',
        ))
        alert = PriceAlert.objects.get()
        PriceAlert.objects.update(is_active=False)
        PriceObservation.objects.filter(pk=observation.pk).update(valid_until=timezone.now() - timedelta(minutes=1))
        self.client.post(reverse('accounts:price_alert_toggle', args=[alert.pk]))
        alert.refresh_from_db()
        self.assertFalse(alert.is_active)

    def test_other_users_alert_inaccessible(self):
        alert = PriceAlert.objects.create(
            profile=self.other_profile, variant=self.variant, direction='below',
            target_amount=Decimal('1000'), currency='IRR', price_basis='kg',
        )
        self.assertEqual(self.client.get(reverse('accounts:price_alert_edit', args=[alert.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('accounts:price_alert_edit', args=[alert.pk]), self._payload()).status_code, 404)
        self.assertEqual(self.client.post(reverse('accounts:price_alert_toggle', args=[alert.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('accounts:price_alert_delete', args=[alert.pk])).status_code, 404)
        alert.refresh_from_db()
        self.assertTrue(alert.is_active)
        self.assertNotIn(alert, self.client.get(reverse('accounts:price_alerts')).context['alerts'])


class NotificationTests(AccountBase):
    def _make(self, count, profile=None, **extra):
        for index in range(count):
            CustomerNotification.objects.create(
                profile=profile or self.profile, title=f'اعلان {index}', body='متن', **extra,
            )

    def test_list_filter_paginate(self):
        self._make(25)
        CustomerNotification.objects.filter(title='اعلان 0').update(is_read=True)
        response = self.client.get(reverse('accounts:notifications'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj'].object_list), 20)
        self.assertEqual(response.context['unread_count'], 24)
        self.assertEqual(response.context['next_url'], '?page=2')
        response = self.client.get(reverse('accounts:notifications'), {'status': 'unread', 'page': 2})
        self.assertEqual(len(response.context['page_obj'].object_list), 4)
        self.assertEqual(response.context['previous_url'], '?status=unread')
        for junk in ('abc', '-1', '9999', '²'):
            self.assertEqual(self.client.get(reverse('accounts:notifications'), {'page': junk}).status_code, 200)

    def test_mark_one_and_all_read(self):
        self._make(3)
        self._make(1, profile=self.other_profile)
        first = CustomerNotification.objects.filter(profile=self.profile).first()
        self.client.post(reverse('accounts:notification_read', args=[first.pk]))
        first.refresh_from_db()
        self.assertTrue(first.is_read)
        self.client.post(reverse('accounts:notifications_read'))
        self.assertFalse(CustomerNotification.objects.filter(profile=self.profile, is_read=False).exists())
        self.assertTrue(CustomerNotification.objects.filter(profile=self.other_profile, is_read=False).exists())

    def test_open_without_target(self):
        self._make(1)
        note = CustomerNotification.objects.get()
        response = self.client.post(reverse('accounts:notification_open', args=[note.pk]))
        self.assertRedirects(response, reverse('accounts:notifications'))


@override_settings(PUSH_DELIVERY_ENABLED=True, VAPID_PUBLIC_KEY='BPublicKeyForTests')
class PushTests(AccountBase):
    endpoint = 'https://fcm.googleapis.com/fcm/send/abc123'

    def _subscribe(self, subscription, client=None):
        return (client or self.client).post(
            reverse('accounts:push_subscribe'), json.dumps({'subscription': subscription}),
            content_type='application/json',
        )

    def _sub(self, endpoint=None):
        return {'endpoint': endpoint or self.endpoint, 'keys': {'p256dh': 'p' * 40, 'auth': 'a' * 16}}

    def test_subscribe_and_unsubscribe(self):
        self.assertEqual(self._subscribe(self._sub()).status_code, 200)
        self.assertEqual(PushSubscription.objects.get().profile, self.profile)
        self.assertEqual(self._subscribe(self._sub()).status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 1)
        response = self.client.post(reverse('accounts:push_unsubscribe'), json.dumps({'endpoint': self.endpoint}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PushSubscription.objects.exists())

    def test_rejects_untrusted_endpoints(self):
        for endpoint in (
            'http://fcm.googleapis.com/x', 'https://evil.example/x', 'https://fcm.googleapis.com.evil.example/x',
            'https://127.0.0.1/x', 'https://user:pw@fcm.googleapis.com/x', 'https://fcm.googleapis.com:8443/x',
            'https://[::1]/x', 'https://evilfcm.googleapis.com.example/x', 'https://' + 'a' * 2100,
        ):
            self.assertEqual(self._subscribe(self._sub(endpoint)).status_code, 400, endpoint)
        self.assertFalse(PushSubscription.objects.exists())

    def test_rejects_bad_payloads(self):
        url = reverse('accounts:push_subscribe')
        for body in ('not json', '[]', json.dumps({'subscription': 'x'}), '\xff', 'x' * 9000,
                     json.dumps({'subscription': {'endpoint': self.endpoint, 'keys': {'p256dh': 'short', 'auth': 'a'}}}),
                     json.dumps({'subscription': {'endpoint': 5, 'keys': {}}})):
            self.assertEqual(self.client.post(url, body, content_type='application/json').status_code, 400, body[:30])

    def test_disabled_returns_503(self):
        with override_settings(PUSH_DELIVERY_ENABLED=False):
            self.assertEqual(self._subscribe(self._sub()).status_code, 503)

    def test_cannot_unsubscribe_other_users_endpoint(self):
        PushSubscription.objects.create(profile=self.other_profile, endpoint=self.endpoint, p256dh='p' * 40, auth='a' * 16)
        self.client.post(reverse('accounts:push_unsubscribe'), json.dumps({'endpoint': self.endpoint}),
                         content_type='application/json')
        self.assertTrue(PushSubscription.objects.exists())

    def test_csrf_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(self._subscribe(self._sub(), client=client).status_code, 403)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(reverse('accounts:push_subscribe')).status_code, 405)
