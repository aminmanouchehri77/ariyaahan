from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
import hashlib
import ipaddress
import json
from urllib.parse import urlsplit

from orders.cart import Cart
from pricing.models import PriceObservation

from .forms import (
    CustomerAddressForm,
    CustomerProfileForm,
    MobileLoginForm,
    OTPVerificationForm,
    PriceAlertForm,
)
from .models import CustomerAddress, CustomerNotification, CustomerProfile, PriceAlert, PushSubscription
from .services import (
    AccountInactive,
    OTPExpired,
    OTPInvalid,
    OTPRateLimited,
    issue_login_code,
    verify_login_code,
)
from .sms import SMSBackendNotConfigured, SMSDeliveryFailed


PENDING_MOBILE_SESSION_KEY = 'pending_login_mobile'
PENDING_NEXT_SESSION_KEY = 'pending_login_next'


def _safe_next_url(request, candidate):
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse('accounts:profile')


def _request_login_code(request, mobile):
    issue_login_code(mobile, client_ip=request.META.get('REMOTE_ADDR', '')[:45])


def _add_otp_error_message(request, error):
    if isinstance(error, OTPRateLimited):
        messages.warning(request, f'برای درخواست دوباره کمی صبر کنید؛ حدود {error.retry_after} ثانیه دیگر تلاش کنید.')
    elif isinstance(error, SMSBackendNotConfigured):
        messages.error(request, 'ارسال پیامک در این محیط پیکربندی نشده است. با پشتیبانی تماس بگیرید.')
    elif isinstance(error, SMSDeliveryFailed):
        messages.error(request, 'ارسال پیامک انجام نشد. چند دقیقهٔ دیگر دوباره تلاش کنید.')


@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect('accounts:profile')

    if request.GET.get('change') == '1':
        request.session.pop(PENDING_MOBILE_SESSION_KEY, None)
        request.session.pop(PENDING_NEXT_SESSION_KEY, None)
    elif request.session.get(PENDING_MOBILE_SESSION_KEY):
        return redirect('accounts:verify')

    next_url = _safe_next_url(request, request.POST.get('next') or request.GET.get('next'))
    form = MobileLoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        mobile = form.cleaned_data['mobile']
        try:
            _request_login_code(request, mobile)
        except (OTPRateLimited, SMSBackendNotConfigured, SMSDeliveryFailed) as error:
            _add_otp_error_message(request, error)
        else:
            request.session[PENDING_MOBILE_SESSION_KEY] = mobile
            request.session[PENDING_NEXT_SESSION_KEY] = next_url
            messages.success(request, 'اگر ارسال پیامک در دسترس باشد، کد ورود برای این شماره فرستاده می‌شود.')
            return redirect('accounts:verify')

    return render(request, 'accounts/login.html', {
        'form': form,
        'next_url': next_url,
    })


@never_cache
def verify_view(request):
    mobile = request.session.get(PENDING_MOBILE_SESSION_KEY)
    if request.user.is_authenticated:
        return redirect('accounts:profile')
    if not mobile:
        messages.info(request, 'برای ورود، ابتدا شمارهٔ همراهتان را وارد کنید.')
        return redirect('accounts:login')

    form = OTPVerificationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            user = verify_login_code(
                mobile,
                form.cleaned_data['code'],
                form.cleaned_data['full_name'],
            )
        except OTPExpired:
            form.add_error('code', 'مهلت کد تمام شده است؛ کد تازه درخواست کنید.')
        except OTPInvalid:
            form.add_error('code', 'کد معتبر نیست یا تعداد تلاش‌ها به پایان رسیده است.')
        except AccountInactive:
            messages.error(request, 'این حساب امکان ورود ندارد. با پشتیبانی تماس بگیرید.')
        else:
            next_url = _safe_next_url(request, request.session.pop(PENDING_NEXT_SESSION_KEY, ''))
            request.session.pop(PENDING_MOBILE_SESSION_KEY, None)
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            profile = CustomerProfile.objects.filter(user=user).first()
            if profile:
                from catalog.compare import merge_session_comparison

                merge_session_comparison(profile, request.session)
            messages.success(request, 'با موفقیت وارد حساب خود شدید.')
            return redirect(next_url)

    return render(request, 'accounts/verify.html', {
        'form': form,
        'masked_mobile': f'{mobile[:4]}*****{mobile[-2:]}',
    })


@require_POST
@never_cache
def resend_view(request):
    mobile = request.session.get(PENDING_MOBILE_SESSION_KEY)
    if not mobile:
        messages.info(request, 'برای دریافت کد، شمارهٔ همراهتان را دوباره وارد کنید.')
        return redirect('accounts:login')
    try:
        _request_login_code(request, mobile)
    except (OTPRateLimited, SMSBackendNotConfigured, SMSDeliveryFailed) as error:
        _add_otp_error_message(request, error)
    else:
        messages.success(request, 'کد تازه ارسال شد. کد قبلی دیگر معتبر نیست.')
    return redirect('accounts:verify')


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def profile_view(request):
    profile = CustomerProfile.objects.filter(user=request.user).first()
    profile_form = CustomerProfileForm(request.POST or None, instance=profile) if profile else None
    if request.method == 'POST' and profile_form:
        if profile_form.is_valid():
            profile_form.save()
            messages.success(request, 'اطلاعات حساب به‌روز شد.')
            return redirect('accounts:profile')
    addresses = profile.addresses.all() if profile else []
    notifications = profile.notifications.all()[:8] if profile else []
    unread_count = profile.notifications.filter(is_read=False).count() if profile else 0
    return render(request, 'accounts/profile.html', {
        'profile': profile,
        'profile_form': profile_form,
        'addresses': addresses,
        'notifications': notifications,
        'unread_count': unread_count,
    })


@login_required
@never_cache
def orders_view(request):
    profile = CustomerProfile.objects.filter(user=request.user).first()
    orders = profile.orders.prefetch_related('items', 'status_events') if profile else []
    preinvoices = profile.preinvoices.prefetch_related('items') if profile else []
    order_page = Paginator(orders, 20).get_page(request.GET.get('orders_page'))
    preinvoice_page = Paginator(preinvoices, 20).get_page(request.GET.get('preinvoices_page'))

    def page_url(parameter, page_number, other_parameter, other_page):
        query = request.GET.copy()
        query.pop(parameter, None)
        if page_number:
            query[parameter] = page_number
        if other_page.number > 1:
            query[other_parameter] = other_page.number
        else:
            query.pop(other_parameter, None)
        return f'?{query.urlencode()}' if query else request.path

    return render(request, 'accounts/orders.html', {
        'order_page': order_page,
        'preinvoice_page': preinvoice_page,
        'previous_order_url': page_url(
            'orders_page', order_page.previous_page_number() if order_page.has_previous() else None,
            'preinvoices_page', preinvoice_page,
        ),
        'next_order_url': page_url(
            'orders_page', order_page.next_page_number() if order_page.has_next() else None,
            'preinvoices_page', preinvoice_page,
        ),
        'previous_preinvoice_url': page_url(
            'preinvoices_page', preinvoice_page.previous_page_number() if preinvoice_page.has_previous() else None,
            'orders_page', order_page,
        ),
        'next_preinvoice_url': page_url(
            'preinvoices_page', preinvoice_page.next_page_number() if preinvoice_page.has_next() else None,
            'orders_page', order_page,
        ),
        'has_customer_profile': bool(profile),
    })


@login_required
@never_cache
def requests_view(request):
    profile = CustomerProfile.objects.filter(user=request.user).first()
    tracked_requests = []
    if profile:
        for record in profile.inquiries.all():
            tracked_requests.append({
                'type': record.get_kind_display(),
                'status': record.get_status_display(),
                'created_at': record.created_at,
                'updated_at': record.updated_at,
                'url': reverse('inquiries:status', kwargs={'public_id': record.public_id}),
            })
        for record in profile.company_requests.all():
            tracked_requests.append({
                'type': record.get_kind_display(),
                'status': record.get_status_display(),
                'created_at': record.created_at,
                'updated_at': record.updated_at,
                'url': reverse('content:company_request_status', kwargs={'public_id': record.public_id}),
            })
        for record in profile.marketplace_listings.all():
            tracked_requests.append({
                'type': f'آگهی تالار: {record.get_kind_display()}',
                'status': record.get_status_display(),
                'created_at': record.created_at,
                'updated_at': record.updated_at,
                'url': reverse('marketplace:listing_status', kwargs={'public_id': record.public_id}),
            })
    tracked_requests.sort(key=lambda item: item['created_at'], reverse=True)
    page_obj = Paginator(tracked_requests, 20).get_page(request.GET.get('page'))
    previous_url = f'?page={page_obj.previous_page_number()}' if page_obj.has_previous() else ''
    next_url = f'?page={page_obj.next_page_number()}' if page_obj.has_next() else ''
    return render(request, 'accounts/requests.html', {
        'page_obj': page_obj,
        'previous_url': previous_url,
        'next_url': next_url,
    })


@login_required
@never_cache
def addresses_view(request):
    profile = CustomerProfile.objects.filter(user=request.user).first()
    addresses = profile.addresses.all() if profile else []
    return render(request, 'accounts/addresses.html', {
        'profile': profile,
        'addresses': addresses,
        'form': CustomerAddressForm(),
    })


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def address_add(request):
    profile = CustomerProfile.objects.filter(user=request.user).first()
    if not profile:
        messages.error(request, 'نشانی فقط برای حساب تأییدشدهٔ مشتری قابل ثبت است.')
        return redirect('accounts:profile')
    form = CustomerAddressForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        address = form.save(commit=False)
        address.profile = profile
        address.save()
        messages.success(request, 'نشانی ذخیره شد.')
        return redirect('accounts:addresses')
    return render(request, 'accounts/address_form.html', {'form': form, 'title': 'افزودن نشانی'})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def address_edit(request, address_id):
    profile = get_object_or_404(CustomerProfile, user=request.user)
    address = get_object_or_404(CustomerAddress, pk=address_id, profile=profile)
    form = CustomerAddressForm(request.POST or None, instance=address)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'نشانی به‌روز شد.')
        return redirect('accounts:addresses')
    return render(request, 'accounts/address_form.html', {'form': form, 'title': 'ویرایش نشانی', 'address': address})


@login_required
@never_cache
@require_POST
def address_delete(request, address_id):
    profile = get_object_or_404(CustomerProfile, user=request.user)
    address = get_object_or_404(CustomerAddress, pk=address_id, profile=profile)
    address.delete()
    messages.success(request, 'نشانی حذف شد.')
    return redirect('accounts:addresses')


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def price_alerts_view(request):
    profile = CustomerProfile.objects.filter(user=request.user).first()
    if not profile:
        messages.error(request, 'برای ثبت هشدار قیمت به حساب مشتری تأییدشده نیاز است.')
        return redirect('accounts:profile')
    form = PriceAlertForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        alert = form.save(commit=False)
        alert.profile = profile
        baseline = getattr(form, 'baseline_observation', None)
        if baseline:
            _set_price_alert_baseline(alert, baseline)
        try:
            alert.save()
        except IntegrityError:
            form.add_error(None, 'همین هشدار قبلاً ثبت شده است.')
        else:
            profile.allow_price_notifications = True
            profile.save(update_fields=('allow_price_notifications', 'updated_at'))
            messages.success(request, 'هشدار قیمت ثبت شد؛ اعلان در حساب کاربری نمایش داده می‌شود.')
            return redirect('accounts:price_alerts')
    return render(request, 'accounts/price_alerts.html', {
        'form': form,
        'alerts': profile.price_alerts.select_related('variant__product').all(),
        'vapid_public_key': settings.VAPID_PUBLIC_KEY,
        'push_delivery_enabled': settings.PUSH_DELIVERY_ENABLED,
    })


def _set_price_alert_baseline(alert, observation):
    alert.baseline_amount = observation.amount
    alert.baseline_location = observation.delivery_location
    alert.baseline_tax_included = observation.tax_included
    alert.baseline_observed_at = observation.observed_at


def _latest_alert_baseline(alert):
    return PriceObservation.objects.filter(
        variant=alert.variant,
        currency=alert.currency,
        price_basis=alert.price_basis,
        status=PriceObservation.Status.APPROVED,
        is_available=True,
    ).filter(
        valid_until__gt=timezone.now(),
    ).order_by('-observed_at', '-pk').first()


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def price_alert_edit(request, alert_id):
    profile = get_object_or_404(CustomerProfile, user=request.user)
    alert = get_object_or_404(PriceAlert, pk=alert_id, profile=profile)
    form = PriceAlertForm(request.POST if request.method == 'POST' else None, instance=alert)
    if request.method == 'POST' and form.is_valid():
        updated = form.save(commit=False)
        baseline = getattr(form, 'baseline_observation', None)
        if baseline:
            _set_price_alert_baseline(updated, baseline)
        elif updated.condition_type == PriceAlert.ConditionType.TARGET:
            updated.baseline_amount = None
            updated.baseline_location = ''
            updated.baseline_tax_included = None
            updated.baseline_observed_at = None
        try:
            updated.save()
        except IntegrityError:
            form.add_error(None, 'هشدار مشابهی با همین شرط از قبل ثبت شده است.')
        else:
            messages.success(request, 'هشدار قیمت ویرایش شد.')
            return redirect('accounts:price_alerts')
    return render(request, 'accounts/price_alerts.html', {
        'form': form,
        'editing_alert': alert,
        'alerts': profile.price_alerts.select_related('variant__product').all(),
        'vapid_public_key': settings.VAPID_PUBLIC_KEY,
        'push_delivery_enabled': settings.PUSH_DELIVERY_ENABLED,
    })


@login_required
@never_cache
@require_POST
def price_alert_toggle(request, alert_id):
    profile = get_object_or_404(CustomerProfile, user=request.user)
    alert = get_object_or_404(PriceAlert, pk=alert_id, profile=profile)
    if not alert.is_active and alert.condition_type == PriceAlert.ConditionType.PERCENT_CHANGE:
        baseline = _latest_alert_baseline(alert)
        if not baseline:
            messages.error(request, 'برای فعال‌سازی دوباره، قیمت تأییدشده و معتبر با همین ارز و واحد لازم است.')
            return redirect('accounts:price_alerts')
        _set_price_alert_baseline(alert, baseline)
    alert.is_active = not alert.is_active
    alert.save(update_fields=(
        'is_active', 'baseline_amount', 'baseline_location', 'baseline_tax_included', 'baseline_observed_at',
    ))
    messages.success(request, 'هشدار فعال شد.' if alert.is_active else 'هشدار متوقف شد.')
    return redirect('accounts:price_alerts')


@login_required
@never_cache
@require_POST
def price_alert_delete(request, alert_id):
    profile = get_object_or_404(CustomerProfile, user=request.user)
    alert = get_object_or_404(PriceAlert, pk=alert_id, profile=profile)
    alert.delete()
    messages.success(request, 'هشدار قیمت حذف شد.')
    return redirect('accounts:price_alerts')


@login_required
@never_cache
@require_POST
def notifications_read(request):
    profile = CustomerProfile.objects.filter(user=request.user).first()
    if profile:
        profile.notifications.filter(is_read=False).update(is_read=True)
    messages.success(request, 'اعلان‌ها به‌عنوان خوانده‌شده ثبت شدند.')
    return _notification_return_redirect(request)


@login_required
@never_cache
def notifications_view(request):
    profile = CustomerProfile.objects.filter(user=request.user).first()
    status_filter = 'unread' if request.GET.get('status') == 'unread' else 'all'
    notifications = profile.notifications.all() if profile else CustomerNotification.objects.none()
    if status_filter == 'unread':
        notifications = notifications.filter(is_read=False)
    page_obj = Paginator(notifications, 20).get_page(request.GET.get('page'))

    def page_url(page_number):
        query = request.GET.copy()
        query.pop('page', None)
        if page_number and page_number > 1:
            query['page'] = page_number
        return f'?{query.urlencode()}' if query else request.path

    return render(request, 'accounts/notifications.html', {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'unread_count': profile.notifications.filter(is_read=False).count() if profile else 0,
        'previous_url': page_url(page_obj.previous_page_number() if page_obj.has_previous() else None),
        'next_url': page_url(page_obj.next_page_number() if page_obj.has_next() else None),
    })


@login_required
@never_cache
@require_POST
def notification_read(request, notification_id):
    profile = CustomerProfile.objects.filter(user=request.user).first()
    if profile:
        notification = get_object_or_404(CustomerNotification, pk=notification_id, profile=profile)
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=('is_read',))
    messages.success(request, 'اعلان خوانده‌شده ثبت شد.')
    return _notification_return_redirect(request)


@login_required
@never_cache
@require_POST
def notification_open(request, notification_id):
    profile = get_object_or_404(CustomerProfile, user=request.user)
    notification = get_object_or_404(CustomerNotification, pk=notification_id, profile=profile)
    target_url = notification.target_url
    if not target_url or not url_has_allowed_host_and_scheme(
        target_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        messages.error(request, 'نشانی این اعلان معتبر نیست.')
        return redirect('accounts:notifications')
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=('is_read',))
    return redirect(target_url)


def _notification_return_redirect(request):
    candidate = request.POST.get('return_to', '')
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(candidate)
    return redirect('accounts:profile')


def _push_endpoint_is_allowed(endpoint):
    try:
        parsed = urlsplit(endpoint)
        hostname = (parsed.hostname or '').lower().rstrip('.')
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != 'https' or not hostname or parsed.username or parsed.password
        or port not in (None, 443) or parsed.fragment
    ):
        return False
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return False
    return any(hostname == suffix or hostname.endswith('.' + suffix) for suffix in settings.PUSH_ALLOWED_HOST_SUFFIXES)


def _push_json_body(request):
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > 8192:
            return None
    except ValueError:
        return None
    if len(request.body) > 8192:
        return None
    try:
        value = json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


@login_required
@never_cache
@require_POST
def push_subscribe(request):
    if not settings.PUSH_DELIVERY_ENABLED or not settings.VAPID_PUBLIC_KEY:
        return JsonResponse({'error': 'اعلان مرورگر در این محیط پیکربندی نشده است.'}, status=503)
    profile = CustomerProfile.objects.filter(user=request.user).first()
    if not profile:
        return JsonResponse({'error': 'حساب مشتری تأییدشده پیدا نشد.'}, status=403)
    payload = _push_json_body(request)
    subscription = payload.get('subscription') if payload else None
    if not isinstance(subscription, dict):
        return JsonResponse({'error': 'اطلاعات اشتراک مرورگر معتبر نیست.'}, status=400)
    endpoint = subscription.get('endpoint', '')
    keys = subscription.get('keys')
    if (
        not isinstance(endpoint, str) or len(endpoint) > 2048 or not _push_endpoint_is_allowed(endpoint)
        or not isinstance(keys, dict)
    ):
        return JsonResponse({'error': 'نشانی سرویس اعلان معتبر یا پشتیبانی‌شده نیست.'}, status=400)
    p256dh = keys.get('p256dh', '')
    auth = keys.get('auth', '')
    if (
        not isinstance(p256dh, str) or not 20 <= len(p256dh) <= 200
        or not isinstance(auth, str) or not 8 <= len(auth) <= 100
    ):
        return JsonResponse({'error': 'کلیدهای اشتراک مرورگر معتبر نیستند.'}, status=400)
    endpoint_hash = hashlib.sha256(endpoint.encode('utf-8')).hexdigest()
    try:
        PushSubscription.objects.update_or_create(
            endpoint_hash=endpoint_hash,
            defaults={'profile': profile, 'endpoint': endpoint, 'p256dh': p256dh, 'auth': auth},
        )
    except IntegrityError:
        return JsonResponse({'error': 'ذخیرهٔ اشتراک اعلان انجام نشد؛ دوباره تلاش کنید.'}, status=409)
    return JsonResponse({'ok': True})


@login_required
@never_cache
@require_POST
def push_unsubscribe(request):
    profile = CustomerProfile.objects.filter(user=request.user).first()
    payload = _push_json_body(request)
    endpoint = payload.get('endpoint') if payload else None
    if not profile:
        return JsonResponse({'error': 'حساب مشتری تأییدشده پیدا نشد.'}, status=403)
    if not isinstance(endpoint, str) or len(endpoint) > 2048 or not _push_endpoint_is_allowed(endpoint):
        return JsonResponse({'error': 'نشانی اشتراک معتبر نیست.'}, status=400)
    endpoint_hash = hashlib.sha256(endpoint.encode('utf-8')).hexdigest()
    PushSubscription.objects.filter(profile=profile, endpoint_hash=endpoint_hash).delete()
    return JsonResponse({'ok': True})


@require_POST
@never_cache
def logout_view(request):
    cart_items = request.session.get(Cart.SESSION_KEY)
    logout(request)
    if isinstance(cart_items, dict):
        request.session[Cart.SESSION_KEY] = cart_items
    messages.success(request, 'از حساب خود خارج شدید.')
    return redirect(settings.LOGOUT_REDIRECT_URL)
