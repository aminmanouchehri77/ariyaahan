from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Avg, Count, F, Max, Min, Prefetch, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from accounts.models import CustomerProfile
from content.forms import ProductQuestionForm, ProductReviewForm
from content.models import Article, ProductQuestion, ProductReview
from core.seo import breadcrumb_schema, canonical_url
from pricing.models import PriceObservation
from pricing.selectors import latest_stock_observations, mark_price_state, mark_stock_state, with_latest_price

from .forms import CategoryFilterForm
from .models import Category, Product, ProductVariant
from .compare import COMPARE_LIMIT, add_variant, get_variant_ids, profile_for_request, remove_variant


def category_list(request):
    categories = Category.objects.filter(
        is_active=True,
        parent__isnull=True,
    ).prefetch_related(
        Prefetch('children', queryset=Category.objects.filter(is_active=True).order_by('sort_order', 'name'), to_attr='active_children'),
    ).order_by('sort_order', 'name')
    return render(request, 'catalog/category_list.html', {
        'categories': categories,
        'breadcrumb_schema': breadcrumb_schema(request, [
            ('خانه', '/'), ('دسته‌بندی کالا', reverse('catalog:category_list')),
        ]),
    })


def category_detail(request, slug):
    category = get_object_or_404(Category.objects.select_related('parent'), slug=slug, is_active=True)
    category_ids = category.descendant_ids()
    subcategories = list(category.children.filter(is_active=True).order_by('sort_order', 'name'))
    ancestors = category.ancestors()
    variants = ProductVariant.objects.filter(
        product__category_id__in=category_ids,
        product__category__is_active=True,
        product__is_active=True,
        is_active=True,
    ).select_related('product', 'product__category', 'manufacturer')

    filters = CategoryFilterForm(request.GET, category=category)
    filters_valid = filters.is_valid()
    variants = latest_stock_observations(with_latest_price(variants))
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
            variants = variants.filter(
                latest_stock_available=True,
                latest_stock_quantity__gt=0,
                latest_stock_valid_until__gt=timezone.now(),
            )
        elif data['availability'] == 'unavailable':
            current_unavailable_stock = Q(
                latest_stock_observation_id__isnull=False,
                latest_stock_valid_until__gt=timezone.now(),
            ) & (Q(latest_stock_available=False) | Q(latest_stock_quantity__lte=0))
            variants = variants.filter(current_unavailable_stock)
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
    page.object_list = mark_stock_state(mark_price_state(list(page.object_list)))
    query_without_page = request.GET.copy()
    query_without_page.pop('page', None)
    has_active_filters = any(value for key, value in query_without_page.items() if key in filters.fields)
    active_filter_chips = []
    for name, value in filters.cleaned_data.items():
        if name not in request.GET or value in ('', None):
            continue
        field = filters.fields[name]
        if name == 'manufacturer':
            value_label = value.name
        elif hasattr(field, 'choices'):
            value_label = dict(field.choices).get(str(value), str(value))
        else:
            value_label = str(value)
        query = request.GET.copy()
        query.pop(name, None)
        query.pop('page', None)
        remove_url = f'{request.path}?{query.urlencode()}' if query else request.path
        active_filter_chips.append({
            'label': f'{field.label}: {value_label}',
            'remove_url': remove_url,
        })
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
        'subcategories': subcategories,
        'ancestors': ancestors,
        'page_obj': page,
        'filters': filters,
        'ordering': ordering,
        'has_active_filters': has_active_filters,
        'active_filter_chips': active_filter_chips,
        'previous_url': previous_url,
        'next_url': next_url,
        'category_indexable': has_variants and not has_active_filters and page.number == 1,
        'compare_count': len(get_variant_ids(request)),
        'breadcrumb_schema': breadcrumb_schema(request, [
            ('خانه', '/'), ('دسته‌بندی کالا', reverse('catalog:category_list')),
            *[(ancestor.name, ancestor.get_absolute_url()) for ancestor in ancestors],
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
    variants = latest_stock_observations(with_latest_price(
        product.variants.filter(is_active=True).select_related('manufacturer')
    )).order_by('sort_order', 'name')
    variants = mark_stock_state(mark_price_state(list(variants)))
    customer_profile = CustomerProfile.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    questions = ProductQuestion.objects.filter(
        product=product,
        status__in=(ProductQuestion.Status.PUBLISHED, ProductQuestion.Status.ANSWERED),
    ).select_related('reviewer')[:30]
    reviews = ProductReview.objects.filter(
        product=product,
        status=ProductReview.Status.APPROVED,
    ).order_by('-published_at', '-pk')[:30]
    review_summary = ProductReview.objects.filter(
        product=product,
        status=ProductReview.Status.APPROVED,
    ).aggregate(average=Avg('rating'), count=Count('pk'))
    existing_review = ProductReview.objects.filter(product=product, profile=customer_profile).first() if customer_profile else None
    related_articles = Article.objects.filter(
        related_products=product,
        status=Article.Status.PUBLISHED,
        published_at__lte=timezone.now(),
    ).distinct().order_by('-published_at', '-pk')[:4]
    schema = {
        '@context': 'https://schema.org',
        '@type': 'Product',
        'name': product.name,
        'description': product.summary or product.name,
        'category': product.category.name,
        'url': canonical_url(request, product.get_absolute_url()),
    }
    if review_summary['count']:
        schema['aggregateRating'] = {
            '@type': 'AggregateRating',
            'ratingValue': format(review_summary['average'], '.1f'),
            'reviewCount': review_summary['count'],
            'bestRating': 5,
            'worstRating': 1,
        }
    offers = []
    now = timezone.now()
    for variant in variants:
        if variant.latest_stock_observation_id and (
            variant.stock_expired or variant.stock_validity_unknown
            or not variant.latest_stock_available or variant.latest_stock_quantity <= 0
        ):
            continue
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
            'url': canonical_url(request, product.get_absolute_url()),
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
        'compare_count': len(get_variant_ids(request)),
        'product_questions': questions,
        'product_reviews': reviews,
        'review_average': review_summary['average'],
        'review_count': review_summary['count'],
        'review_form': ProductReviewForm() if customer_profile and not existing_review else None,
        'existing_review': existing_review,
        'related_articles': related_articles,
        'product_url': canonical_url(request, product.get_absolute_url()),
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
    variant_ids = get_variant_ids(request)
    variants = latest_stock_observations(with_latest_price(
        ProductVariant.objects.filter(
            pk__in=variant_ids,
            is_active=True,
            product__is_active=True,
            product__category__is_active=True,
        ).select_related('product', 'product__category', 'manufacturer')
    ))
    by_id = {variant.pk: variant for variant in mark_stock_state(mark_price_state(list(variants)))}
    ordered = [by_id[value] for value in variant_ids if value in by_id]
    return render(request, 'catalog/compare.html', {
        'variants': ordered,
        'compare_limit': COMPARE_LIMIT,
        'saved_comparison': profile_for_request(request) is not None,
    })


@never_cache
@require_POST
def compare_add(request, variant_id):
    variant = get_object_or_404(
        ProductVariant, pk=variant_id, is_active=True,
        product__is_active=True, product__category__is_active=True,
    )
    result = add_variant(request, variant)
    if result == 'full':
        messages.warning(request, f'حداکثر می‌توانید {COMPARE_LIMIT} گونه را با هم مقایسه کنید.')
    elif result == 'added':
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
    remove_variant(request, variant_id)
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
    ranges = {
        '7d': ('۷ روز', timedelta(days=7)),
        '30d': ('۳۰ روز', timedelta(days=30)),
        '90d': ('۹۰ روز', timedelta(days=90)),
        '365d': ('یک سال', timedelta(days=365)),
        'all': ('همهٔ سوابق', None),
    }
    selected_range = request.GET.get('range', '30d')
    if selected_range not in ranges:
        selected_range = '30d'
    page_obj = None
    series_currency = ''
    series_basis = ''
    series_count = 0
    chart_bucket = 'روزانه'
    if selected_variant:
        latest = PriceObservation.objects.filter(
            variant=selected_variant, status=PriceObservation.Status.APPROVED,
        ).order_by('-observed_at', '-pk').first()
        if latest:
            series_location = latest.delivery_location
            series_currency = latest.currency
            series_basis = latest.get_price_basis_display()
            series = PriceObservation.objects.filter(
                variant=selected_variant,
                status=PriceObservation.Status.APPROVED,
                currency=latest.currency,
                price_basis=latest.price_basis,
                tax_included=latest.tax_included,
                delivery_location=latest.delivery_location,
            )
            range_delta = ranges[selected_range][1]
            if range_delta:
                series = series.filter(observed_at__gte=timezone.now() - range_delta)
            series_count = series.count()
            extremes = series.aggregate(minimum=Min('amount'), maximum=Max('amount'))
            min_amount = extremes['minimum']
            max_amount = extremes['maximum']
            bucket = TruncMonth('observed_at') if selected_range == 'all' else TruncDate('observed_at')
            chart_bucket = 'ماهانه' if selected_range == 'all' else 'روزانه'
            chart_series = list(
                series.annotate(period=bucket)
                .values('period')
                .annotate(amount=Avg('amount'))
                .order_by('period')
            )
            amounts = [point['amount'] for point in chart_series]
            if len(amounts) > 1:
                span = max_amount - min_amount
                coordinates = []
                for index, point in enumerate(chart_series):
                    x = 30 + round(index * 660 / (len(chart_series) - 1))
                    amount = point['amount']
                    offset = (amount - min_amount) / span if span else 0
                    y = 195 - round(float(offset) * 160)
                    coordinates.append(f'{x},{y}')
                chart_points = ' '.join(coordinates)
            page_obj = Paginator(series.order_by('-observed_at', '-pk'), 50).get_page(request.GET.get('page'))
            observations = page_obj.object_list
    return render(request, 'catalog/price_history.html', {
        'product': product,
        'variants': active_variants,
        'selected_variant': selected_variant,
        'observations': observations,
        'chart_points': chart_points,
        'series_location': series_location,
        'series_tax_included': latest.tax_included if selected_variant and latest else None,
        'series_currency': series_currency,
        'series_basis': series_basis,
        'series_count': series_count,
        'chart_bucket': chart_bucket,
        'ranges': ranges,
        'selected_range': selected_range,
        'selected_range_label': ranges[selected_range][0],
        'page_obj': page_obj,
        'min_amount': min_amount,
        'max_amount': max_amount,
    })
