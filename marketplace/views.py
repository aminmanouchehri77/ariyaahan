from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from accounts.models import CustomerProfile
from core.throttle import submission_allowed
from .forms import MarketplaceListingForm
from .models import MarketplaceListing


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
    page_obj = Paginator(listings, PAGE_SIZE).get_page(request.GET.get('page'))
    is_offer = kind == MarketplaceListing.Kind.OFFER
    return render(request, 'marketplace/hall.html', {
        'form': form,
        'kind': kind,
        'is_offer': is_offer,
        'page_obj': page_obj,
        'listings': page_obj.object_list,
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
