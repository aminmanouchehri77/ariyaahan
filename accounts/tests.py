from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from catalog.models import Category, Product, ProductVariant
from pricing.models import PriceObservation

from .models import CustomerNotification, CustomerProfile, PriceAlert
from .price_alerts import notify_price_alerts


class PriceAlertSmsTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user('alerted')
        self.operator = get_user_model().objects.create_user('operator')
        self.profile = CustomerProfile.objects.create(user=user, mobile='09127777777', allow_price_notifications=True)
        category = Category.objects.create(name='م', slug='m-cat')
        product = Product.objects.create(category=category, name='میلگرد', slug='m-p')
        self.variant = ProductVariant.objects.create(product=product, name='۱۲', unit='kg')

    def _observe(self, amount):
        observation = PriceObservation.objects.create(
            variant=self.variant, amount=Decimal(amount), currency='IRR', price_basis='kg',
            valid_until=timezone.now() + timedelta(days=1), created_by=self.operator,
        )
        observation.approve(self.operator)
        return observation

    def test_sms_sent_when_alert_opted_in(self):
        PriceAlert.objects.create(
            profile=self.profile, variant=self.variant, direction='below', target_amount=Decimal('300000'),
            currency='IRR', price_basis='kg', notify_sms=True,
        )
        backend = mock.Mock()
        with mock.patch('accounts.sms.get_sms_backend', return_value=backend):
            notify_price_alerts(self._observe(290000))
        backend.send_price_alert.assert_called_once()
        self.assertEqual(CustomerNotification.objects.get().sms_status, 'sent')

    def test_no_sms_without_opt_in(self):
        PriceAlert.objects.create(
            profile=self.profile, variant=self.variant, direction='below', target_amount=Decimal('300000'),
            currency='IRR', price_basis='kg',
        )
        backend = mock.Mock()
        with mock.patch('accounts.sms.get_sms_backend', return_value=backend):
            notify_price_alerts(self._observe(290000))
        backend.send_price_alert.assert_not_called()
        self.assertEqual(CustomerNotification.objects.get().sms_status, '')
