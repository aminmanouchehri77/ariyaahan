"""Payment orchestration for the SEP gateway.

Rules enforced here:
* Only an order in ``awaiting_payment`` with confirmed lines and shipping can pay.
* The gateway amount is always derived from the stored order snapshot, in Rial.
* A browser callback is never proof of payment: success is recorded only after
  SEP's server-side VerifyTransaction returns ResultCode 0 with the same amount.
* A verified payment that cannot be applied (amount mismatch, order already paid
  or cancelled) is reversed automatically; if reversal fails it is flagged for
  staff review instead of being silently accepted.
* Callbacks are idempotent and each SEP ``RefNum`` can settle only one record.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Order, OrderItem, PaymentRecord
from .sep import CALLBACK_STATE_MESSAGES, SEPClient, SEPError, SEPTransportError

RIAL_FACTORS = {'IRR': Decimal('1'), 'IRT': Decimal('10')}


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


def order_totals(order):
    """Return a display dictionary (subtotal, shipping, total, rial amount) or None."""
    lines = list(order.items.all())
    if not lines or any(line.currency != order.currency for line in lines):
        return None
    subtotal = sum((line.line_total for line in lines), Decimal('0'))
    total = subtotal + order.shipping_amount if order.shipping_amount is not None else None
    factor = RIAL_FACTORS.get(order.currency)
    return {
        'subtotal': subtotal,
        'shipping': order.shipping_amount,
        'total': total,
        'currency': order.currency,
        'total_rial': total * factor if total is not None and factor else None,
    }


def payment_block_reason(order):
    """Return '' when the order can be paid online now, otherwise a Persian reason."""
    if not settings.PAYMENT_ENABLED or settings.PAYMENT_PROVIDER != 'sep':
        return 'پرداخت آنلاین هنوز فعال نشده است؛ برای پرداخت با کارشناس فروش هماهنگ کنید.'
    if order.status != Order.Status.AWAITING_PAYMENT:
        return 'این سفارش در وضعیت پرداخت نیست.'
    if order.shipping_amount is None:
        return 'هزینهٔ حمل هنوز توسط کارشناس تأیید نشده است.'
    if order.currency not in RIAL_FACTORS:
        return 'پرداخت آنلاین فقط برای سفارش‌های ریالی امکان‌پذیر است.'
    try:
        _order_total_for_payment(order)
    except ValidationError:
        return 'مبلغ سفارش برای پرداخت آماده نیست.'
    return ''


def _rial_amount(order, amount):
    factor = RIAL_FACTORS.get(order.currency)
    if factor is None:
        raise ValidationError('Online payment supports only IRR/IRT orders.')
    return (amount * factor).quantize(Decimal('1'))


def _mark(payment, status, *, reason='', code=None, **fields):
    payment.status = status
    payment.failure_reason = reason[:250]
    if code is not None:
        payment.provider_response_code = str(code)[:40]
    payment.completed_at = timezone.now()
    for name, value in fields.items():
        setattr(payment, name, value)
    payment.save(update_fields=(
        'status', 'failure_reason', 'provider_response_code', 'completed_at', 'updated_at', *fields.keys(),
    ))
    return payment


@transaction.atomic
def create_payment_attempt(order_id):
    """Create a fresh local attempt for an unpaid order (no bank contact)."""
    if not settings.PAYMENT_ENABLED:
        raise PaymentUnavailable('Online payment is disabled in this environment.')
    if settings.PAYMENT_PROVIDER != 'sep' or not settings.SEP_INTEGRATION_READY:
        raise PaymentUnavailable('The SEP adapter is not ready for bank requests.')

    order = Order.objects.select_for_update().get(pk=order_id)
    if order.status != Order.Status.AWAITING_PAYMENT:
        raise PaymentUnavailable('Only unpaid orders can start a payment attempt.')
    if order.payments.filter(status=PaymentRecord.Status.SUCCEEDED).exists():
        raise PaymentUnavailable('This order already has a successful payment.')

    amount = _order_total_for_payment(order)
    now = timezone.now()
    # A new attempt supersedes earlier unfinished ones. Their late callbacks are
    # still verified, and reversed if this attempt has already paid the order.
    PaymentRecord.objects.filter(
        order=order, provider='sep', status=PaymentRecord.Status.INITIATED,
    ).update(
        status=PaymentRecord.Status.CANCELLED,
        failure_reason='Superseded by a newer payment attempt.',
        completed_at=now,
        updated_at=now,
    )
    return PaymentRecord.objects.create(
        order=order,
        amount=amount,
        amount_rial=_rial_amount(order, amount),
        currency=order.currency,
        provider='sep',
        expires_at=now + timedelta(minutes=settings.SEP_TOKEN_EXPIRY_MINUTES),
    )


def start_sep_payment(order_id, *, callback_url, cell_number='', client=None):
    """Create an attempt and obtain a SEP token. Returns (payment, form_action, fields)."""
    if not str(callback_url).startswith('https://'):
        raise PaymentUnavailable('The bank callback address must use HTTPS.')
    payment = create_payment_attempt(order_id)
    try:
        client = client or SEPClient()
        token = client.request_token(
            amount_rial=payment.amount_rial,
            res_num=payment.res_num,
            redirect_url=callback_url,
            cell_number=cell_number,
        )
    except SEPError as error:
        _mark(payment, PaymentRecord.Status.FAILED, reason='SEP did not issue a payment token.', code=error.code)
        raise PaymentUnavailable(str(error)) from None
    return payment, settings.SEP_PAYMENT_URL, client.payment_form_fields(token)


def _find_payment_for_res_num(res_num):
    try:
        key = uuid.UUID(hex=str(res_num).strip())
    except (ValueError, AttributeError, TypeError):
        return None
    return PaymentRecord.objects.filter(idempotency_key=key, provider='sep').first()


def handle_sep_callback(data, *, client=None):
    """Process SEP's browser callback and return the PaymentRecord (or None).

    ``data`` is the POST/GET mapping sent by SEP. Values are untrusted.
    """
    payment = _find_payment_for_res_num(data.get('ResNum', ''))
    if payment is None:
        return None

    terminal = str(data.get('TerminalId') or data.get('MID') or '').strip()
    state = str(data.get('State') or '').strip()
    status_value = str(data.get('Status') or '').strip()
    ref_num = str(data.get('RefNum') or '').strip()[:120]

    with transaction.atomic():
        payment = PaymentRecord.objects.select_for_update().get(pk=payment.pk)
        if payment.status in {PaymentRecord.Status.SUCCEEDED, PaymentRecord.Status.REVERSED}:
            return payment
        if terminal and terminal != settings.SEP_TERMINAL_ID:
            if payment.status in {PaymentRecord.Status.INITIATED, PaymentRecord.Status.CANCELLED}:
                _mark(payment, PaymentRecord.Status.REQUIRES_REVIEW, reason='Callback terminal does not match.', code=state)
            return payment
        if state != 'OK' or not ref_num:
            if payment.status == PaymentRecord.Status.INITIATED:
                _mark(
                    payment, PaymentRecord.Status.FAILED,
                    reason=CALLBACK_STATE_MESSAGES.get(state, 'SEP reported an unsuccessful transaction.'),
                    code=state or status_value,
                )
            return payment
        if payment.ref_num and payment.ref_num != ref_num:
            _mark(payment, PaymentRecord.Status.REQUIRES_REVIEW, reason='A different RefNum was already recorded.', code=state)
            return payment
        if PaymentRecord.objects.filter(ref_num=ref_num).exclude(pk=payment.pk).exists():
            _mark(payment, PaymentRecord.Status.REQUIRES_REVIEW, reason='RefNum already settled another payment.', code=state)
            return payment
        payment.ref_num = ref_num
        payment.trace_no = str(data.get('TraceNo') or '')[:40]
        payment.rrn = str(data.get('Rrn') or data.get('RRN') or '')[:40]
        payment.masked_pan = str(data.get('SecurePan') or '')[:40]
        try:
            with transaction.atomic():
                payment.save(update_fields=('ref_num', 'trace_no', 'rrn', 'masked_pan', 'updated_at'))
        except IntegrityError:
            payment.refresh_from_db()
            _mark(payment, PaymentRecord.Status.REQUIRES_REVIEW, reason='RefNum already settled another payment.', code=state)
            return payment

    return verify_payment(payment.pk, client=client)


def verify_payment(payment_id, *, client=None):
    """Run SEP verification for a recorded RefNum and apply the outcome."""
    payment = PaymentRecord.objects.get(pk=payment_id)
    if payment.status in {PaymentRecord.Status.SUCCEEDED, PaymentRecord.Status.REVERSED} or not payment.ref_num:
        return payment
    client = client or SEPClient()
    try:
        result = client.verify(payment.ref_num)
    except SEPTransportError:
        with transaction.atomic():
            payment = PaymentRecord.objects.select_for_update().get(pk=payment_id)
            if payment.status != PaymentRecord.Status.SUCCEEDED:
                _mark(
                    payment, PaymentRecord.Status.REQUIRES_REVIEW,
                    reason='Verification got no answer; re-verify from the admin within 30 minutes.',
                )
        return payment
    except SEPError as error:
        with transaction.atomic():
            payment = PaymentRecord.objects.select_for_update().get(pk=payment_id)
            if payment.status != PaymentRecord.Status.SUCCEEDED:
                _mark(payment, PaymentRecord.Status.REQUIRES_REVIEW, reason=str(error), code=error.code)
        return payment

    if not result.success:
        with transaction.atomic():
            payment = PaymentRecord.objects.select_for_update().get(pk=payment_id)
            if payment.status == PaymentRecord.Status.SUCCEEDED:
                return payment
            status = (
                PaymentRecord.Status.REQUIRES_REVIEW if result.result_code == 2
                else PaymentRecord.Status.FAILED
            )
            return _mark(payment, status, reason=result.message, code=result.result_code)

    # The verified amount is mandatory: a missing or different amount is never applied.
    if result.original_amount is None or result.original_amount != payment.amount_rial:
        return _reverse_or_review(payment_id, client, 'Verified amount does not match the order amount.')
    if result.terminal_number and result.terminal_number != str(settings.SEP_TERMINAL_ID):
        return _reverse_or_review(payment_id, client, 'Verified terminal does not match this merchant.')

    try:
        payment = record_verified_sep_success(
            payment_id,
            amount=payment.amount,
            currency=payment.currency,
            provider_reference=result.ref_num or payment.ref_num,
            response_code=str(result.result_code),
            trace_no=result.trace_no,
            rrn=result.rrn,
            masked_pan=result.masked_pan,
        )
    except PaymentStateConflict:
        return _reverse_or_review(payment_id, client, 'Verified payment conflicts with stored state.')
    if payment.status == PaymentRecord.Status.REQUIRES_REVIEW:
        # Order already paid/cancelled or another success exists: refund this one.
        return _reverse_or_review(payment_id, client, payment.failure_reason or 'Payment cannot be applied.')
    return payment


def _reverse_or_review(payment_id, client, reason):
    payment = PaymentRecord.objects.get(pk=payment_id)
    if payment.status == PaymentRecord.Status.SUCCEEDED:
        # Already applied to the order (e.g. a concurrent callback won); never reverse it here.
        return payment
    try:
        result = client.reverse(payment.ref_num)
        reversed_ok = result.success or result.result_code == 5
        code = result.result_code
    except SEPError as error:
        reversed_ok = False
        code = error.code
    with transaction.atomic():
        payment = PaymentRecord.objects.select_for_update().get(pk=payment_id)
        if reversed_ok:
            return _mark(payment, PaymentRecord.Status.REVERSED, reason=f'{reason} Reversed automatically.', code=code)
        return _mark(payment, PaymentRecord.Status.REQUIRES_REVIEW, reason=f'{reason} Automatic reversal failed.', code=code)


def reverse_payment(payment_id, *, client=None, reason='Reversed by staff.'):
    """Staff-initiated reversal of a verified payment (within SEP's window)."""
    payment = PaymentRecord.objects.get(pk=payment_id)
    if not payment.ref_num or payment.status == PaymentRecord.Status.REVERSED:
        raise PaymentStateConflict('Only a payment with a RefNum can be reversed.')
    if payment.status == PaymentRecord.Status.SUCCEEDED:
        raise PaymentStateConflict('Cancel the order first; a payment applied to an order is refunded through settlement.')
    return _reverse_or_review(payment_id, client or SEPClient(), reason)


@transaction.atomic
def record_verified_sep_success(
    payment_id,
    *,
    amount,
    currency,
    provider_reference,
    response_code='',
    trace_no='',
    rrn='',
    masked_pan='',
):
    """Record success only after SEP verified it server-side.

    The caller must have run SEP's official verification before calling this
    function. A return/callback parameter from the customer's browser is not
    verification evidence.
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
        or payment.status not in {
            PaymentRecord.Status.INITIATED,
            PaymentRecord.Status.REQUIRES_REVIEW,
            PaymentRecord.Status.CANCELLED,
        }
        or not provider_reference
    ):
        raise PaymentStateConflict('The payment is not eligible for verified success.')

    if amount != payment.amount or currency != payment.currency:
        return _mark(payment, PaymentRecord.Status.REQUIRES_REVIEW,
                     reason='Verified amount or currency does not match the order.', code=response_code)

    if order.status != Order.Status.AWAITING_PAYMENT:
        return _mark(payment, PaymentRecord.Status.REQUIRES_REVIEW,
                     reason='The order is no longer awaiting payment.', code=response_code)

    # The attempt's amount was captured when it started; staff may have changed
    # shipping since (a superseded attempt can still return late). Only apply a
    # payment that still equals the order's current payable total.
    try:
        current_total = _order_total_for_payment(order)
    except ValidationError:
        current_total = None
    if current_total != payment.amount or order.currency != payment.currency:
        return _mark(payment, PaymentRecord.Status.REQUIRES_REVIEW,
                     reason='The order total changed after this payment attempt started.', code=response_code)

    if order.payments.filter(status=PaymentRecord.Status.SUCCEEDED).exclude(pk=payment.pk).exists():
        return _mark(payment, PaymentRecord.Status.REQUIRES_REVIEW,
                     reason='Another payment for this order is already recorded as successful.', code=response_code)

    now = timezone.now()
    payment.status = PaymentRecord.Status.SUCCEEDED
    payment.reference = provider_reference
    payment.provider_response_code = response_code
    payment.failure_reason = ''
    payment.verified_at = now
    payment.completed_at = now
    update_fields = [
        'status', 'reference', 'provider_response_code', 'failure_reason',
        'verified_at', 'completed_at', 'updated_at',
    ]
    for name, value in (('trace_no', trace_no), ('rrn', rrn), ('masked_pan', masked_pan)):
        if value:
            setattr(payment, name, str(value)[:40])
            update_fields.append(name)
    payment.save(update_fields=update_fields)
    order.set_status(Order.Status.PAID, note='پرداخت سپ با تأیید سمت سرور ثبت شد.')
    return payment


@transaction.atomic
def record_sep_failure(payment_id, *, response_code=''):
    """Record a definitive provider failure without retaining raw provider payloads."""
    payment = PaymentRecord.objects.select_for_update().get(pk=payment_id)
    if payment.provider != 'sep' or payment.status != PaymentRecord.Status.INITIATED:
        raise PaymentStateConflict('Only an initiated SEP payment can be marked failed.')
    return _mark(payment, PaymentRecord.Status.FAILED,
                 reason='SEP reported an unsuccessful transaction.', code=response_code)
