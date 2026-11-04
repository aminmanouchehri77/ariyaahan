from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db.models import Count, F, Q
from django.http import HttpResponse, HttpResponseGone, HttpResponseNotFound, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from catalog.models import Category, Product, ProductVariant
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
        return HttpResponseNotFound()
    if rule.status_code == RedirectRule.StatusCode.GONE:
        response = HttpResponseGone()
        response['X-Robots-Tag'] = 'noindex, nofollow'
        return response
    response = HttpResponseRedirect(rule.destination)
    response.status_code = rule.status_code
    response['Cache-Control'] = 'public, max-age=3600'
    return response
