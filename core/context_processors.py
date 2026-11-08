from catalog.models import Category
from inquiries.models import CompanyContactDetails
from .seo import canonical_origin


def get_company_contact_details(request):
    if not hasattr(request, '_company_contact_details'):
        request._company_contact_details = CompanyContactDetails.objects.first()
    return request._company_contact_details


def navigation_categories(request):
    from django.db.models import Prefetch

    from content.models import MarketNews

    cart = request.session.get('ariaa_cart', {}) if hasattr(request, 'session') else {}
    return {
        'navigation_categories': Category.objects.filter(
            is_active=True,
            parent__isnull=True,
        ).prefetch_related(
            Prefetch(
                'children',
                queryset=Category.objects.filter(is_active=True).order_by('sort_order', 'name'),
                to_attr='active_children',
            ),
        ).order_by('sort_order', 'name')[:10],
        'cart_count': len(cart) if isinstance(cart, dict) else 0,
        'market_ticker': MarketNews.objects.select_related('variant__product').all()[:8],
        'company_contact_details': get_company_contact_details(request),
        'canonical_origin': canonical_origin(request),
    }


def site_integrations(request):
    """Expose trust-seal identifiers; the template renders nothing when unset."""
    from django.conf import settings

    enamad_id = settings.ENAMAD_ID
    enamad_code = settings.ENAMAD_CODE
    return {
        'trust_seals': {
            'enamad': {'id': enamad_id, 'code': enamad_code} if enamad_id and enamad_code else None,
            'enamad_meta': settings.ENAMAD_META_CODE,
            'samandehi': (
                {'id': settings.SAMANDEHI_ID, 'code': settings.SAMANDEHI_CODE}
                if settings.SAMANDEHI_ID and settings.SAMANDEHI_CODE else None
            ),
        },
        'payment_enabled': settings.PAYMENT_ENABLED,
    }
