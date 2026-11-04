from catalog.models import Category


def navigation_categories(request):
    return {
        'navigation_categories': Category.objects.filter(
            is_active=True,
            parent__isnull=True,
        ).order_by('sort_order', 'name')[:8],
    }
