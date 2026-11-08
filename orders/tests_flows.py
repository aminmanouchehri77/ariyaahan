"""Cart, checkout, pre-invoice acceptance and project flows exercised through the test client."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomerProfile
from catalog.models import Category, Product, ProductVariant
from pricing.models import InventoryLocation, PriceObservation, StockObservation

from .models import PreInvoice, PreInvoiceItem, ProjectList, ProjectListItem
from .services import convert_preinvoice_to_order, issue_preinvoice_quote

SENT_CODES = []


class CaptureSMSBackend:
    def send_login_code(self, mobile, code):
        SENT_CODES.append((mobile, code))

    def send_preinvoice_acceptance_code(self, mobile, code):
        SENT_CODES.append((mobile, code))


class CatalogMixin:
    def make_catalog(self):
        self.staff = get_user_model().objects.create_user('staff', is_staff=True)
        category = Category.objects.create(name='میلگرد', slug='rebar-flow')
        product = Product.objects.create(category=category, name='میلگرد آجدار', slug='rebar-flow-p')
        self.variant = ProductVariant.objects.create(product=product, name='۱۴', unit='kg')
        self.location = InventoryLocation.objects.create(name='انبار تهران')
        self.price = self.set_price(Decimal('100'))
        self.set_stock(Decimal('50000'))

    def set_price(self, amount, *, variant=None, currency='IRT', basis='kg'):
        observation = PriceObservation.objects.create(
            variant=variant or self.variant, amount=amount, currency=currency, price_basis=basis,
            unit_label='کیلوگرم', valid_until=timezone.now() + timedelta(days=1),
        )
        observation.approve(self.staff)
        return observation

    def set_stock(self, quantity, *, variant=None):
        observation = StockObservation.objects.create(
            variant=variant or self.variant, location=self.location, quantity=quantity, unit='kg',
            valid_until=timezone.now() + timedelta(days=1),
        )
        observation.approve(self.staff)
        return observation


class CartTests(CatalogMixin, TestCase):
    def setUp(self):
        self.make_catalog()
        self.add_url = reverse('orders:cart_add', args=[self.variant.pk])

    def cart(self):
        return self.client.session.get('ariaa_cart', {})

    def test_add_valid_and_decimal_quantities(self):
        self.client.post(self.add_url, {'quantity': '2.5'})
        self.client.post(self.add_url, {'quantity': '0.125'})
        self.assertEqual(self.cart(), {str(self.variant.pk): '2.625'})

    def test_invalid_quantities_are_rejected(self):
        for raw in ('0', '-5', 'abc', '', '1.0005', 'NaN', 'Infinity', '1e9', '99999999999999'):
            response = self.client.post(self.add_url, {'quantity': raw})
            self.assertRedirects(response, reverse('orders:cart'), fetch_redirect_response=False)
            self.assertEqual(self.cart(), {}, raw)

    def test_cumulative_quantity_capped(self):
        self.client.post(self.add_url, {'quantity': '1000000'})
        self.client.post(self.add_url, {'quantity': '1'})
        self.assertEqual(self.cart(), {str(self.variant.pk): '1000000'})

    def test_inactive_or_unknown_variant_is_404(self):
        self.assertEqual(self.client.post(reverse('orders:cart_add', args=[999999]), {'quantity': '1'}).status_code, 404)
        self.variant.is_active = False
        self.variant.save()
        self.assertEqual(self.client.post(self.add_url, {'quantity': '1'}).status_code, 404)

    def test_get_does_not_change_cart(self):
        self.assertEqual(self.client.get(self.add_url, {'quantity': '1'}).status_code, 405)
        self.client.post(self.add_url, {'quantity': '1'})
        self.assertEqual(self.client.get(reverse('orders:cart_remove', args=[self.variant.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse('orders:cart_update', args=[self.variant.pk])).status_code, 405)
        self.assertEqual(self.cart(), {str(self.variant.pk): '1'})

    def test_update_and_remove(self):
        self.client.post(self.add_url, {'quantity': '1'})
        update = reverse('orders:cart_update', args=[self.variant.pk])
        self.client.post(update, {'quantity': '0'})
        self.assertEqual(self.cart(), {str(self.variant.pk): '1'})
        self.client.post(update, {'quantity': '7'})
        self.assertEqual(self.cart(), {str(self.variant.pk): '7'})
        # Updating an item not in the cart does not add it.
        self.client.post(reverse('orders:cart_update', args=[self.variant.pk + 1]), {'quantity': '3'})
        self.assertEqual(len(self.cart()), 1)
        self.client.post(reverse('orders:cart_remove', args=[self.variant.pk]))
        self.assertEqual(self.cart(), {})

    def test_tampered_session_cart_is_normalized(self):
        session = self.client.session
        session['ariaa_cart'] = {str(self.variant.pk): '-3', 'x': '1', '99': 'abc', str(self.variant.pk + 5): '2'}
        session.save()
        response = self.client.get(reverse('orders:cart'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cart_lines'], [])

    def test_csrf_enforced_on_cart_mutations(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(self.add_url, {'quantity': '1'}).status_code, 403)
        self.assertEqual(client.post(reverse('orders:cart_remove', args=[self.variant.pk])).status_code, 403)
        self.assertEqual(client.post(reverse('orders:checkout') + '../checkout/submit/').status_code, 403)

    def test_cart_page_with_shipping_query_params(self):
        self.client.post(self.add_url, {'quantity': '1000'})
        response = self.client.get(reverse('orders:cart'), {'origin': 'x' * 500, 'destination': 'y', 'method': '<script>'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['shipping_estimate'])
        self.assertEqual(response.context['cart_weight_tonnes'], Decimal('1.000'))

    def test_shipping_estimate_and_grand_total(self):
        from pricing.models import ShippingRate
        ShippingRate.objects.create(
            origin_city='تهران', destination_city='کرج', per_tonne=Decimal('500000'), base_fee=Decimal('0'),
            currency='IRR', valid_until=timezone.now() + timedelta(days=1),
        )
        self.client.post(self.add_url, {'quantity': '2000'})
        params = {'origin': 'تهران', 'destination': 'کرج'}
        response = self.client.get(reverse('orders:cart'), params)
        self.assertEqual(response.context['shipping_estimate']['amount'], Decimal('1000000'))
        # 2000 kg x 100 Toman = 2,000,000 Rial goods + 1,000,000 Rial shipping.
        self.assertEqual(response.context['grand_total_rial'], Decimal('3000000'))
        # An item without a reference weight makes the shipping figure partial: no grand total.
        unweighed = ProductVariant.objects.create(product=self.variant.product, name='شاخه', unit='piece')
        self.set_price(Decimal('10'), variant=unweighed, basis='piece')
        self.client.post(reverse('orders:cart_add', args=[unweighed.pk]), {'quantity': '3'})
        response = self.client.get(reverse('orders:cart'), params)
        self.assertFalse(response.context['cart_weight_complete'])
        self.assertFalse(response.context['has_unpriced_items'])
        self.assertIsNone(response.context['grand_total_rial'])


@override_settings(SMS_BACKEND='orders.tests_flows.CaptureSMSBackend')
class CheckoutTests(CatalogMixin, TestCase):
    def setUp(self):
        self.make_catalog()
        SENT_CODES.clear()
        self.client.post(reverse('orders:cart_add', args=[self.variant.pk]), {'quantity': '1000'})
        self.form = {'customer_name': 'علی رضایی', 'mobile': '09121234567'}

    def submit(self, **extra):
        return self.client.post(reverse('orders:submit_preinvoice'), {**self.form, **extra})

    def test_checkout_get_requires_items(self):
        self.client.post(reverse('orders:cart_remove', args=[self.variant.pk]))
        self.assertRedirects(self.client.get(reverse('orders:checkout')), reverse('orders:cart'), fetch_redirect_response=False)

    def test_submit_without_viewing_checkout_is_refused(self):
        response = self.submit()
        self.assertRedirects(response, reverse('orders:checkout'), fetch_redirect_response=False)
        self.assertFalse(PreInvoice.objects.exists())

    def test_submit_snapshots_price_and_stock(self):
        self.client.get(reverse('orders:checkout'))
        response = self.submit()
        preinvoice = PreInvoice.objects.get()
        self.assertRedirects(response, reverse('orders:preinvoice_detail', args=[preinvoice.public_id]), fetch_redirect_response=False)
        self.assertEqual(preinvoice.status, PreInvoice.Status.PENDING)
        item = preinvoice.items.get()
        self.assertEqual(item.unit_price, Decimal('100'))
        self.assertEqual(item.line_total, Decimal('100000'))
        self.assertEqual(item.price_observation, self.price)
        self.assertTrue(item.stock_is_usable)
        self.assertEqual(self.client.session.get('ariaa_cart'), {})

    def test_price_change_between_view_and_submit_requires_reacknowledgement(self):
        self.client.get(reverse('orders:checkout'))
        self.set_price(Decimal('120'))
        response = self.submit(price_confirmation='on')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['quote_confirmation_required'])
        self.assertFalse(PreInvoice.objects.exists())
        # Submitting again without the acknowledgement checkbox is still refused.
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PreInvoice.objects.exists())
        response = self.submit(price_confirmation='on')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PreInvoice.objects.get().items.get().unit_price, Decimal('120'))

    def test_stock_change_requires_reacknowledgement(self):
        self.client.get(reverse('orders:checkout'))
        self.set_stock(Decimal('10'))
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PreInvoice.objects.exists())
        self.submit(price_confirmation='on')
        self.assertEqual(PreInvoice.objects.get().status, PreInvoice.Status.REVIEW)

    def test_invalid_mobile_rerenders(self):
        self.client.get(reverse('orders:checkout'))
        response = self.submit(mobile='12345')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PreInvoice.objects.exists())

    def test_other_users_saved_address_cannot_be_used(self):
        from accounts.models import CustomerAddress
        owner = get_user_model().objects.create_user('addr-owner')
        owner_profile = CustomerProfile.objects.create(user=owner, mobile='09127777777')
        address = CustomerAddress.objects.create(
            profile=owner_profile, title='خانه', recipient='مالک', mobile='09127777777',
            province='تهران', city='تهران', address='نشانی محرمانه', postal_code='1234567890',
        )
        me = get_user_model().objects.create_user('buyer')
        CustomerProfile.objects.create(user=me, mobile='09121234567')
        self.client.force_login(me)
        self.client.post(reverse('orders:cart_add', args=[self.variant.pk]), {'quantity': '1000'})
        self.client.get(reverse('orders:checkout'))
        response = self.submit(saved_address=str(address.pk))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PreInvoice.objects.filter(delivery_address='نشانی محرمانه').exists())

    def test_replayed_submit_with_stale_session_does_not_double_create(self):
        self.client.get(reverse('orders:checkout'))
        session = self.client.session
        stale = dict(session.items())
        self.assertEqual(self.submit().status_code, 302)
        # A concurrent duplicate request carries the session state from before the first commit.
        session = self.client.session
        for key, value in stale.items():
            session[key] = value
        session.save()
        response = self.submit()
        self.assertEqual(PreInvoice.objects.count(), 1)
        self.assertRedirects(
            response, reverse('orders:preinvoice_detail', args=[PreInvoice.objects.get().public_id]),
            fetch_redirect_response=False,
        )

    def test_get_submit_is_not_allowed(self):
        self.client.get(reverse('orders:checkout'))
        self.assertEqual(self.client.get(reverse('orders:submit_preinvoice'), self.form).status_code, 405)
        self.assertFalse(PreInvoice.objects.exists())


@override_settings(SMS_BACKEND='orders.tests_flows.CaptureSMSBackend')
class PreInvoiceAcceptanceTests(CatalogMixin, TestCase):
    def setUp(self):
        self.make_catalog()
        SENT_CODES.clear()
        self.preinvoice = PreInvoice.objects.create(customer_name='مشتری', mobile='09121234567')
        PreInvoiceItem.objects.create(
            preinvoice=self.preinvoice, variant=self.variant, product_name='میلگرد', variant_name='۱۴',
            quantity=Decimal('1000'), quantity_unit='kg',
        )
        self.assertTrue(issue_preinvoice_quote(self.preinvoice.pk))
        self.preinvoice.refresh_from_db()
        self.detail = reverse('orders:preinvoice_detail', args=[self.preinvoice.public_id])
        self.send_code = reverse('orders:preinvoice_acceptance_code', args=[self.preinvoice.public_id])
        self.accept = reverse('orders:preinvoice_accept', args=[self.preinvoice.public_id])

    def test_full_acceptance_and_conversion(self):
        self.assertEqual(self.preinvoice.status, PreInvoice.Status.AWAITING_CUSTOMER)
        self.client.post(self.send_code)
        mobile, code = SENT_CODES[-1]
        self.assertEqual(mobile, '09121234567')
        self.client.post(self.accept, {'code': code, 'accept_quote': 'on'})
        self.preinvoice.refresh_from_db()
        self.assertEqual(self.preinvoice.status, PreInvoice.Status.CONFIRMED)
        order = convert_preinvoice_to_order(self.preinvoice.pk)
        self.assertIsNotNone(order)
        self.assertEqual(order.items.get().line_total, Decimal('100000'))
        self.assertEqual(order.currency, 'IRT')

    def test_wrong_code_and_missing_checkbox_do_not_accept(self):
        self.client.post(self.send_code)
        _, code = SENT_CODES[-1]
        wrong = '000000' if code != '000000' else '111111'
        self.client.post(self.accept, {'code': wrong, 'accept_quote': 'on'})
        self.client.post(self.accept, {'code': code})
        self.client.post(self.accept, {'code': 'abcdef', 'accept_quote': 'on'})
        self.preinvoice.refresh_from_db()
        self.assertEqual(self.preinvoice.status, PreInvoice.Status.AWAITING_CUSTOMER)

    def test_accept_requires_code_requested_in_same_session(self):
        self.client.post(self.send_code)
        _, code = SENT_CODES[-1]
        attacker = Client()
        attacker.post(self.accept, {'code': code, 'accept_quote': 'on'})
        self.preinvoice.refresh_from_db()
        self.assertEqual(self.preinvoice.status, PreInvoice.Status.AWAITING_CUSTOMER)

    def test_price_change_after_issue_returns_to_review(self):
        self.client.post(self.send_code)
        _, code = SENT_CODES[-1]
        self.set_price(Decimal('130'))
        self.client.post(self.accept, {'code': code, 'accept_quote': 'on'})
        self.preinvoice.refresh_from_db()
        self.assertEqual(self.preinvoice.status, PreInvoice.Status.REVIEW)

    def test_expired_quote_cannot_be_accepted(self):
        self.client.post(self.send_code)
        _, code = SENT_CODES[-1]
        PreInvoice.objects.filter(pk=self.preinvoice.pk).update(quote_valid_until=timezone.now() - timedelta(minutes=1))
        self.client.post(self.accept, {'code': code, 'accept_quote': 'on'})
        self.preinvoice.refresh_from_db()
        self.assertEqual(self.preinvoice.status, PreInvoice.Status.REVIEW)

    def test_get_never_changes_state_and_csrf_required(self):
        self.assertEqual(self.client.get(self.send_code).status_code, 405)
        self.assertEqual(self.client.get(self.accept).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf_client.post(self.send_code).status_code, 403)
        self.assertEqual(csrf_client.post(self.accept, {'code': '123456', 'accept_quote': 'on'}).status_code, 403)
        self.assertEqual(SENT_CODES, [])

    def test_unknown_preinvoice_is_404(self):
        import uuid
        self.assertEqual(self.client.get(reverse('orders:preinvoice_detail', args=[uuid.uuid4()])).status_code, 404)
        self.assertEqual(self.client.get(f'/orders/preinvoice/{self.preinvoice.pk}/').status_code, 404)
        self.assertEqual(self.client.post(reverse('orders:preinvoice_accept', args=[uuid.uuid4()])).status_code, 404)

    def test_detail_masks_mobile_and_is_not_cached(self):
        response = self.client.get(self.detail)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')


class ProjectSecurityTests(CatalogMixin, TestCase):
    def setUp(self):
        self.make_catalog()
        self.owner = get_user_model().objects.create_user('owner')
        self.profile = CustomerProfile.objects.create(user=self.owner, mobile='09121110000')
        self.project = ProjectList.objects.create(profile=self.profile, title='برج')
        self.item = ProjectListItem.objects.create(project=self.project, variant=self.variant, quantity=Decimal('5'))
        self.other = get_user_model().objects.create_user('intruder')
        CustomerProfile.objects.create(user=self.other, mobile='09122220000')

    def test_anonymous_redirected_to_login(self):
        for url in (
            reverse('orders:project_list'),
            reverse('orders:project_detail', args=[self.project.public_id]),
        ):
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_other_user_cannot_mutate_project(self):
        self.client.force_login(self.other)
        update = reverse('orders:project_update', args=[self.project.public_id])
        for action in ('delete', 'share', 'rename', 'to_cart'):
            self.assertEqual(self.client.post(update, {'action': action, 'title': 'hacked'}).status_code, 404)
        item_url = reverse('orders:project_item_update', args=[self.project.public_id, self.item.pk])
        self.assertEqual(self.client.post(item_url, {'action': 'remove'}).status_code, 404)
        self.assertEqual(self.client.post(item_url, {'quantity': '99'}).status_code, 404)
        add = reverse('orders:project_add_item', args=[self.variant.pk])
        self.assertEqual(self.client.post(add, {'project': str(self.project.public_id), 'quantity': '1'}).status_code, 404)
        self.project.refresh_from_db()
        self.assertEqual(self.project.title, 'برج')
        self.assertFalse(self.project.is_shared)
        self.assertTrue(ProjectListItem.objects.filter(pk=self.item.pk, quantity=Decimal('5')).exists())

    def test_item_id_from_another_project_is_rejected(self):
        own = ProjectList.objects.create(profile=CustomerProfile.objects.get(user=self.other), title='من')
        self.client.force_login(self.other)
        url = reverse('orders:project_item_update', args=[own.public_id, self.item.pk])
        self.assertEqual(self.client.post(url, {'action': 'remove'}).status_code, 404)
        self.assertTrue(ProjectListItem.objects.filter(pk=self.item.pk).exists())

    def test_malformed_project_id_is_not_a_server_error(self):
        self.client.force_login(self.owner)
        add = reverse('orders:project_add_item', args=[self.variant.pk])
        response = self.client.post(add, {'project': 'not-a-uuid', 'quantity': '1'})
        self.assertEqual(response.status_code, 404)

    def test_invalid_item_quantities(self):
        self.client.force_login(self.owner)
        url = reverse('orders:project_item_update', args=[self.project.public_id, self.item.pk])
        for raw in ('0', '-1', 'abc', '', '1.23456', '1e12'):
            self.client.post(url, {'quantity': raw})
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, Decimal('5'))
        add = reverse('orders:project_add_item', args=[self.variant.pk])
        self.client.post(add, {'project': str(self.project.public_id), 'quantity': '-4'})
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, Decimal('5'))

    def test_shared_link_is_read_only(self):
        self.project.is_shared = True
        self.project.save()
        shared = reverse('orders:project_shared', args=[self.project.public_id])
        response = self.client.get(shared)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['owner'])
        self.assertNotContains(response, reverse('orders:project_update', args=[self.project.public_id]))
        self.assertNotContains(response, 'csrfmiddlewaretoken')
        self.assertEqual(self.client.post(shared).status_code, 405)
        # A logged-in stranger with the shared link still cannot reach owner endpoints.
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('orders:project_detail', args=[self.project.public_id])).status_code, 404)

    def test_project_mutations_require_csrf_and_post(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        update = reverse('orders:project_update', args=[self.project.public_id])
        self.assertEqual(client.post(update, {'action': 'delete'}).status_code, 403)
        self.assertEqual(client.get(update, {'action': 'delete'}).status_code, 405)
        self.assertEqual(client.post(reverse('orders:project_list'), {'title': 'x'}).status_code, 403)
        self.assertTrue(ProjectList.objects.filter(pk=self.project.pk).exists())
