from catalog.models import Category
from inquiries.models import CompanyContactDetails
from .seo import canonical_origin


def get_company_contact_details(request):
    if not hasattr(request, '_company_contact_details'):
        request._company_contact_details = CompanyContactDetails.objects.first()
    return request._company_contact_details


def navigation_categories(request):
    return {
        'navigation_categories': Category.objects.filter(
            is_active=True,
            parent__isnull=True,
        ).order_by('sort_order', 'name')[:8],
        'company_contact_details': get_company_contact_details(request),
        'canonical_origin': canonical_origin(request),
    }
