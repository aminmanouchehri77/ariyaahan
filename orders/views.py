from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from catalog.models import ProductVariant
from accounts.models import CustomerProfile
from accounts.services import (
    OTPExpired,
    OTPInvalid,
    OTPRateLimited,
    invalidate_preinvoice_acceptance_codes,
    issue_preinvoice_acceptance_code,
    verify_preinvoice_acceptance_code,
)
from accounts.sms import SMSBackendNotConfigured, SMSDeliveryFailed

from .cart import Cart, CartError
from .forms import AcceptPreInvoiceQuoteForm, CartQuantityForm, PreInvoiceForm
from core.seo import canonical_url
from core.throttle import submission_allowed

from .models import Order, PaymentRecord, PreInvoice, PreInvoiceItem
from .payment_services import (
    PaymentUnavailable,
    handle_sep_callback,
    order_totals,
    payment_block_reason,
    start_sep_payment,
)
from .services import (
    build_cart_context,
    captured_quote_is_current,
    checkout_quote_changes,
    checkout_quote_snapshot,
    snapshot_line,
)


CHECKOUT_QUOTE_SESSION_KEY = 'ariaa_checkout_quote'
CHECKOUT_ACK_SESSION_KEY = 'ariaa_checkout_quote_ack_required'
CHECKOUT_CHANGES_SESSION_KEY = 'ariaa_checkout_quote_changes'
PREINVOICE_ACCEPTANCE_SESSION_KEY = 'ariaa_preinvoice_acceptance'


def _set_checkout_quote_context(context, *, confirmation_required=False, changes=None):
    context['quote_confirmation_required'] = confirmation_required
    context['quote_changes'] = changes or []
    return context


def _remember_checkout_quote(request, snapshot):
    previous = request.session.get(CHECKOUT_QUOTE_SESSION_KEY)
    changes = checkout_quote_changes(previous, snapshot) if previous else []
    confirmation_required = bool(
        request.session.get(CHECKOUT_ACK_SESSION_KEY) or changes
    )
    request.session[CHECKOUT_QUOTE_SESSION_KEY] = snapshot
    if changes:
        request.session[CHECKOUT_ACK_SESSION_KEY] = True
        request.session[CHECKOUT_CHANGES_SESSION_KEY] = changes
    elif not confirmation_required:
        request.session.pop(CHECKOUT_ACK_SESSION_KEY, None)
        request.session.pop(CHECKOUT_CHANGES_SESSION_KEY, None)
    return confirmation_required, request.session.get(CHECKOUT_CHANGES_SESSION_KEY, [])


def _clear_checkout_quote(request):
    request.session.pop(CHECKOUT_QUOTE_SESSION_KEY, None)
    request.session.pop(CHECKOUT_ACK_SESSION_KEY, None)
    request.session.pop(CHECKOUT_CHANGES_SESSION_KEY, None)


@never_cache
@require_GET
def cart_detail(request):
    return render(request, 'orders/cart.html', build_cart_context(request))


@never_cache
@require_POST
def cart_add(request, variant_id):
    variant = get_object_or_404(
        ProductVariant,
        pk=variant_id,
        is_active=True,
        product__is_active=True,
        product__category__is_active=True,
    )
    form = CartQuantityForm(request.POST)
    if form.is_valid():
        try:
            Cart(request).add(variant.pk, form.cleaned_data['quantity'])
            messages.success(request, f'«{variant.product.name} — {variant.name}» به سبد اضافه شد.')
        except CartError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, 'مقدار کالا را بررسی و دوباره تلاش کنید.')
    return redirect('orders:cart')


@never_cache
@require_POST
def cart_update(request, variant_id):
    form = CartQuantityForm(request.POST)
    if form.is_valid():
        try:
            Cart(request).update(variant_id, form.cleaned_data['quantity'])
            messages.success(request, 'مقدار کالا در سبد به‌روز شد.')
        except (CartError, ValueError) as exc:
            messages.error(request, str(exc) or 'به‌روزرسانی سبد انجام نشد.')
    else:
        messages.error(request, 'مقدار واردشده معتبر نیست.')
    return redirect('orders:cart')


@never_cache
@require_POST
def cart_remove(request, variant_id):
    Cart(request).remove(variant_id)
    messages.info(request, 'کالا از سبد حذف شد.')
    return redirect('orders:cart')


@never_cache
@require_GET
def checkout(request):
    context = build_cart_context(request)
    if context['cart_is_empty']:
        messages.warning(request, 'برای ثبت پیش‌فاکتور ابتدا کالایی به سبد اضافه کنید.')
        return redirect('orders:cart')
    profile = CustomerProfile.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    context['form'] = PreInvoiceForm(initial={
        'customer_name': profile.full_name if profile else '',
        'mobile': profile.mobile if profile else '',
    }, addresses=profile.addresses.all() if profile else None)
    confirmation_required, changes = _remember_checkout_quote(request, checkout_quote_snapshot(context))
    return render(request, 'orders/checkout.html', _set_checkout_quote_context(
        context,
        confirmation_required=confirmation_required,
        changes=changes,
    ))


@never_cache
@require_POST
def submit_preinvoice(request):
    context = build_cart_context(request)
    if context['cart_is_empty']:
        messages.warning(request, 'سبد خالی است؛ کالاها را دوباره انتخاب کنید.')
        return redirect('orders:cart')

    profile = CustomerProfile.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    addresses = profile.addresses.all() if profile else None
    form = PreInvoiceForm(request.POST, addresses=addresses)
    current_quote = checkout_quote_snapshot(context)
    previous_quote = request.session.get(CHECKOUT_QUOTE_SESSION_KEY)
    if previous_quote is None:
        messages.warning(request, 'صفحهٔ ثبت درخواست منقضی شده است؛ اقلام و قیمت‌ها را دوباره مرور کنید.')
        return redirect('orders:checkout')
    quote_changes = checkout_quote_changes(previous_quote, current_quote)
    confirmation_required = bool(
        request.session.get(CHECKOUT_ACK_SESSION_KEY) or quote_changes
    )
    if quote_changes:
        request.session[CHECKOUT_QUOTE_SESSION_KEY] = current_quote
        request.session[CHECKOUT_ACK_SESSION_KEY] = True
        request.session[CHECKOUT_CHANGES_SESSION_KEY] = quote_changes
    else:
        quote_changes = request.session.get(CHECKOUT_CHANGES_SESSION_KEY, [])

    if quote_changes:
        form_data = request.POST.copy()
        form_data['price_confirmation'] = ''
        form = PreInvoiceForm(form_data, addresses=addresses)
        form.add_error(None, 'قیمت یا موجودی تغییر کرده است؛ موارد تازه را بررسی و دوباره ثبت کنید.')
        context['form'] = form
        return render(request, 'orders/checkout.html', _set_checkout_quote_context(
            context,
            confirmation_required=True,
            changes=quote_changes,
        ))
    if not form.is_valid():
        context['form'] = form
        return render(request, 'orders/checkout.html', _set_checkout_quote_context(
            context,
            confirmation_required=confirmation_required,
            changes=quote_changes,
        ))
    if confirmation_required and not form.cleaned_data['price_confirmation']:
        form.add_error('price_confirmation', 'برای ادامه، تغییرهای قیمت و موجودی را بررسی و تأیید کنید.')
        context['form'] = form
        return render(request, 'orders/checkout.html', _set_checkout_quote_context(
            context,
            confirmation_required=True,
            changes=quote_changes,
        ))

    selected_address = form.cleaned_data['saved_address']
    address_values = {
        'delivery_recipient': selected_address.recipient if selected_address else form.cleaned_data['delivery_recipient'],
        'delivery_mobile': selected_address.mobile if selected_address else form.cleaned_data['delivery_mobile'],
        'delivery_province': selected_address.province if selected_address else form.cleaned_data['delivery_province'],
        'delivery_postal_code': selected_address.postal_code if selected_address else form.cleaned_data['delivery_postal_code'],
        'delivery_address': selected_address.address if selected_address else form.cleaned_data['delivery_address'],
        'delivery_note': selected_address.delivery_note if selected_address else form.cleaned_data['delivery_note'],
        'delivery_city': selected_address.city if selected_address else form.cleaned_data['delivery_city'],
    }

    late_quote_changes = []
    needs_late_confirmation = False
    cart_became_empty = False
    preinvoice = None
    with transaction.atomic():
        cart = Cart(request)
        variant_ids = sorted(int(variant_id) for variant_id in cart.items)
        list(
            ProductVariant.objects.select_for_update()
            .filter(pk__in=variant_ids)
            .order_by('pk')
        )

        # Price and stock approvals take the same variant lock. Refresh the quote
        # while holding it so an approval cannot slip between the final comparison
        # and the pre-invoice snapshot being written.
        context = build_cart_context(request)
        cart_became_empty = context['cart_is_empty']
        if not cart_became_empty:
            locked_quote = checkout_quote_snapshot(context)
            late_quote_changes = checkout_quote_changes(previous_quote, locked_quote)
            if late_quote_changes:
                request.session[CHECKOUT_QUOTE_SESSION_KEY] = locked_quote
                request.session[CHECKOUT_ACK_SESSION_KEY] = True
                request.session[CHECKOUT_CHANGES_SESSION_KEY] = late_quote_changes
                needs_late_confirmation = True
            elif request.session.get(CHECKOUT_ACK_SESSION_KEY) and not form.cleaned_data['price_confirmation']:
                late_quote_changes = request.session.get(CHECKOUT_CHANGES_SESSION_KEY, [])
                needs_late_confirmation = True
            else:
                preinvoice = PreInvoice.objects.create(
                    customer=profile,
                    customer_name=form.cleaned_data['customer_name'],
                    mobile=form.cleaned_data['mobile'],
                    company_name=form.cleaned_data['company_name'],
                    **address_values,
                    customer_note=form.cleaned_data['customer_note'],
                    status=(
                        PreInvoice.Status.PENDING
                        if all(line['price_is_usable'] and line['stock_is_usable'] for line in context['cart_lines'])
                        else PreInvoice.Status.REVIEW
                    ),
                )
                for line in context['cart_lines']:
                    snapshot = snapshot_line(line)
                    price_observation_id = snapshot.pop('price_observation_id')
                    stock_observation_id = snapshot.pop('stock_observation_id')
                    PreInvoiceItem.objects.create(
                        preinvoice=preinvoice,
                        price_observation_id=price_observation_id,
                        stock_observation_id=stock_observation_id,
                        **snapshot,
                    )

    if cart_became_empty:
        messages.warning(request, 'کالاهای سبد دیگر در دسترس نیستند؛ سبد را دوباره بررسی کنید.')
        return redirect('orders:cart')
    if needs_late_confirmation:
        form_data = request.POST.copy()
        form_data['price_confirmation'] = ''
        form = PreInvoiceForm(form_data, addresses=addresses)
        form.add_error(None, 'قیمت یا موجودی هنگام ثبت تغییر کرد؛ موارد تازه را بررسی و دوباره تأیید کنید.')
        context['form'] = form
        return render(request, 'orders/checkout.html', _set_checkout_quote_context(
            context,
            confirmation_required=True,
            changes=late_quote_changes,
        ))

    Cart(request).clear()
    _clear_checkout_quote(request)
    messages.success(request, 'درخواست پیش‌فاکتور شما ثبت شد.')
    return redirect('orders:preinvoice_detail', public_id=preinvoice.public_id)


@require_GET
def preinvoice_detail(request, public_id):
    preinvoice = get_object_or_404(
        PreInvoice.objects.prefetch_related('items'),
        public_id=public_id,
    )
    lines = list(preinvoice.items.all())
    totals = {}
    for line in lines:
        if line.price_is_usable and line.line_total is not None:
            totals[line.currency] = totals.get(line.currency, 0) + line.line_total
    response = render(request, 'orders/preinvoice_detail.html', {
        'preinvoice': preinvoice,
        'preinvoice_items': lines,
        'currency_totals': totals,
        'accept_quote_form': AcceptPreInvoiceQuoteForm(),
        'otp_sent': request.session.get(PREINVOICE_ACCEPTANCE_SESSION_KEY) == str(preinvoice.public_id),
        'masked_mobile': f'{preinvoice.mobile[:4]}*****{preinvoice.mobile[-2:]}',
        'quote_expired': bool(
            preinvoice.quote_valid_until and preinvoice.quote_valid_until <= timezone.now()
        ),
    })
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Referrer-Policy'] = 'no-referrer'
    return response


@never_cache
@require_POST
def request_preinvoice_acceptance_code(request, public_id):
    preinvoice = get_object_or_404(PreInvoice, public_id=public_id)
    detail_url = reverse('orders:preinvoice_detail', kwargs={'public_id': public_id})
    with transaction.atomic():
        preinvoice = PreInvoice.objects.select_for_update().get(pk=preinvoice.pk)
        if preinvoice.status != PreInvoice.Status.AWAITING_CUSTOMER:
            messages.warning(request, 'این پیش‌فاکتور برای پذیرش در دسترس نیست.')
            return redirect(detail_url)
        now = timezone.now()
        if not preinvoice.quote_valid_until or preinvoice.quote_valid_until <= now:
            preinvoice.status = PreInvoice.Status.REVIEW
            preinvoice.admin_note = (preinvoice.admin_note + '\nارسال کد انجام نشد: مهلت پیش‌فاکتور پایان یافته است.').strip()[:5000]
            invalidate_preinvoice_acceptance_codes(preinvoice.public_id)
            preinvoice.save(update_fields=('status', 'admin_note', 'updated_at'))
            messages.warning(request, 'مهلت پیش‌فاکتور پایان یافته است؛ درخواست برای به‌روزرسانی به کارشناس برگشت.')
            return redirect(detail_url)

        lines = list(preinvoice.items.select_related('variant__product__category'))
        current, reason = captured_quote_is_current(lines)
        if not current or preinvoice.quote_valid_until <= timezone.now():
            preinvoice.status = PreInvoice.Status.REVIEW
            preinvoice.admin_note = (preinvoice.admin_note + f'\nارسال کد انجام نشد: {reason}').strip()[:5000]
            invalidate_preinvoice_acceptance_codes(preinvoice.public_id)
            preinvoice.save(update_fields=('status', 'admin_note', 'updated_at'))
            messages.warning(request, 'قیمت یا موجودی تغییر کرده است؛ درخواست برای صدور پیش‌فاکتور تازه به کارشناس برگشت.')
            return redirect(detail_url)

    try:
        issue_preinvoice_acceptance_code(
            preinvoice.mobile,
            preinvoice.public_id,
            client_ip=request.META.get('REMOTE_ADDR', '')[:45],
        )
    except OTPRateLimited as error:
        messages.warning(request, f'برای درخواست دوباره کمی صبر کنید؛ حدود {error.retry_after} ثانیه دیگر تلاش کنید.')
    except SMSBackendNotConfigured:
        messages.error(request, 'الگوی پیامک اختصاصی پذیرش در این محیط تنظیم نشده است.')
    except SMSDeliveryFailed:
        messages.error(request, 'ارسال کد انجام نشد. کمی بعد دوباره تلاش کنید.')
    else:
        request.session[PREINVOICE_ACCEPTANCE_SESSION_KEY] = str(preinvoice.public_id)
        messages.success(request, f'کد یک‌بارمصرف به شمارهٔ {preinvoice.mobile[:4]}*****{preinvoice.mobile[-2:]} فرستاده شد.')
    return redirect(detail_url)


@never_cache
@require_POST
def accept_preinvoice_quote(request, public_id):
    preinvoice = get_object_or_404(PreInvoice, public_id=public_id)
    detail_url = reverse('orders:preinvoice_detail', kwargs={'public_id': public_id})
    if request.session.get(PREINVOICE_ACCEPTANCE_SESSION_KEY) != str(preinvoice.public_id):
        messages.warning(request, 'ابتدا برای همین پیش‌فاکتور کد تأیید پیامکی درخواست کنید.')
        return redirect(detail_url)

    form = AcceptPreInvoiceQuoteForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'کد شش‌رقمی و تأیید آگاهانهٔ پیش‌فاکتور را وارد کنید.')
        return redirect(detail_url)

    otp_error = None
    accepted = False
    with transaction.atomic():
        preinvoice = PreInvoice.objects.select_for_update().get(pk=preinvoice.pk)
        if preinvoice.status != PreInvoice.Status.AWAITING_CUSTOMER:
            messages.warning(request, 'این پیش‌فاکتور دیگر در انتظار پذیرش نیست.')
            return redirect(detail_url)
        now = timezone.now()
        if not preinvoice.quote_valid_until or preinvoice.quote_valid_until <= now:
            preinvoice.status = PreInvoice.Status.REVIEW
            preinvoice.admin_note = (preinvoice.admin_note + '\nپذیرش انجام نشد: مهلت پیش‌فاکتور پایان یافته است.').strip()[:5000]
            invalidate_preinvoice_acceptance_codes(preinvoice.public_id)
            preinvoice.save(update_fields=('status', 'admin_note', 'updated_at'))
            messages.warning(request, 'مهلت پیش‌فاکتور پایان یافته و برای به‌روزرسانی به کارشناس برگشت.')
            return redirect(detail_url)

        lines = list(preinvoice.items.select_related('variant__product__category'))
        current, reason = captured_quote_is_current(lines)
        if not current or preinvoice.quote_valid_until <= timezone.now():
            preinvoice.status = PreInvoice.Status.REVIEW
            preinvoice.admin_note = (preinvoice.admin_note + f'\nپذیرش انجام نشد: {reason}').strip()[:5000]
            invalidate_preinvoice_acceptance_codes(preinvoice.public_id)
            preinvoice.save(update_fields=('status', 'admin_note', 'updated_at'))
            messages.warning(request, 'قیمت یا موجودی تغییر کرده است؛ درخواست برای صدور پیش‌فاکتور تازه به کارشناس برگشت.')
            return redirect(detail_url)

        try:
            challenge = verify_preinvoice_acceptance_code(
                preinvoice.mobile,
                preinvoice.public_id,
                form.cleaned_data['code'],
            )
        except OTPExpired:
            otp_error = 'مهلت کد پایان یافته است؛ کد تازه درخواست کنید.'
            request.session.pop(PREINVOICE_ACCEPTANCE_SESSION_KEY, None)
        except OTPInvalid:
            otp_error = 'کد معتبر نیست یا تعداد تلاش‌های مجاز تمام شده است.'
        else:
            current, reason = captured_quote_is_current(lines)
            if not current or preinvoice.quote_valid_until <= timezone.now():
                preinvoice.status = PreInvoice.Status.REVIEW
                preinvoice.admin_note = (preinvoice.admin_note + f'\nپذیرش انجام نشد: {reason or "مهلت پیش‌فاکتور پایان یافته است."}').strip()[:5000]
                invalidate_preinvoice_acceptance_codes(preinvoice.public_id)
                preinvoice.save(update_fields=('status', 'admin_note', 'updated_at'))
                messages.warning(request, 'اعتبار قیمت یا موجودی در زمان تأیید به پایان رسید؛ درخواست برای به‌روزرسانی به کارشناس برگشت.')
            else:
                acceptance_time = timezone.now()
                if challenge.expires_at <= acceptance_time:
                    otp_error = 'مهلت کد پایان یافته است؛ کد تازه درخواست کنید.'
                    request.session.pop(PREINVOICE_ACCEPTANCE_SESSION_KEY, None)
                else:
                    profile = CustomerProfile.objects.filter(mobile=preinvoice.mobile).first()
                    preinvoice.customer = profile or preinvoice.customer
                    preinvoice.customer_accepted_at = acceptance_time
                    preinvoice.customer_accepted_mobile = preinvoice.mobile
                    preinvoice.acceptance_otp = challenge
                    preinvoice.status = PreInvoice.Status.CONFIRMED
                    preinvoice.save(update_fields=(
                        'customer', 'customer_accepted_at', 'customer_accepted_mobile',
                        'acceptance_otp', 'status', 'updated_at',
                    ))
                    accepted = True

    if otp_error:
        messages.error(request, otp_error)
    elif accepted:
        request.session.pop(PREINVOICE_ACCEPTANCE_SESSION_KEY, None)
        messages.success(request, 'پذیرش پیش‌فاکتور ثبت شد. این ثبت سفارش قطعی یا پرداخت نیست؛ کارشناس مرحلهٔ بعد را پیگیری می‌کند.')
    return redirect(detail_url)


# ---------------------------------------------------------------------------
# Orders and online payment (SEP)
# ---------------------------------------------------------------------------

def _customer_order_or_404(request, public_id):
    profile = CustomerProfile.objects.filter(user=request.user).first()
    if profile is None:
        raise Http404
    return get_object_or_404(
        Order.objects.prefetch_related('items', 'status_events', 'payments'),
        public_id=public_id,
        customer=profile,
    )


@login_required
@never_cache
@require_GET
def order_detail(request, public_id):
    order = _customer_order_or_404(request, public_id)
    response = render(request, 'orders/order_detail.html', {
        'order': order,
        'totals': order_totals(order),
        'payment_block_reason': payment_block_reason(order),
        'payments': order.payments.all()[:10],
        'status_events': order.status_events.all()[:20],
    })
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@login_required
@never_cache
@require_POST
def order_pay(request, public_id):
    order = _customer_order_or_404(request, public_id)
    detail_url = reverse('orders:order_detail', kwargs={'public_id': order.public_id})
    reason = payment_block_reason(order)
    if reason:
        messages.warning(request, reason)
        return redirect(detail_url)
    if not submission_allowed(request, 'sep-payment', limit=10, window=600):
        messages.warning(request, 'تعداد تلاش‌های پرداخت زیاد بوده است؛ چند دقیقهٔ دیگر دوباره تلاش کنید.')
        return redirect(detail_url)
    callback_url = canonical_url(request, reverse('orders:sep_callback'))
    mobile = order.preinvoice.mobile if order.preinvoice_id else ''
    try:
        payment, action, fields = start_sep_payment(order.pk, callback_url=callback_url, cell_number=mobile)
    except (PaymentUnavailable, ValidationError) as error:
        messages.error(request, f'اتصال به درگاه انجام نشد. {error if isinstance(error, PaymentUnavailable) else ""}'.strip())
        return redirect(detail_url)
    response = render(request, 'orders/payment_redirect.html', {
        'order': order,
        'payment': payment,
        'gateway_action': action,
        'gateway_fields': fields,
    })
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Referrer-Policy'] = 'no-referrer'
    return response


@csrf_exempt
@never_cache
@require_http_methods(['GET', 'POST'])
def sep_callback(request):
    """Bank return URL. Cross-site POST: no session, no CSRF token, untrusted data."""
    data = request.POST if request.method == 'POST' else request.GET
    payment = handle_sep_callback(data)
    if payment is None:
        return redirect('core:home')
    return redirect('orders:payment_result', key=payment.idempotency_key)


@never_cache
@require_GET
def payment_result(request, key):
    payment = get_object_or_404(PaymentRecord.objects.select_related('order'), idempotency_key=key)
    order_url = ''
    if request.user.is_authenticated and payment.order.customer and payment.order.customer.user_id == request.user.pk:
        order_url = reverse('orders:order_detail', kwargs={'public_id': payment.order.public_id})
    response = render(request, 'orders/payment_result.html', {
        'payment': payment,
        'order_number': payment.order.order_number,
        'order_url': order_url,
    })
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Referrer-Policy'] = 'no-referrer'
    return response
