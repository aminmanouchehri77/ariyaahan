from django.core.paginator import Paginator
from django.db.models import F
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from pricing.selectors import mark_price_state, with_latest_price

from .models import Category, Product, ProductVariant


def category_list(request):
    categories = Category.objects.filter(
        is_active=True,
        parent__isnull=True,
    ).order_by('sort_order', 'name')
    return render(request, 'catalog/category_list.html', {'categories': categories})


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug, is_active=True)
    variants = ProductVariant.objects.filter(
        product__category=category,
        product__is_active=True,
        is_active=True,
    ).select_related('product', 'product__category', 'manufacturer')

    size = request.GET.get('size', '').strip()[:80]
    manufacturer = request.GET.get('manufacturer', '').strip()[:140]
    if size:
        variants = variants.filter(size__icontains=size)
    if manufacturer:
        variants = variants.filter(manufacturer__name__icontains=manufacturer)
    variants = with_latest_price(variants).order_by(
        'product__name', 'sort_order', F('latest_observed_at').desc(nulls_last=True), 'name'
    )

    has_variants = variants.exists()
    page = Paginator(variants, 24).get_page(request.GET.get('page'))
    page.object_list = mark_price_state(list(page.object_list))
    return render(request, 'catalog/category_detail.html', {
        'category': category,
        'page_obj': page,
        'size_filter': size,
        'manufacturer_filter': manufacturer,
        'category_indexable': has_variants and not size and not manufacturer and page.number == 1,
    })


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related('category'),
        slug=slug,
        is_active=True,
        category__is_active=True,
    )
    variants = with_latest_price(
        product.variants.filter(is_active=True).select_related('manufacturer')
    ).order_by('sort_order', 'name')
    variants = mark_price_state(list(variants))
    schema = {
        '@context': 'https://schema.org',
        '@type': 'Product',
        'name': product.name,
        'description': product.summary or product.name,
        'category': product.category.name,
        'url': request.build_absolute_uri(product.get_absolute_url()),
    }
    offers = []
    now = timezone.now()
    for variant in variants:
        if (
            variant.latest_amount is None
            or not variant.latest_available
            or not variant.latest_valid_until
            or variant.latest_valid_until <= now
        ):
            continue

        currency = variant.latest_currency
        amount = variant.latest_amount
        if currency == 'IRT':
            amount *= 10
            currency = 'IRR'
        if currency not in {'IRR', 'USD'}:
            continue

        offer = {
            '@type': 'Offer',
            'name': variant.name,
            'priceCurrency': currency,
            'price': format(amount, 'f'),
            'availability': 'https://schema.org/InStock',
            'url': request.build_absolute_uri(product.get_absolute_url()),
            'priceValidUntil': timezone.localtime(variant.latest_valid_until).date().isoformat(),
        }
        if variant.sku:
            offer['sku'] = variant.sku
        offers.append(offer)
    if offers:
        schema['offers'] = offers

    return render(request, 'catalog/product_detail.html', {
        'product': product,
        'variants': variants,
        'product_schema': schema,
    })
