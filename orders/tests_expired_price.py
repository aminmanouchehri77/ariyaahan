"""A variant whose price has expired (or has no validity date) must never
enter the cart; the customer is told why."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomerProfile
from catalog.tests_security import CatalogFixtureMixin
from orders.models import ProjectList, ProjectListItem


class ExpiredPriceCartTests(CatalogFixtureMixin, TestCase):
    def add(self):
        return self.client.post(reverse('orders:cart_add', args=[self.variant.pk]), {'quantity': '100'})

    def messages(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]

    def assert_cart_empty(self):
        response = self.client.get(reverse('orders:cart'))
        self.assertEqual(response.context['cart_lines'], [])

    def test_expired_price_is_rejected_with_message(self):
        self.price(valid_for=-timedelta(hours=1))
        response = self.add()
        self.assertRedirects(response, self.product.get_absolute_url(), fetch_redirect_response=False)
        self.assertTrue(any('منقضی شده' in m for m in self.messages(response)))
        self.assert_cart_empty()

    def test_unknown_validity_is_rejected_with_message(self):
        self.price(valid_for=None)
        response = self.add()
        self.assertTrue(any('اعتبار قیمت' in m for m in self.messages(response)))
        self.assert_cart_empty()

    def test_fresh_price_is_added(self):
        self.price()
        response = self.add()
        self.assertRedirects(response, reverse('orders:cart'), fetch_redirect_response=False)
        self.assertEqual(len(self.client.get(reverse('orders:cart')).context['cart_lines']), 1)

    def test_newer_fresh_price_lifts_the_block(self):
        self.price(valid_for=-timedelta(hours=1))
        self.price(amount='310000')
        self.add()
        self.assertEqual(len(self.client.get(reverse('orders:cart')).context['cart_lines']), 1)

    def test_product_page_shows_notice_instead_of_add_button(self):
        self.price(valid_for=-timedelta(hours=1))
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, 'قیمت این کالا منقضی شده است')
        self.assertContains(response, 'استعلام قیمت روز')
        self.assertNotContains(response, reverse('orders:cart_add', args=[self.variant.pk]))

    def test_project_to_cart_skips_expired_items(self):
        self.price(valid_for=-timedelta(hours=1))
        user = get_user_model().objects.create_user('project-owner')
        profile = CustomerProfile.objects.create(user=user, mobile='09121112233')
        project = ProjectList.objects.create(profile=profile, title='ساختمان')
        ProjectListItem.objects.create(project=project, variant=self.variant, quantity=100)
        self.client.force_login(user)
        response = self.client.post(
            reverse('orders:project_update', args=[project.public_id]), {'action': 'to_cart'},
        )
        self.assertTrue(any('منقضی شده' in m for m in self.messages(response)))
        self.assert_cart_empty()
