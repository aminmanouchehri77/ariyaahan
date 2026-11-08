"""Bank-independent payment bookkeeping for the future SEP adapter.

This module deliberately does not make HTTP requests to SEP. The bank's API
contract, test credentials, amount unit, and callback rules are still pending.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Order, OrderItem, PaymentRecord


class PaymentUnavailable(Exception):
    """Raised when an online payment cannot safely be started."""


class PaymentStateConflict(Exception):
    """Raised when a payment callback conflicts with stored transaction state."""


def _order_total_for_payment(order):
    lines = list(OrderItem.objects.filter(order=order).values('line_total', 'currency'))
    if not lines or order.shipping_amount is None:
        raise ValidationError('Order lines and confirmed shipping amount are required before payment.')
    if any(line['currency'] != order.currency for line in lines):
        raise ValidationError('All order lines must use the order currency.')

    total = sum((line['line_total'] for line in lines), Decimal('0')) + order.shipping_amount
    if total <= 0:
        raise ValidationError('The payable order total must be positive.')
    return total


@transaction.atomic
def create_payment_attempt(order_id):
    """Create or return a local attempt; this does not contact the payment bank."""
    if not settings.PAYMENT_ENABLED:
        raise PaymentUnavailable('Online payment is disabled in this environment.')
    if settings.PAYMENT_PROVIDER != 'sep' or not settings.SEP_INTEGRATION_READY:
        raise PaymentUnavailable('The SEP adapter is not ready for bank requests.')

    order = Order.objects.select_for_update().get(pk=order_id)
    if order.status != Order.Status.AWAITING_PAYMENT:
        raise PaymentUnavailable('Only unpaid orders can start a payment attempt.')

    existing = PaymentRecord.objects.filter(
        order=order,
        provider='sep',
        status=PaymentRecord.Status.INITIATED,
    ).first()
    if existing:
        return existing

    return PaymentRecord.objects.create(
        order=order,
        amount=_order_total_for_payment(order),
        currency=order.currency,
        provider='sep',
    )


@transaction.atomic
def record_verified_sep_success(
    payment_id,
    *,
    amount,
    currency,
    provider_reference,
    response_code='',
):
    """Record success only after a future SEP adapter verifies it server-side.

    The adapter must call SEP's official verification operation before calling
    this function. A return/callback parameter from the customer's browser is
    not verification evidence.
    """
    payment = PaymentRecord.objects.select_for_update().get(pk=payment_id)
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    amount = Decimal(str(amount))
    provider_reference = str(provider_reference).strip()[:120]
    response_code = str(response_code).strip()[:40]

    if payment.status == PaymentRecord.Status.SUCCEEDED:
        if (
            payment.amount == amount
            and payment.currency == currency
            and payment.reference == provider_reference
        ):
            return payment
        raise PaymentStateConflict('A repeated success callback does not match the recorded transaction.')

    if (
        payment.provider != 'sep'
        or payment.status not in {PaymentRecord.Status.INITIATED, PaymentRecord.Status.REQUIRES_REVIEW}
        or not provider_reference
    ):
        raise PaymentStateConflict('The payment is not eligible for verified success.')

    if amount != payment.amount or currency != payment.currency:
        payment.status = PaymentRecord.Status.REQUIRES_REVIEW
        payment.provider_response_code = response_code
        payment.failure_reason = 'Verified amount or currency does not match the order.'
        payment.completed_at = timezone.now()
        payment.save(update_fields=(
            'status', 'provider_response_code', 'failure_reason', 'completed_at', 'updated_at',
        ))
        return payment

    if order.status != Order.Status.AWAITING_PAYMENT:
        payment.status = PaymentRecord.Status.REQUIRES_REVIEW
        payment.provider_response_code = response_code
        payment.failure_reason = 'The order is no longer awaiting payment.'
        payment.completed_at = timezone.now()
        payment.save(update_fields=(
            'status', 'provider_response_code', 'failure_reason', 'completed_at', 'updated_at',
        ))
        return payment

    if order.payments.filter(status=PaymentRecord.Status.SUCCEEDED).exclude(pk=payment.pk).exists():
        payment.status = PaymentRecord.Status.REQUIRES_REVIEW
        payment.provider_response_code = response_code
        payment.failure_reason = 'Another payment for this order is already recorded as successful.'
        payment.completed_at = timezone.now()
        payment.save(update_fields=(
            'status', 'provider_response_code', 'failure_reason', 'completed_at', 'updated_at',
        ))
        return payment

    now = timezone.now()
    payment.status = PaymentRecord.Status.SUCCEEDED
    payment.reference = provider_reference
    payment.provider_response_code = response_code
    payment.failure_reason = ''
    payment.verified_at = now
    payment.completed_at = now
    payment.save(update_fields=(
        'status', 'reference', 'provider_response_code', 'failure_reason',
        'verified_at', 'completed_at', 'updated_at',
    ))
    order.set_status(Order.Status.PAID, note='SEP payment verified server-side.')
    return payment


@transaction.atomic
def record_sep_failure(payment_id, *, response_code=''):
    """Record a definitive provider failure without retaining raw provider payloads."""
    payment = PaymentRecord.objects.select_for_update().get(pk=payment_id)
    if payment.provider != 'sep' or payment.status != PaymentRecord.Status.INITIATED:
        raise PaymentStateConflict('Only an initiated SEP payment can be marked failed.')

    payment.status = PaymentRecord.Status.FAILED
    payment.provider_response_code = str(response_code).strip()[:40]
    payment.failure_reason = 'SEP reported an unsuccessful transaction.'
    payment.completed_at = timezone.now()
    payment.save(update_fields=(
        'status', 'provider_response_code', 'failure_reason', 'completed_at', 'updated_at',
    ))
    return payment
