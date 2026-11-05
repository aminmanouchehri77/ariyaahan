import re

from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from accounts.models import CustomerProfile
from catalog.models import ProductVariant
from core.context_processors import get_company_contact_details
from core.seo import json_ld
from marketplace.models import MarketplaceListing

from .forms import InquiryForm
from .models import CompanyContactDetails, Inquiry


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
        if request.user.is_authenticated:
            inquiry.profile = CustomerProfile.objects.filter(
                user=request.user, mobile=inquiry.mobile,
            ).first()
        inquiry.save()
        return redirect('inquiries:status', public_id=inquiry.public_id)

    contact_details = get_company_contact_details(request) if kind == Inquiry.Kind.CONTACT else None
    contact_schema = None
    if contact_details and contact_details.has_public_details:
        organization = {
            '@type': 'Organization',
            'name': contact_details.public_name or 'آهن‌آلات آریا',
            'url': request.build_absolute_uri('/'),
        }
        if contact_details.phone or contact_details.email:
            point = {'@type': 'ContactPoint', 'contactType': 'customer service'}
            if contact_details.phone:
                point['telephone'] = contact_details.phone
            if contact_details.email:
                point['email'] = contact_details.email
            organization['contactPoint'] = [point]
        if contact_details.address:
            organization['address'] = {
                '@type': 'PostalAddress',
                'streetAddress': contact_details.address,
            }
        if contact_details.map_url:
            organization['hasMap'] = contact_details.map_url
        social_links = [url for url in (
            contact_details.whatsapp_url, contact_details.telegram_url,
            contact_details.instagram_url, contact_details.linkedin_url,
        ) if url]
        if social_links:
            organization['sameAs'] = social_links
        contact_schema = json_ld({
            '@context': 'https://schema.org',
            '@type': 'ContactPage',
            'name': 'تماس با آهن‌آلات آریا',
            'url': request.build_absolute_uri(),
            'mainEntity': organization,
        })

    return render(request, 'inquiries/form.html', {
        'form': form,
        'kind': kind,
        'is_quote': kind == Inquiry.Kind.QUOTE,
        'sent': request.GET.get('sent') == '1',
        'selected_variant': selected_variant,
        'contact_details': contact_details,
        'contact_schema': contact_schema,
    })


@require_http_methods(['GET', 'POST'])
def quote_request(request):
    return _inquiry_page(request, Inquiry.Kind.QUOTE)


@require_http_methods(['GET', 'POST'])
def contact(request):
    return _inquiry_page(request, Inquiry.Kind.CONTACT)


@never_cache
def inquiry_status(request, public_id):
    inquiry = get_object_or_404(Inquiry, public_id=public_id)
    response = render(request, 'inquiries/status.html', {'inquiry': inquiry})
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Referrer-Policy'] = 'no-referrer'
    return response
