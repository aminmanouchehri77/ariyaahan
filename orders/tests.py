from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomerProfile
from catalog.models import Category, Product, ProductVariant

from .models import Order, OrderItem, PaymentRecord, PreInvoice
from .payment_services import (
    PaymentUnavailable,
    handle_sep_callback,
    payment_block_reason,
    start_sep_payment,
)
from .sep import SEPClient, SEPError, SEPTransportError, VerifyResult

SEP_SETTINGS = dict(
    PAYMENT_ENABLED=True,
    PAYMENT_PROVIDER='sep',
    SEP_TERMINAL_ID='12345678',
    PUBLIC_SITE_URL='https://aria.example',
    ALLOWED_HOSTS=['testserver', 'aria.example'],
)


def verify_result(*, success=True, code=0, amount=Decimal('1200000'), ref='REF-1'):
    return VerifyResult(
        success=success, result_code=code, original_amount=amount, affective_amount=amount,
        ref_num=ref, trace_no='T1', rrn='R1', masked_pan='6037-99**-****-1234', terminal_number='12345678',
    )


class FakeClient:
    def __init__(self, *, verify=None, reverse=None, token='TOKEN-1', token_error=None):
        self._verify = verify or verify_result()
        self._reverse = reverse or verify_result()
        self.token = token
        self.token_error = token_error
        self.calls = []

    def request_token(self, **kwargs):
        self.calls.append(('token', kwargs))
        if self.token_error:
            raise self.token_error
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


@override_settings(**SEP_SETTINGS)
class SEPPaymentFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('customer')
        self.profile = CustomerProfile.objects.create(user=self.user, mobile='09120000000', full_name='مشتری')
        category = Category.objects.create(name='تست', slug='test-cat')
        product = Product.objects.create(category=category, name='میلگرد', slug='rebar-test')
        self.variant = ProductVariant.objects.create(product=product, name='۱۲', unit='kg')
        preinvoice = PreInvoice.objects.create(customer=self.profile, customer_name='مشتری', mobile='09120000000')
        self.order = Order.objects.create(
            preinvoice=preinvoice, customer=self.profile, currency='IRT', shipping_amount=Decimal('20000'),
        )
        OrderItem.objects.create(
            order=self.order, variant=self.variant, product_name='میلگرد', variant_name='۱۲',
            quantity=Decimal('1000'), quantity_unit='kg', unit_price=Decimal('100'),
            currency='IRT', price_basis='kg', line_total=Decimal('100000'),
        )
        # Total 120,000 Toman = 1,200,000 Rial.

    def _start(self, client=None):
        client = client or FakeClient()
        payment, action, fields = start_sep_payment(
            self.order.pk, callback_url='https://aria.example/payment/sep/callback/', client=client,
        )
        return payment, client

    def test_token_request_uses_rial_amount_and_res_num(self):
        payment, client = self._start()
        kind, kwargs = client.calls[0]
        self.assertEqual(kind, 'token')
        self.assertEqual(kwargs['amount_rial'], Decimal('1200000'))
        self.assertEqual(kwargs['res_num'], payment.res_num)
        self.assertEqual(payment.amount, Decimal('120000'))

    def test_successful_callback_verifies_and_marks_order_paid(self):
        payment, _ = self._start()
        client = FakeClient()
        result = handle_sep_callback({'ResNum': payment.res_num, 'State': 'OK', 'RefNum': 'REF-1', 'TerminalId': '12345678'}, client=client)
        self.assertEqual(result.status, PaymentRecord.Status.SUCCEEDED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        # Duplicate callbacks are idempotent and do not verify again.
        again = handle_sep_callback({'ResNum': payment.res_num, 'State': 'OK', 'RefNum': 'REF-1'}, client=client)
        self.assertEqual(again.status, PaymentRecord.Status.SUCCEEDED)
        self.assertEqual([c[0] for c in client.calls], ['verify'])

    def test_cancelled_by_user_marks_failed_without_verify(self):
        payment, _ = self._start()
        client = FakeClient()
        result = handle_sep_callback({'ResNum': payment.res_num, 'State': 'CanceledByUser'}, client=client)
        self.assertEqual(result.status, PaymentRecord.Status.FAILED)
        self.assertEqual(client.calls, [])

    def test_amount_mismatch_is_reversed(self):
        payment, _ = self._start()
        client = FakeClient(verify=verify_result(amount=Decimal('1000')))
        result = handle_sep_callback({'ResNum': payment.res_num, 'State': 'OK', 'RefNum': 'REF-1'}, client=client)
        self.assertEqual(result.status, PaymentRecord.Status.REVERSED)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.AWAITING_PAYMENT)

    def test_second_payment_for_paid_order_is_reversed(self):
        first, _ = self._start()
        second, _ = self._start()
        first.refresh_from_db()
        self.assertEqual(first.status, PaymentRecord.Status.CANCELLED)  # superseded
        handle_sep_callback({'ResNum': second.res_num, 'State': 'OK', 'RefNum': 'REF-2'},
                            client=FakeClient(verify=verify_result(ref='REF-2')))
        late = handle_sep_callback({'ResNum': first.res_num, 'State': 'OK', 'RefNum': 'REF-1'}, client=FakeClient())
        self.assertEqual(late.status, PaymentRecord.Status.REVERSED)

    def test_verify_timeout_requires_review(self):
        payment, _ = self._start()
        client = FakeClient(verify=SEPTransportError('timeout'))
        result = handle_sep_callback({'ResNum': payment.res_num, 'State': 'OK', 'RefNum': 'REF-1'}, client=client)
        self.assertEqual(result.status, PaymentRecord.Status.REQUIRES_REVIEW)

    def test_ref_num_cannot_settle_two_payments(self):
        first, _ = self._start()
        handle_sep_callback({'ResNum': first.res_num, 'State': 'OK', 'RefNum': 'REF-1'}, client=FakeClient())
        other_pre = PreInvoice.objects.create(customer=self.profile, customer_name='م', mobile='09120000000')
        other = Order.objects.create(preinvoice=other_pre, customer=self.profile, currency='IRR', shipping_amount=Decimal('0'))
        OrderItem.objects.create(order=other, product_name='x', variant_name='y', quantity=1, quantity_unit='kg',
                                 unit_price=1200000, currency='IRR', price_basis='kg', line_total=1200000)
        payment, _, _ = start_sep_payment(other.pk, callback_url='https://aria.example/cb/', client=FakeClient())
        result = handle_sep_callback({'ResNum': payment.res_num, 'State': 'OK', 'RefNum': 'REF-1'}, client=FakeClient())
        self.assertEqual(result.status, PaymentRecord.Status.REQUIRES_REVIEW)

    def test_wrong_terminal_requires_review(self):
        payment, _ = self._start()
        result = handle_sep_callback({'ResNum': payment.res_num, 'State': 'OK', 'RefNum': 'R', 'TerminalId': '999'}, client=FakeClient())
        self.assertEqual(result.status, PaymentRecord.Status.REQUIRES_REVIEW)

    def test_token_failure_marks_attempt_failed(self):
        with self.assertRaises(PaymentUnavailable):
            self._start(FakeClient(token_error=SEPError('no', code='-1')))
        self.assertEqual(PaymentRecord.objects.get().status, PaymentRecord.Status.FAILED)

    def test_unknown_res_num_is_ignored(self):
        self.assertIsNone(handle_sep_callback({'ResNum': 'not-a-uuid', 'State': 'OK'}))

    def test_missing_shipping_blocks_payment(self):
        self.order.shipping_amount = None
        self.order.save()
        self.assertTrue(payment_block_reason(self.order))

    def test_callback_view_is_csrf_exempt_and_redirects_to_result(self):
        payment, _ = self._start()
        with mock.patch('orders.payment_services.SEPClient', return_value=FakeClient()):
            response = self.client_class(enforce_csrf_checks=True).post(
                reverse('orders:sep_callback'),
                {'ResNum': payment.res_num, 'State': 'OK', 'RefNum': 'REF-1'},
            )
        self.assertRedirects(response, reverse('orders:payment_result', kwargs={'key': payment.idempotency_key}),
                             fetch_redirect_response=False)
        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentRecord.Status.SUCCEEDED)

    def test_order_detail_is_owner_only(self):
        url = reverse('orders:order_detail', kwargs={'public_id': self.order.public_id})
        stranger = get_user_model().objects.create_user('stranger')
        CustomerProfile.objects.create(user=stranger, mobile='09121111111')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 200)


@override_settings(**SEP_SETTINGS)
class SEPClientTests(TestCase):
    def test_token_payload_and_verify_parsing(self):
        sent = []

        def transport(url, payload):
            sent.append((url, payload))
            if payload.get('action') == 'token':
                return {'status': 1, 'token': 'abc'}
            return {'ResultCode': 0, 'Success': True, 'TransactionDetail': {
                'RefNum': 'R', 'OrginalAmount': 1200000, 'AffectiveAmount': 1200000, 'StraceNo': '9', 'RRN': '8',
            }}

        client = SEPClient(transport=transport)
        self.assertEqual(client.request_token(amount_rial=1200000, res_num='x', redirect_url='https://a/cb'), 'abc')
        self.assertEqual(sent[0][1]['TerminalId'], '12345678')
        self.assertEqual(sent[0][1]['Amount'], 1200000)
        result = client.verify('R')
        self.assertTrue(result.success)
        self.assertEqual(result.original_amount, Decimal('1200000'))
        self.assertEqual(sent[1][1], {'RefNum': 'R', 'TerminalNumber': 12345678})

    def test_token_rejection_raises(self):
        client = SEPClient(transport=lambda url, payload: {'status': -1, 'errorCode': '5'})
        with self.assertRaises(SEPError):
            client.request_token(amount_rial=1000, res_num='x', redirect_url='https://a/cb')
