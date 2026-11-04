from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.db.models import Count, F, Q
from django.http import HttpResponse, HttpResponseGone, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from catalog.models import Category, Product, ProductVariant
from content.models import MarketNews
from pricing.selectors import mark_price_state, with_latest_price
from pricing.models import ShippingRate
from .models import RedirectRule

from .forms import ShippingEstimateForm, SteelWeightForm


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
    latest_market_news = MarketNews.objects.select_related('variant__product').all()[:3]

    return render(request, 'core/home.html', {
        'categories': categories,
        'featured_variants': mark_price_state(list(variants)),
        'latest_market_news': latest_market_news,
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


@require_GET
def search_suggestions(request):
    query = request.GET.get('q', '').strip()[:80]
    suggestions = []
    if len(query) >= 2:
        products = Product.objects.filter(
            is_active=True,
            category__is_active=True,
        ).filter(
            Q(name__icontains=query)
            | Q(summary__icontains=query)
            | Q(category__name__icontains=query)
        ).select_related('category').order_by('name')[:6]
        for product in products:
            suggestions.append({
                'label': product.name,
                'detail': product.category.name,
                'url': product.get_absolute_url(),
            })
        remaining = max(0, 10 - len(suggestions))
        if remaining:
            variants = ProductVariant.objects.filter(
                is_active=True,
                product__is_active=True,
                product__category__is_active=True,
            ).filter(
                Q(name__icontains=query)
                | Q(size__icontains=query)
                | Q(grade__icontains=query)
                | Q(standard__icontains=query)
                | Q(manufacturer__name__icontains=query)
            ).select_related('product', 'manufacturer').order_by('product__name', 'sort_order', 'name')[:remaining]
            for variant in variants:
                manufacturer = f' · {variant.manufacturer.name}' if variant.manufacturer else ''
                suggestions.append({
                    'label': f'{variant.product.name} — {variant.name}',
                    'detail': f'{variant.size or variant.get_unit_display()}{manufacturer}',
                    'url': variant.product.get_absolute_url(),
                })
    return JsonResponse({'results': suggestions})


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


@require_GET
def assetlinks_json(request):
    package_name = settings.TWA_PACKAGE_NAME
    fingerprints = [
        value.strip().upper()
        for value in settings.TWA_SHA256_CERT_FINGERPRINTS.split(',')
        if value.strip()
    ]
    canonical = urlsplit(settings.PUBLIC_SITE_URL)
    package_is_valid = bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+', package_name))
    fingerprints_are_valid = bool(fingerprints) and all(
        re.fullmatch(r'(?:[A-F0-9]{2}:){31}[A-F0-9]{2}', value) for value in fingerprints
    )
    expected_host = canonical.netloc.lower().rstrip('.')
    request_host = request.get_host().lower().rstrip('.')
    if (
        canonical.scheme != 'https' or not expected_host or request_host != expected_host
        or not package_is_valid or not fingerprints_are_valid
    ):
        response = HttpResponseNotFound()
        response['X-Robots-Tag'] = 'noindex, nofollow'
        response['Cache-Control'] = 'no-store'
        return response
    statement = [{
        'relation': ['delegate_permission/common.handle_all_urls'],
        'target': {
            'namespace': 'android_app',
            'package_name': package_name,
            'sha256_cert_fingerprints': sorted(set(fingerprints)),
        },
    }]
    response = JsonResponse(statement, safe=False, json_dumps_params={'indent': 2})
    response['Cache-Control'] = 'public, max-age=3600'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def weight_calculator(request):
    form = SteelWeightForm(request.POST or None)
    result = None
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        kind = data['calculation_type']
        count = data['count']
        if kind == 'round_bar':
            per_metre = data['diameter_mm'] ** 2 * Decimal('0.006165375')
            weight = per_metre * data['length_m'] * count
            formula = 'قطر² × طول × ۰٫۰۰۶۱۶۵۳۷۵'
        elif kind == 'pipe':
            per_metre = Decimal('0.0246615') * data['thickness_mm'] * (data['diameter_mm'] - data['thickness_mm'])
            weight = per_metre * data['length_m'] * count
            formula = '۰٫۰۲۴۶۶۱۵ × ضخامت × (قطر بیرونی − ضخامت) × طول × تعداد'
        elif kind == 'plate':
            weight = (
                data['thickness_mm'] * data['width_mm'] * data['length_mm']
                * Decimal('0.00000785') * count
            )
            formula = 'ضخامت × عرض × طول × ۰٫۰۰۰۰۰۷۸۵ × تعداد'
        else:
            weight = data['variant'].weight_per_unit_kg * count
            formula = 'وزن مرجع گونهٔ انتخاب‌شده در کاتالوگ × تعداد'
        result = {
            'weight_kg': weight.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP),
            'weight_tonnes': (weight / Decimal('1000')).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP),
            'formula': formula,
        }
    return render(request, 'core/weight_calculator.html', {'form': form, 'result': result})


def shipping_calculator(request):
    form = ShippingEstimateForm(request.POST or None)
    routes_available = ShippingRate.objects.filter(is_active=True, valid_until__gt=timezone.now()).exists()
    result = None
    unavailable = False
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        now = timezone.now()
        rate = ShippingRate.objects.filter(
            origin_city=data['origin_city'],
            destination_city=data['destination_city'],
            is_active=True,
            valid_until__gt=now,
            minimum_tonnes__lte=data['weight_tonnes'],
        ).filter(
            Q(maximum_tonnes__isnull=True) | Q(maximum_tonnes__gte=data['weight_tonnes'])
        ).order_by('-minimum_tonnes', 'per_tonne').first()
        if rate:
            amount = rate.base_fee + rate.per_tonne * data['weight_tonnes']
            result = {
                'rate': rate,
                'amount': amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP),
                'weight_tonnes': data['weight_tonnes'],
            }
        else:
            unavailable = True
    return render(request, 'core/shipping_calculator.html', {
        'form': form, 'result': result, 'unavailable': unavailable, 'routes_available': routes_available,
    })


@require_GET
def legacy_route(request, old_path):
    path = '/' + old_path
    rule = RedirectRule.objects.filter(old_path=path, is_active=True).first()
    if not rule:
        return page_not_found(request, None)
    if rule.status_code == RedirectRule.StatusCode.GONE:
        response = HttpResponseGone()
        response['X-Robots-Tag'] = 'noindex, nofollow'
        return response
    response = HttpResponseRedirect(rule.destination)
    response.status_code = rule.status_code
    response['Cache-Control'] = 'public, max-age=3600'
    return response


def page_not_found(request, exception):
    return HttpResponse(get_template('404.html').render(), status=404)


def server_error(request):
    return HttpResponse(get_template('500.html').render(), status=500)
