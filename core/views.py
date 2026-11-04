from pathlib import Path

from django.conf import settings
from django.db.models import Count, F, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from catalog.models import Category, Product, ProductVariant
from pricing.selectors import mark_price_state, with_latest_price


def home(request):
    categories = Category.objects.filter(
        is_active=True,
        parent__isnull=True,
    ).annotate(
        product_count=Count('products', filter=Q(products__is_active=True)),
    ).order_by('sort_order', 'name')

    variants = with_latest_price(
        ProductVariant.objects.filter(
            is_active=True,
            product__is_active=True,
            product__category__is_active=True,
        ).select_related('product', 'product__category', 'manufacturer')
    ).order_by(F('latest_observed_at').desc(nulls_last=True), 'product__name')[:6]

    return render(request, 'core/home.html', {
        'categories': categories,
        'featured_variants': mark_price_state(list(variants)),
    })


def search(request):
    query = request.GET.get('q', '').strip()[:100]
    products = Product.objects.none()
    if query:
        products = Product.objects.filter(is_active=True).filter(
            Q(name__icontains=query)
            | Q(summary__icontains=query)
            | Q(category__name__icontains=query)
            | Q(variants__size__icontains=query)
            | Q(variants__grade__icontains=query)
            | Q(variants__standard__icontains=query)
            | Q(variants__manufacturer__name__icontains=query)
        ).select_related('category').distinct().order_by('name')[:50]

    return render(request, 'core/search.html', {
        'query': query,
        'products': products,
    })


def offline(request):
    return render(request, 'core/offline.html')


@require_GET
def robots_txt(request):
    sitemap_url = request.build_absolute_uri(reverse('core:sitemap'))
    body = '\n'.join((
        'User-agent: *',
        'Disallow: /admin/',
        f'Sitemap: {sitemap_url}',
        '',
    ))
    return HttpResponse(body, content_type='text/plain; charset=utf-8')


@require_GET
def service_worker(request):
    worker_path = Path(settings.BASE_DIR) / 'static' / 'service-worker.js'
    response = HttpResponse(
        worker_path.read_text(encoding='utf-8'),
        content_type='application/javascript; charset=utf-8',
    )
    response['Service-Worker-Allowed'] = '/'
    response['Cache-Control'] = 'no-cache'
    return response
