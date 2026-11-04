import re

from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from catalog.models import ProductVariant
from marketplace.models import MarketplaceListing

from .forms import InquiryForm
from .models import Inquiry


def _inquiry_page(request, kind):
    selected_variant = None
    variant_id = request.GET.get('variant') if kind == Inquiry.Kind.QUOTE and request.method == 'GET' else None
    if variant_id:
        selected_variant = get_object_or_404(
            ProductVariant.objects.select_related('product', 'manufacturer'),
            pk=variant_id,
            is_active=True,
            product__is_active=True,
            product__category__is_active=True,
        )

    initial = {}
    if selected_variant:
        initial['product_variant'] = selected_variant.pk
        initial['quantity_unit'] = selected_variant.get_unit_display()
    listing_reference = request.GET.get('listing', '')
    if (
        kind == Inquiry.Kind.CONTACT
        and request.method == 'GET'
        and re.fullmatch(r'[0-9]{1,18}', listing_reference)
    ):
        listing = get_object_or_404(
            MarketplaceListing,
            pk=int(listing_reference),
            status=MarketplaceListing.Status.APPROVED,
            expires_at__gt=timezone.now(),
        )
        initial['message'] = (
            f'درخواست پیگیری آگهی شمارهٔ {listing.pk}: {listing.product_label}، '
            f'{listing.quantity} {listing.get_quantity_unit_display()}، {listing.city}.'
        )

    form = InquiryForm(
        request.POST or None,
        initial=initial,
        inquiry_kind=kind,
    )
    if request.method == 'POST' and form.is_valid():
        inquiry = form.save(commit=False)
        inquiry.kind = kind
        inquiry.source_path = request.get_full_path()[:255]
        inquiry.save()
        return redirect(f'{request.path}?sent=1')

    return render(request, 'inquiries/form.html', {
        'form': form,
        'kind': kind,
        'is_quote': kind == Inquiry.Kind.QUOTE,
        'sent': request.GET.get('sent') == '1',
        'selected_variant': selected_variant,
    })


@require_http_methods(['GET', 'POST'])
def quote_request(request):
    return _inquiry_page(request, Inquiry.Kind.QUOTE)


@require_http_methods(['GET', 'POST'])
def contact(request):
    return _inquiry_page(request, Inquiry.Kind.CONTACT)
