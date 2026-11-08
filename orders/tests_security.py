"""Security tests for SEP payments and customer-owned order resources.

The bank is never contacted: SEPClient gets a fake transport, and the
callback view gets a patched client.
"""

import io
import json
import urllib.error
import uuid
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomerProfile
from catalog.models import Category, Product, ProductVariant

from .models import Order, OrderItem, PaymentRecord, PreInvoice
from .payment_services import PaymentUnavailable, handle_sep_callback, start_sep_payment, verify_payment
from .sep import SEPClient, SEPError, SEPTransportError, VerifyResult, _post_json

SEP_SETTINGS = dict(
    PAYMENT_ENABLED=True,
    PAYMENT_PROVIDER='sep',
    SEP_TERMINAL_ID='12345678',
    SEP_VERIFY_RETRIES=1,
    PUBLIC_SITE_URL='https://aria.example',
    ALLOWED_HOSTS=['testserver', 'aria.example'],
)
CALLBACK = 'https://aria.example/payment/sep/callback/'


def verify_result(*, success=True, code=0, amount=Decimal('1200000'), ref='REF-1', terminal='12345678'):
    return VerifyResult(
        success=success, result_code=code, original_amount=amount, affective_amount=amount,
        ref_num=ref, trace_no='T1', rrn='R1', masked_pan='6037-99**-****-1234', terminal_number=terminal,
    )


class FakeClient:
    def __init__(self, *, verify=None, reverse=None, token='TOKEN-1'):
        self._verify = verify if verify is not None else verify_result()
        self._reverse = reverse if reverse is not None else verify_result()
        self.token = token
        self.calls = []

    def request_token(self, **kwargs):
        self.calls.append(('token', kwargs))
        return self.token

    def payment_form_fields(self, token):
        return {'Token': token}

    def verify(self, ref_num):
        self.calls.append(('verify', ref_num))
        if isinstance(self._verify, Exception):
            raise self._verify
        return self._verify

    def reverse(self, ref_num):
        self.calls.append(('reverse', ref_num))
        if isinstance(self._reverse, Exception):
            raise self._reverse
        return self._reverse

    def kinds(self):
        return [kind for kind, _ in self.calls]


class OrderFixture:
    def make_order(self, username='payer', mobile='09120000001', *, currency='IRT', line_total='100000', shipping='20000'):
        user = get_user_model().objects.create_user(username)
        profile = CustomerProfile.objects.create(user=user, mobile=mobile, full_name='مشتری')
        preinvoice = PreInvoice.objects.create(customer=profile, customer_name='مشتری', mobile=mobile)
        order = Order.objects.create(
            preinvoice=preinvoice, customer=profile, currency=currency, shipping_amount=Decimal(shipping),
        )
        OrderItem.objects.create(
            order=order, variant=self.variant, product_name='میلگرد', variant_name='۱۲',
            quantity=Decimal('1000'), quantity_unit='kg', unit_price=Decimal('100'),
            currency=currency, price_basis='kg', line_total=Decimal(line_total),
        )
        return user, order

    def make_variant(self):
        category = Category.objects.create(name='تست', slug='sec-cat')
        product = Product.objects.create(category=category, name='میلگرد', slug='sec-rebar')
        self.variant = ProductVariant.objects.create(product=product, name='۱۲', unit='kg')


def ok_callback(payment, ref='REF-1', **extra):
    return {'ResNum': payment.res_num, 'State': 'OK', 'Status': '2', 'RefNum': ref, 'TerminalId': '12345678', **extra}


@override_settings(**SEP_SETTINGS)
class PaymentTamperingTests(OrderFixture, TestCase):
    def setUp(self):
        self.make_variant()
        self.user, self.order = self.make_order()  # 120,000 Toman = 1,200,000 Rial

    def start(self, order=None):
        payment, _, _ = start_sep_payment((order or self.order).pk, callback_url=CALLBACK, client=FakeClient())
        return payment

    def assert_unpaid(self, order=None):
        order = order or self.order
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.AWAITING_PAYMENT)

    def test_amount_is_converted_toman_to_rial(self):
        payment = self.start()
        self.assertEqual(payment.amount, Decimal('120000'))
        self.assertEqual(payment.amount_rial, Decimal('1200000'))

    def test_verified_amount_lower_than_order_is_reversed(self):
        payment = self.start()
        client = FakeClient(verify=verify_result(amount=Decimal('120000')))  # Toman sent as Rial
        result = handle_sep_callback(ok_callback(payment), client=client)
        self.assertEqual(result.status, PaymentRecord.Status.REVERSED)
        self.assertEqual(client.kinds(), ['verify', 'reverse'])
        self.assert_unpaid()

    def test_missing_verified_amount_is_not_trusted(self):
        payment = self.start()
        client = FakeClient(verify=verify_result(amount=None))
        result = handle_sep_callback(ok_callback(payment), client=client)
        self.assertEqual(result.status, PaymentRecord.Status.REVERSED)
        self.assert_unpaid()

    def test_failed_reversal_of_mismatch_requires_review(self):
        payment = self.start()
        client = FakeClient(verify=verify_result(amount=Decimal('1')), reverse=SEPTransportError('down'))
        result = handle_sep_callback(ok_callback(payment), client=client)
        self.assertEqual(result.status, PaymentRecord.Status.REQUIRES_REVIEW)
        self.assert_unpaid()

    def test_callback_amount_fields_are_ignored(self):
        payment = self.start()
        client = FakeClient(verify=verify_result(amount=Decimal('1000')))
        handle_sep_callback(ok_callback(payment, Amount='1200000', AffectiveAmount='1200000'), client=client)
        self.assert_unpaid()

    def test_verified_terminal_mismatch_is_reversed(self):
        payment = self.start()
        result = handle_sep_callback(ok_callback(payment), client=FakeClient(verify=verify_result(terminal='999')))
        self.assertEqual(result.status, PaymentRecord.Status.REVERSED)
        self.assert_unpaid()

    def test_state_ok_without_successful_verify_does_not_pay(self):
        for verify in (verify_result(success=False, code=-2), SEPError('bad', code='HTTP500'), SEPTransportError('t')):
            with self.subTest(verify=verify):
                payment = self.start()
                result = handle_sep_callback(ok_callback(payment, ref=f'R-{uuid.uuid4().hex}'), client=FakeClient(verify=verify))
                self.assertIn(result.status, {PaymentRecord.Status.FAILED, PaymentRecord.Status.REQUIRES_REVIEW})
                self.assert_unpaid()
        self.assertEqual(
            PaymentRecord.objects.filter(status=PaymentRecord.Status.REQUIRES_REVIEW).count(), 2,
        )

    def test_non_ok_state_is_not_verified_and_not_paid(self):
        payment = self.start()
        client = FakeClient()
        result = handle_sep_callback({'ResNum': payment.res_num, 'State': 'Failed', 'RefNum': 'REF-1'}, client=client)
        self.assertEqual(result.status, PaymentRecord.Status.FAILED)
        self.assertEqual(client.calls, [])
        self.assert_unpaid()

    def test_replayed_callback_is_idempotent(self):
        payment = self.start()
        client = FakeClient()
        for _ in range(3):
            result = handle_sep_callback(ok_callback(payment), client=client)
            self.assertEqual(result.status, PaymentRecord.Status.SUCCEEDED)
        self.assertEqual(client.kinds(), ['verify'])
        self.assertEqual(self.order.status_events.filter(to_status=Order.Status.PAID).count(), 1)

    def test_one_ref_num_cannot_pay_two_orders(self):
        first = self.start()
        handle_sep_callback(ok_callback(first), client=FakeClient())
        _, other_order = self.make_order('payer2', '09120000002')
        second = self.start(other_order)
        client = FakeClient()
        result = handle_sep_callback(ok_callback(second), client=client)
        self.assertEqual(result.status, PaymentRecord.Status.REQUIRES_REVIEW)
        self.assertEqual(client.calls, [])
        self.assert_unpaid(other_order)

    def test_different_ref_num_on_same_attempt_requires_review(self):
        payment = self.start()
        handle_sep_callback(ok_callback(payment, ref='REF-A'), client=FakeClient(verify=SEPTransportError('t')))
        result = handle_sep_callback(ok_callback(payment, ref='REF-B'), client=FakeClient())
        self.assertEqual(result.status, PaymentRecord.Status.REQUIRES_REVIEW)
        self.assertEqual(result.ref_num, 'REF-A')
        self.assert_unpaid()

    def test_forged_callback_unknown_res_num(self):
        self.start()
        for res_num in ('', 'x' * 500, uuid.uuid4().hex, str(self.order.public_id), '../../etc'):
            self.assertIsNone(handle_sep_callback({'ResNum': res_num, 'State': 'OK', 'RefNum': 'F'}, client=FakeClient()))
        self.assert_unpaid()
        self.assertFalse(PaymentRecord.objects.exclude(status=PaymentRecord.Status.INITIATED).exists())

    def test_paid_order_second_attempt_is_blocked_and_late_payment_reversed(self):
        stale = self.start()
        fresh = self.start()
        handle_sep_callback(ok_callback(fresh, ref='REF-2'), client=FakeClient(verify=verify_result(ref='REF-2')))
        with self.assertRaises(PaymentUnavailable):
            self.start()
        late = handle_sep_callback(ok_callback(stale), client=FakeClient())
        self.assertEqual(late.status, PaymentRecord.Status.REVERSED)

    def test_cancelled_order_cannot_start_or_settle_payment(self):
        payment = self.start()
        self.order.set_status(Order.Status.CANCELLED)
        with self.assertRaises(PaymentUnavailable):
            self.start()
        result = handle_sep_callback(ok_callback(payment), client=FakeClient())
        self.assertEqual(result.status, PaymentRecord.Status.REVERSED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)

    def test_late_attempt_after_shipping_change_is_reversed(self):
        stale = self.start()
        self.order.shipping_amount = Decimal('50000')
        self.order.save(update_fields=('shipping_amount',))
        # The bank verifies exactly what the stale attempt asked for.
        result = handle_sep_callback(ok_callback(stale), client=FakeClient())
        self.assertEqual(result.status, PaymentRecord.Status.REVERSED)
        self.assert_unpaid()

    def test_reverify_after_review_can_succeed_once(self):
        payment = self.start()
        handle_sep_callback(ok_callback(payment), client=FakeClient(verify=SEPTransportError('t')))
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentRecord.Status.REQUIRES_REVIEW)
        self.assertEqual(verify_payment(payment.pk, client=FakeClient()).status, PaymentRecord.Status.SUCCEEDED)
        client = FakeClient()
        self.assertEqual(verify_payment(payment.pk, client=client).status, PaymentRecord.Status.SUCCEEDED)
        self.assertEqual(client.calls, [])

    @override_settings(PAYMENT_ENABLED=False)
    def test_payment_disabled_blocks_attempts(self):
        with self.assertRaises(PaymentUnavailable):
            self.start()
        self.assertFalse(PaymentRecord.objects.exists())

    def test_http_callback_url_is_refused(self):
        with self.assertRaises(PaymentUnavailable):
            start_sep_payment(self.order.pk, callback_url='http://aria.example/payment/sep/callback/', client=FakeClient())
        self.assertFalse(PaymentRecord.objects.exists())

    def test_usd_order_cannot_pay(self):
        _, order = self.make_order('usd', '09120000003', currency='USD')
        with self.assertRaises(Exception):
            self.start(order)
        self.assertFalse(PaymentRecord.objects.filter(order=order).exists())


@override_settings(**SEP_SETTINGS)
class PaymentViewTests(OrderFixture, TestCase):
    def setUp(self):
        self.make_variant()
        self.user, self.order = self.make_order()
        self.other, self.other_order = self.make_order('other', '09120000009')
        self.detail = reverse('orders:order_detail', args=[self.order.public_id])
        self.pay = reverse('orders:order_pay', args=[self.order.public_id])

    def post_pay(self, client=None, url=None):
        fake = FakeClient()
        with mock.patch('orders.payment_services.SEPClient', return_value=fake):
            return (client or self.client).post(url or self.pay), fake

    def test_owner_pay_renders_gateway_form_with_https_callback(self):
        self.client.force_login(self.user)
        response, fake = self.post_pay()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="Token" value="TOKEN-1"')
        self.assertEqual(fake.calls[0][1]['redirect_url'], CALLBACK)
        self.assertEqual(fake.calls[0][1]['amount_rial'], Decimal('1200000'))
        self.assertIn('no-store', response['Cache-Control'])

    def test_anonymous_and_other_user_cannot_view_or_pay(self):
        self.assertEqual(self.client.get(self.detail).status_code, 302)
        self.assertEqual(self.post_pay()[0].status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.detail).status_code, 404)
        response, fake = self.post_pay()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(fake.calls, [])
        self.assertFalse(PaymentRecord.objects.filter(order=self.order).exists())
        # Guessed identifiers.
        self.assertEqual(self.client.get(reverse('orders:order_detail', args=[uuid.uuid4()])).status_code, 404)
        self.assertEqual(self.client.get(f'/account/orders/{self.order.pk}/').status_code, 404)

    def test_staff_without_profile_cannot_use_customer_order_page(self):
        staff = get_user_model().objects.create_user('staffer', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.detail).status_code, 404)

    def test_pay_requires_csrf_and_post(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(self.post_pay(client)[0].status_code, 403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.pay).status_code, 405)
        self.assertFalse(PaymentRecord.objects.exists())

    @override_settings(PAYMENT_ENABLED=False)
    def test_pay_view_blocked_when_disabled(self):
        self.client.force_login(self.user)
        response, fake = self.post_pay()
        self.assertRedirects(response, self.detail, fetch_redirect_response=False)
        self.assertEqual(fake.calls, [])
        self.assertFalse(PaymentRecord.objects.exists())

    def test_pay_view_blocked_for_paid_or_cancelled(self):
        self.client.force_login(self.user)
        for status in (Order.Status.PAID, Order.Status.CANCELLED):
            Order.objects.filter(pk=self.order.pk).update(status=status)
            response, fake = self.post_pay()
            self.assertEqual(response.status_code, 302)
            self.assertEqual(fake.calls, [])
        self.assertFalse(PaymentRecord.objects.exists())

    @override_settings(PUBLIC_SITE_URL='')
    def test_pay_view_refuses_plain_http_callback(self):
        self.client.force_login(self.user)
        response, fake = self.post_pay()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(fake.calls, [])
        self.assertFalse(PaymentRecord.objects.exists())

    def _started_payment(self):
        payment, _, _ = start_sep_payment(self.order.pk, callback_url=CALLBACK, client=FakeClient())
        return payment

    def test_callback_get_never_changes_state(self):
        payment = self._started_payment()
        with mock.patch('orders.payment_services.SEPClient', return_value=FakeClient()) as patched:
            response = self.client.get(reverse('orders:sep_callback'), ok_callback(payment))
        self.assertEqual(response.status_code, 302)
        patched.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentRecord.Status.INITIATED)

    def test_callback_post_without_csrf_and_forged_values(self):
        payment = self._started_payment()
        csrf_client = Client(enforce_csrf_checks=True)
        fake = FakeClient(verify=verify_result(success=False, code=-2))
        with mock.patch('orders.payment_services.SEPClient', return_value=fake):
            response = csrf_client.post(reverse('orders:sep_callback'), ok_callback(payment))
        self.assertRedirects(response, reverse('orders:payment_result', args=[payment.idempotency_key]),
                             fetch_redirect_response=False)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_PAYMENT)
        with mock.patch('orders.payment_services.SEPClient', return_value=FakeClient()):
            response = csrf_client.post(reverse('orders:sep_callback'), {'ResNum': 'nope', 'State': 'OK', 'RefNum': 'X'})
        self.assertRedirects(response, reverse('core:home'), fetch_redirect_response=False)

    def test_payment_result_does_not_link_other_users_order(self):
        payment = self._started_payment()
        url = reverse('orders:payment_result', args=[payment.idempotency_key])
        self.client.force_login(self.other)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['order_url'], '')
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).context['order_url'], self.detail)
        self.assertEqual(self.client.get(reverse('orders:payment_result', args=[uuid.uuid4()])).status_code, 404)


class FakeHTTPResponse(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@override_settings(**SEP_SETTINGS)
class SEPTransportTests(TestCase):
    def urlopen_returning(self, body, status=200):
        return mock.patch('orders.sep.urllib.request.urlopen', return_value=FakeHTTPResponse(body, status))

    def test_timeout_and_connection_errors_are_transport_errors(self):
        for error in (TimeoutError(), urllib.error.URLError('dns'), ConnectionResetError()):
            with self.subTest(error=error), mock.patch('orders.sep.urllib.request.urlopen', side_effect=error):
                with self.assertRaises(SEPTransportError):
                    _post_json('https://sep.example/x', {})

    def test_http_error_is_definite_sep_error(self):
        error = urllib.error.HTTPError('https://sep.example/x', 500, 'err', {}, io.BytesIO(b''))
        with mock.patch('orders.sep.urllib.request.urlopen', side_effect=error):
            with self.assertRaises(SEPError) as ctx:
                _post_json('https://sep.example/x', {})
        self.assertNotIsInstance(ctx.exception, SEPTransportError)
        self.assertEqual(ctx.exception.code, 'HTTP500')

    def test_garbage_and_oversized_responses(self):
        for body in (b'<html>', b'\xff\xfe', b'{' * 70000):
            with self.subTest(body=body[:10]), self.urlopen_returning(body):
                with self.assertRaises(SEPError):
                    _post_json('https://sep.example/x', {})

    def test_verify_retries_only_on_transport_errors(self):
        good = {'ResultCode': 0, 'Success': True, 'TransactionDetail': {'OrginalAmount': '1200000', 'RefNum': 'R'}}
        transport = mock.Mock(side_effect=[SEPTransportError('t'), good])
        with mock.patch('orders.sep.time.sleep'):
            result = SEPClient(transport=transport).verify('R')
        self.assertTrue(result.success)
        self.assertEqual(transport.call_count, 2)
        transport = mock.Mock(side_effect=SEPTransportError('t'))
        with mock.patch('orders.sep.time.sleep'), self.assertRaises(SEPTransportError):
            SEPClient(transport=transport).verify('R')
        self.assertEqual(transport.call_count, 2)  # SEP_VERIFY_RETRIES=1
        transport = mock.Mock(side_effect=SEPError('no', code='HTTP400'))
        with self.assertRaises(SEPError):
            SEPClient(transport=transport).verify('R')
        self.assertEqual(transport.call_count, 1)

    def test_verify_requires_strict_success_and_integral_amount(self):
        def client(data):
            return SEPClient(transport=lambda url, payload: data)
        self.assertFalse(client({'ResultCode': 0, 'Success': 'true'}).verify('R').success)
        self.assertFalse(client({'ResultCode': 2, 'Success': True}).verify('R').success)
        with self.assertRaises(SEPError):
            client({'Success': True}).verify('R')
        with self.assertRaises(SEPError):
            client(['not', 'a', 'dict']).verify('R')
        result = client({'ResultCode': 0, 'Success': True, 'TransactionDetail': {'OrginalAmount': '1199999.6'}}).verify('R')
        self.assertIsNone(result.original_amount)
        result = client({'ResultCode': 0, 'Success': True, 'TransactionDetail': 'oops'}).verify('R')
        self.assertIsNone(result.original_amount)

    def test_token_payload_is_json_and_rejects_non_positive_amount(self):
        with self.urlopen_returning(json.dumps({'status': 1, 'token': 'T'}).encode()) as urlopen:
            self.assertEqual(SEPClient().request_token(amount_rial=1200000, res_num='abc', redirect_url=CALLBACK), 'T')
        request = urlopen.call_args[0][0]
        self.assertEqual(json.loads(request.data)['Amount'], 1200000)
        for amount in (0, -10):
            with self.assertRaises(SEPError):
                SEPClient(transport=mock.Mock()).request_token(amount_rial=amount, res_num='a', redirect_url=CALLBACK)

    @override_settings(SEP_TERMINAL_ID='')
    def test_client_requires_terminal(self):
        with self.assertRaises(SEPError):
            SEPClient()
