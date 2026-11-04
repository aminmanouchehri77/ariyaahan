from django.core.paginator import Paginator
from django.db.models import F
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from accounts.models import CustomerProfile
from content.forms import ProductQuestionForm
from content.models import ProductQuestion
from core.seo import breadcrumb_schema
from pricing.models import PriceObservation
from pricing.selectors import mark_price_state, with_latest_price

from .forms import CategoryFilterForm
from .models import Category, Product, ProductVariant


COMPARE_SESSION_KEY = 'ariaa_compare_variants'
COMPARE_LIMIT = 4


def category_list(request):
    categories = Category.objects.filter(
        is_active=True,
        parent__isnull=True,
    ).order_by('sort_order', 'name')
    return render(request, 'catalog/category_list.html', {
        'categories': categories,
        'breadcrumb_schema': breadcrumb_schema(request, [
            ('خانه', '/'), ('دسته‌بندی کالا', reverse('catalog:category_list')),
        ]),
    })


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug, is_active=True)
    variants = ProductVariant.objects.filter(
        product__category=category,
        product__is_active=True,
        is_active=True,
    ).select_related('product', 'product__category', 'manufacturer')

    filters = CategoryFilterForm(request.GET, category=category)
    filters_valid = filters.is_valid()
    variants = with_latest_price(variants)
    if filters_valid:
        data = filters.cleaned_data
        if data['size']:
            variants = variants.filter(size__icontains=data['size'].strip())
        if data['manufacturer']:
            variants = variants.filter(manufacturer=data['manufacturer'])
        if data['grade']:
            variants = variants.filter(grade__icontains=data['grade'].strip())
        if data['standard']:
            variants = variants.filter(standard__icontains=data['standard'].strip())
        if data['location']:
            variants = variants.filter(latest_location__icontains=data['location'].strip())
        if data['currency']:
            variants = variants.filter(latest_currency=data['currency'])
        if data['price_basis']:
            variants = variants.filter(latest_price_basis=data['price_basis'])
        if data['tax_status'] == 'included':
            variants = variants.filter(latest_tax_included=True)
        elif data['tax_status'] == 'excluded':
            variants = variants.filter(latest_tax_included=False)
        elif data['tax_status'] == 'unknown':
            variants = variants.filter(latest_tax_included__isnull=True)
        if data['min_price'] is not None:
            variants = variants.filter(latest_amount__gte=data['min_price'])
        if data['max_price'] is not None:
            variants = variants.filter(latest_amount__lte=data['max_price'])
        if data['availability'] == 'available':
            variants = variants.filter(latest_available=True)
        elif data['availability'] == 'unavailable':
            variants = variants.filter(latest_available=False)
        ordering = data['ordering'] or 'recent'
    else:
        ordering = 'recent'
    sort_expressions = {
        'recent': (F('latest_observed_at').desc(nulls_last=True), 'product__name', 'name'),
        'price_asc': (F('latest_amount').asc(nulls_last=True), 'product__name', 'name'),
        'price_desc': (F('latest_amount').desc(nulls_last=True), 'product__name', 'name'),
        'name': ('product__name', 'name'),
    }
    variants = variants.order_by(*sort_expressions[ordering])

    has_variants = variants.exists()
    page = Paginator(variants, 24).get_page(request.GET.get('page'))
    page.object_list = mark_price_state(list(page.object_list))
    query_without_page = request.GET.copy()
    query_without_page.pop('page', None)
    has_active_filters = any(value for key, value in query_without_page.items() if key in filters.fields)
    previous_url = next_url = ''
    if page.has_previous():
        query = request.GET.copy()
        query['page'] = page.previous_page_number()
        previous_url = f'?{query.urlencode()}'
    if page.has_next():
        query = request.GET.copy()
        query['page'] = page.next_page_number()
        next_url = f'?{query.urlencode()}'
    return render(request, 'catalog/category_detail.html', {
        'category': category,
        'page_obj': page,
        'filters': filters,
        'ordering': ordering,
        'has_active_filters': has_active_filters,
        'previous_url': previous_url,
        'next_url': next_url,
        'category_indexable': has_variants and not has_active_filters and page.number == 1,
        'compare_count': len(request.session.get(COMPARE_SESSION_KEY, [])),
        'breadcrumb_schema': breadcrumb_schema(request, [
            ('خانه', '/'), ('دسته‌بندی کالا', reverse('catalog:category_list')),
            (category.name, category.get_absolute_url()),
        ]),
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
    customer_profile = CustomerProfile.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    questions = ProductQuestion.objects.filter(
        product=product,
        status__in=(ProductQuestion.Status.PUBLISHED, ProductQuestion.Status.ANSWERED),
    ).select_related('reviewer')[:30]
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
        'compare_count': len(request.session.get(COMPARE_SESSION_KEY, [])),
        'product_questions': questions,
        'question_form': ProductQuestionForm(initial={
            'display_name': customer_profile.full_name if customer_profile else '',
        }) if customer_profile else None,
        'question_account_missing': request.user.is_authenticated and customer_profile is None,
        'product_schema': schema,
        'breadcrumb_schema': breadcrumb_schema(request, [
            ('خانه', '/'), ('دسته‌بندی کالا', reverse('catalog:category_list')),
            (product.category.name, product.category.get_absolute_url()),
            (product.name, product.get_absolute_url()),
        ]),
    })


@never_cache
@require_GET
def compare(request):
    raw_ids = request.session.get(COMPARE_SESSION_KEY, [])
    variant_ids = [int(value) for value in raw_ids if str(value).isdigit()][:COMPARE_LIMIT]
    variants = with_latest_price(
        ProductVariant.objects.filter(
            pk__in=variant_ids,
            is_active=True,
            product__is_active=True,
            product__category__is_active=True,
        ).select_related('product', 'product__category', 'manufacturer')
    )
    by_id = {variant.pk: variant for variant in mark_price_state(list(variants))}
    ordered = [by_id[value] for value in variant_ids if value in by_id]
    return render(request, 'catalog/compare.html', {
        'variants': ordered,
        'compare_limit': COMPARE_LIMIT,
    })


@never_cache
@require_POST
def compare_add(request, variant_id):
    variant = get_object_or_404(
        ProductVariant, pk=variant_id, is_active=True,
        product__is_active=True, product__category__is_active=True,
    )
    ids = [str(value) for value in request.session.get(COMPARE_SESSION_KEY, []) if str(value).isdigit()]
    key = str(variant.pk)
    if key not in ids and len(ids) >= COMPARE_LIMIT:
        messages.warning(request, f'حداکثر می‌توانید {COMPARE_LIMIT} گونه را با هم مقایسه کنید.')
    else:
        if key not in ids:
            ids.append(key)
            request.session[COMPARE_SESSION_KEY] = ids
            messages.success(request, 'کالا به فهرست مقایسه اضافه شد.')
        else:
            messages.info(request, 'این کالا از قبل در فهرست مقایسه است.')
    candidate = request.POST.get('next', '')
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return redirect(candidate)
    return redirect(variant.product.get_absolute_url())


@never_cache
@require_POST
def compare_remove(request, variant_id):
    ids = [str(value) for value in request.session.get(COMPARE_SESSION_KEY, []) if str(value).isdigit()]
    request.session[COMPARE_SESSION_KEY] = [value for value in ids if value != str(variant_id)]
    return redirect('catalog:compare')


@never_cache
@require_GET
def price_history(request, slug):
    product = get_object_or_404(Product.objects.select_related('category'), slug=slug, is_active=True, category__is_active=True)
    active_variants = product.variants.filter(is_active=True).select_related('manufacturer')
    selected_id = request.GET.get('variant', '')
    selected_variant = active_variants.filter(pk=selected_id).first() if selected_id.isdigit() else None
    if selected_variant is None:
        selected_variant = active_variants.order_by('sort_order', 'name').first()
    observations = []
    chart_points = ''
    series_location = ''
    min_amount = max_amount = None
    if selected_variant:
        latest = PriceObservation.objects.filter(
            variant=selected_variant, status=PriceObservation.Status.APPROVED,
        ).order_by('-observed_at', '-pk').first()
        if latest:
            series_location = latest.delivery_location
            observations = list(PriceObservation.objects.filter(
                variant=selected_variant,
                status=PriceObservation.Status.APPROVED,
                currency=latest.currency,
                price_basis=latest.price_basis,
                tax_included=latest.tax_included,
                delivery_location=latest.delivery_location,
            ).order_by('-observed_at', '-pk')[:30])
            observations.reverse()
            amounts = [observation.amount for observation in observations]
            min_amount = min(amounts) if amounts else None
            max_amount = max(amounts) if amounts else None
            if len(amounts) > 1:
                span = max_amount - min_amount
                coordinates = []
                for index, amount in enumerate(amounts):
                    x = 30 + round(index * 660 / (len(amounts) - 1))
                    offset = (amount - min_amount) / span if span else 0
                    y = 195 - round(float(offset) * 160)
                    coordinates.append(f'{x},{y}')
                chart_points = ' '.join(coordinates)
    return render(request, 'catalog/price_history.html', {
        'product': product,
        'variants': active_variants,
        'selected_variant': selected_variant,
        'observations': observations,
        'chart_points': chart_points,
        'series_location': series_location,
        'series_tax_included': latest.tax_included if selected_variant and observations else None,
        'min_amount': min_amount,
        'max_amount': max_amount,
    })
