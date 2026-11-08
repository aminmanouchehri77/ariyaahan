import hashlib

from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import CustomerProfile
from core.throttle import client_ip, submission_allowed
from .forms import MarketplaceListingForm
from .models import ListingReport, MarketplaceListing

AUTO_HIDE_REPORTS = 3


PAGE_SIZE = 12


def _hall(request, kind):
    form = MarketplaceListingForm(request.POST if request.method == 'POST' else None, kind=kind)
    throttled = request.method == 'POST' and not submission_allowed(request, f'listing-{kind}')
    if throttled:
        form.is_valid()
        form.add_error(None, 'تعداد ارسال‌های شما در چند دقیقهٔ اخیر زیاد بوده است؛ کمی بعد دوباره تلاش کنید.')
    elif request.method == 'POST' and form.is_valid():
        listing = form.save(commit=False)
        if request.user.is_authenticated:
            listing.profile = CustomerProfile.objects.filter(
                user=request.user, mobile=listing.mobile,
            ).first()
        listing.save()
        messages.success(
            request,
            'آگهی ثبت شد و پس از بررسی کارشناسان در تالار نمایش داده می‌شود.',
        )
        return redirect('marketplace:listing_status', public_id=listing.public_id)

    listings = MarketplaceListing.objects.filter(
        kind=kind,
        status=MarketplaceListing.Status.APPROVED,
        expires_at__gt=timezone.now(),
    ).filter(
        Q(product_variant__isnull=True)
        | Q(
            product_variant__is_active=True,
            product_variant__product__is_active=True,
            product_variant__product__category__is_active=True,
        )
    ).select_related('product_variant', 'product_variant__product').order_by('-created_at', '-pk')
    search = request.GET.get('q', '').strip()[:80]
    city = request.GET.get('city', '').strip()[:80]
    if search:
        from core.search import match_q

        condition = match_q(search, ('product_label', 'details', 'product_variant__product__name'))
        if condition is not None:
            listings = listings.filter(condition)
    if city:
        listings = listings.filter(city__icontains=city)
    cities = list(
        MarketplaceListing.objects.filter(kind=kind, status=MarketplaceListing.Status.APPROVED, expires_at__gt=timezone.now())
        .values_list('city', flat=True).distinct().order_by('city')[:30]
    )
    page_obj = Paginator(listings, PAGE_SIZE).get_page(request.GET.get('page'))
    is_offer = kind == MarketplaceListing.Kind.OFFER
    return render(request, 'marketplace/hall.html', {
        'form': form,
        'kind': kind,
        'is_offer': is_offer,
        'page_obj': page_obj,
        'listings': page_obj.object_list,
        'search': search,
        'city': city,
        'cities': cities,
        'report_reasons': ListingReport.Reason.choices,
    })


@never_cache
@require_http_methods(['GET', 'POST'])
def sell_hall(request):
    return _hall(request, MarketplaceListing.Kind.OFFER)


@never_cache
@require_http_methods(['GET', 'POST'])
def buy_hall(request):
    return _hall(request, MarketplaceListing.Kind.REQUEST)


@never_cache
def listing_status(request, public_id):
    listing = get_object_or_404(MarketplaceListing, public_id=public_id)
    response = render(request, 'marketplace/listing_status.html', {'listing': listing})
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Referrer-Policy'] = 'no-referrer'
    return response


@require_POST
def report_listing(request, pk):
    listing = get_object_or_404(
        MarketplaceListing, pk=pk, status=MarketplaceListing.Status.APPROVED, expires_at__gt=timezone.now(),
    )
    hall = 'marketplace:sell' if listing.kind == MarketplaceListing.Kind.OFFER else 'marketplace:buy'
    reason = request.POST.get('reason', '')
    if reason not in ListingReport.Reason.values:
        messages.error(request, 'دلیل گزارش را انتخاب کنید.')
        return redirect(hall)
    if not submission_allowed(request, 'listing-report', limit=10, window=3600):
        messages.warning(request, 'تعداد گزارش‌های شما زیاد بوده است؛ بعداً دوباره تلاش کنید.')
        return redirect(hall)
    # One report per network address, whether or not the visitor is signed in: switching between
    # several accounts from one address must not count as independent reports.
    identity = client_ip(request) or 'unknown'
    reporter_key = hashlib.sha256(f'{settings.SECRET_KEY}:report:{identity}'.encode()).hexdigest()
    try:
        with transaction.atomic():
            ListingReport.objects.create(
                listing=listing, reason=reason, reporter_key=reporter_key,
                details=request.POST.get('details', '').strip()[:400],
            )
            open_reports = listing.reports.filter(status=ListingReport.Status.OPEN)
            if listing.reviewed_at:
                # Reports raised before the last moderation decision were already weighed by a reviewer;
                # without this a single new report would hide a re-approved listing again.
                open_reports = open_reports.filter(created_at__gt=listing.reviewed_at)
            open_reports = open_reports.count()
            if open_reports >= AUTO_HIDE_REPORTS:
                # Several independent reports: pull the listing back for review.
                MarketplaceListing.objects.filter(pk=listing.pk).update(
                    status=MarketplaceListing.Status.PENDING,
                    admin_note=(listing.admin_note + '\nبه‌دلیل چند گزارش تخلف، خودکار به بررسی برگشت.').strip()[:5000],
                )
    except IntegrityError:
        messages.info(request, 'گزارش شما برای این آگهی قبلاً ثبت شده است.')
    else:
        messages.success(request, 'گزارش ثبت شد و توسط کارشناسان بررسی می‌شود. سپاس از همراهی شما.')
    return redirect(hall)
