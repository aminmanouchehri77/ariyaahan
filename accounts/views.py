from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from orders.cart import Cart

from .forms import (
    CustomerAddressForm,
    CustomerProfileForm,
    MobileLoginForm,
    OTPVerificationForm,
    PriceAlertForm,
)
from .models import CustomerAddress, CustomerProfile, PriceAlert
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
    return render(request, 'accounts/orders.html', {
        'orders': orders,
        'preinvoices': preinvoices,
        'has_customer_profile': bool(profile),
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
    form = PriceAlertForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        alert = form.save(commit=False)
        alert.profile = profile
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
    })


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
    return redirect('accounts:profile')


@require_POST
@never_cache
def logout_view(request):
    cart_items = request.session.get(Cart.SESSION_KEY)
    logout(request)
    if isinstance(cart_items, dict):
        request.session[Cart.SESSION_KEY] = cart_items
    messages.success(request, 'از حساب خود خارج شدید.')
    return redirect(settings.LOGOUT_REDIRECT_URL)
