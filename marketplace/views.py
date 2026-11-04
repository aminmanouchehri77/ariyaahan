from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .forms import MarketplaceListingForm
from .models import MarketplaceListing


PAGE_SIZE = 12


def _hall(request, kind):
    form = MarketplaceListingForm(request.POST or None, kind=kind)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(
            request,
            'آگهی ثبت شد و پس از بررسی کارشناسان در تالار نمایش داده می‌شود.',
        )
        return redirect(request.path)

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
