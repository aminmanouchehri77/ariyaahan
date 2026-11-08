import csv
import io
import json
import re
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomerProfile
from catalog.compare import COMPARE_LIMIT, COMPARE_SESSION_KEY, merge_session_comparison
from catalog.models import Category, Manufacturer, Product, ProductVariant, SavedComparison, SavedComparisonItem
from core.search import did_you_mean, normalize_fa, tokens
from pricing.models import PriceObservation


class CatalogFixtureMixin:
    def setUp(self):
        cache.clear()
        self.operator = get_user_model().objects.create_user('operator-cat')
        self.category = Category.objects.create(name='میلگرد', slug='sec-rebar')
        self.manufacturer = Manufacturer.objects.create(name='ذوب‌آهن', slug='zob')
        self.product = Product.objects.create(
            category=self.category, name='میلگرد آجدار', slug='rebar-ribbed', summary='میلگرد ساختمانی',
        )
        self.variant = ProductVariant.objects.create(
            product=self.product, manufacturer=self.manufacturer, name='سایز ۱۲', size='12',
            grade='A3', unit='kg', sku='RB-12', weight_per_unit_kg=Decimal('10.656'),
        )

    def price(self, variant=None, amount='300000', status='approved', valid_for=timedelta(days=1), **extra):
        observation = PriceObservation.objects.create(
            variant=variant or self.variant, amount=Decimal(amount), currency=extra.pop('currency', 'IRR'),
            price_basis=extra.pop('price_basis', 'kg'), delivery_location=extra.pop('delivery_location', 'تهران'),
            valid_until=(timezone.now() + valid_for) if valid_for is not None else None,
            created_by=self.operator, **extra,
        )
        if status == 'approved':
            observation.approve(self.operator)
        elif status == 'rejected':
            observation.reject(self.operator)
        return observation

    def jsonld_product(self, response):
        match = re.search(
            r'<script id="product-jsonld" type="application/ld\+json">(.*?)</script>',
            response.content.decode(), re.S,
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(1))


class ReflectedXssTests(CatalogFixtureMixin, TestCase):
    payload = '"><script>alert(1)</script><img src=x onerror=alert(2)>'

    def test_category_filter_params_are_escaped(self):
        url = reverse('catalog:category_detail', args=[self.category.slug])
        response = self.client.get(url, {'size': self.payload, 'grade': self.payload, 'location': self.payload})
        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<script>alert(1)', body)
        self.assertNotIn('<img src=x', body)
        self.assertIn('&lt;script&gt;alert(1)', body)

    def test_search_query_is_escaped(self):
        response = self.client.get(reverse('core:search'), {'q': self.payload})
        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<script>alert(1)', body)
        self.assertNotIn('<img src=x', body)

    def test_did_you_mean_suggestion_is_escaped(self):
        Product.objects.create(category=self.category, name='تیرآهن <img src=x onerror=alert(1)>', slug='evil')
        cache.clear()
        response = self.client.get(reverse('core:search'), {'q': 'تيرآهن <img src=x onerror=alert(9)> زززز'})
        body = response.content.decode()
        self.assertTrue(response.context['suggestion'])
        self.assertNotIn('<img src=x', body)
        self.assertIn('&lt;img src=x', body)

    def test_suggestions_endpoint_returns_json_not_html(self):
        response = self.client.get(reverse('core:search_suggestions'), {'q': '<script>میلگرد'})
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertNotIn(b'<script>', response.content)


class FilterAndSortInjectionTests(CatalogFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('catalog:category_detail', args=[self.category.slug])
        self.price()

    def test_sql_injection_in_ordering_is_rejected_by_whitelist(self):
        for value in ("name; DROP TABLE catalog_product;--", '-pk', 'product__name', "price_asc' OR '1'='1"):
            response = self.client.get(self.url, {'ordering': value})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['ordering'], 'recent')
            self.assertIn('ordering', response.context['filters'].errors)
        self.assertTrue(Product.objects.exists())

    def test_sql_injection_in_filters_is_harmless(self):
        response = self.client.get(self.url, {'manufacturer': '1 OR 1=1', 'currency': "IRR' --"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['filters'].is_valid())
        response = self.client.get(self.url, {'size': "' OR '1'='1"})
        self.assertEqual(response.context['page_obj'].paginator.count, 0)

    def test_like_wildcards_are_literal(self):
        for value in ('%', '_'):
            response = self.client.get(self.url, {'size': value})
            self.assertEqual(response.context['page_obj'].paginator.count, 0)

    def test_bad_page_numbers(self):
        for page in ('abc', '-1', '0', '99999999999999999999', '۲', ''):
            response = self.client.get(self.url, {'page': page})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['page_obj'].number, 1)

    def test_unknown_filter_values_produce_errors_and_no_misleading_chips(self):
        response = self.client.get(self.url, {'currency': 'EUR', 'size': '12', 'min_price': 'NaN'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('currency', response.context['filters'].errors)
        self.assertEqual(response.context['active_filter_chips'], [])

    def test_huge_and_nul_filter_values(self):
        response = self.client.get(self.url, {'size': 'x' * 5000})
        self.assertEqual(response.status_code, 200)
        self.assertIn('size', response.context['filters'].errors)
        response = self.client.get(self.url, {'size': '\x00'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('size', response.context['filters'].errors)

    def test_price_filter_with_persian_digits_requires_comparable_context(self):
        response = self.client.get(self.url, {'min_price': '۱۰۰'})
        self.assertIn('currency', response.context['filters'].errors)
        response = self.client.get(self.url, {
            'min_price': '۴۰۰۰۰۰', 'currency': 'IRR', 'price_basis': 'kg', 'location': 'تهران', 'tax_status': 'unknown',
        })
        self.assertTrue(response.context['filters'].is_valid())
        self.assertEqual(response.context['page_obj'].paginator.count, 0)
        response = self.client.get(self.url, {
            'max_price': '۴۰۰۰۰۰', 'currency': 'IRR', 'price_basis': 'kg', 'location': 'تهران',
            'tax_status': 'unknown', 'ordering': 'price_asc',
        })
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        self.assertTrue(response.context['active_filter_chips'])

    def test_mixed_currency_filter(self):
        other = ProductVariant.objects.create(product=self.product, name='سایز ۱۴', size='14', unit='kg')
        self.price(variant=other, amount='30', currency='USD')
        response = self.client.get(self.url, {'currency': 'USD'})
        self.assertEqual([v.pk for v in response.context['page_obj']], [other.pk])
        # Different currencies are never compared for the "best price" badge.
        response = self.client.get(self.url)
        self.assertFalse(any(v.is_best_price for v in response.context['page_obj']))


class PublicVisibilityTests(CatalogFixtureMixin, TestCase):
    def test_pending_and_rejected_prices_never_reach_public_pages(self):
        self.price(amount='111111', status='pending')
        self.price(amount='222222', status='rejected')
        pages = [
            reverse('catalog:product_detail', args=[self.product.slug]),
            reverse('catalog:category_detail', args=[self.category.slug]),
            reverse('catalog:category_price_list', args=[self.category.slug]),
            reverse('catalog:price_history', args=[self.product.slug]) + '?range=all',
        ]
        for url in pages:
            body = self.client.get(url).content.decode()
            for digits in ('111111', '111,111', '۱۱۱٬۱۱۱', '۱۱۱۱۱۱', '222222', '۲۲۲٬۲۲۲'):
                self.assertNotIn(digits, body, url)
        self.assertNotIn('offers', self.jsonld_product(self.client.get(pages[0])))

    def test_inactive_product_and_category_are_hidden(self):
        hidden_category = Category.objects.create(name='دستهٔ پنهان', slug='hidden-cat', is_active=False)
        hidden_product = Product.objects.create(category=hidden_category, name='کالای مخفی', slug='secret')
        Product.objects.create(category=self.category, name='کالای غیرفعال', slug='inactive', is_active=False)
        hidden_variant = ProductVariant.objects.create(product=hidden_product, name='گونهٔ مخفی', unit='kg')
        inactive_variant = ProductVariant.objects.create(product=self.product, name='گونهٔ غیرفعال', unit='kg', is_active=False)
        cache.clear()
        for url in (
            reverse('catalog:category_detail', args=['hidden-cat']),
            reverse('catalog:category_price_list', args=['hidden-cat']),
            reverse('catalog:product_detail', args=['secret']),
            reverse('catalog:product_detail', args=['inactive']),
            reverse('catalog:price_history', args=['secret']),
        ):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.post(reverse('catalog:compare_add', args=[hidden_variant.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('catalog:compare_add', args=[inactive_variant.pk])).status_code, 404)
        listing = self.client.get(reverse('catalog:category_list')).content.decode()
        self.assertNotIn('دستهٔ پنهان', listing)
        detail = self.client.get(reverse('catalog:category_detail', args=[self.category.slug])).content.decode()
        self.assertNotIn('گونهٔ غیرفعال', detail)
        price_list = self.client.get(reverse('catalog:category_price_list', args=[self.category.slug])).content.decode()
        self.assertNotIn('گونهٔ غیرفعال', price_list)
        for query in ('مخفی', 'غیرفعال'):
            self.assertEqual(self.client.get(reverse('core:search'), {'q': query}).context['products'], [])
            payload = self.client.get(reverse('core:search_suggestions'), {'q': query}).json()
            self.assertEqual(payload['results'], [])
        self.assertNotIn('کالای مخفی', did_you_mean('کالای مخفي'))

    def test_inactive_subcategory_products_excluded_from_parent(self):
        child = Category.objects.create(name='زیر', slug='child', parent=self.category, is_active=False)
        product = Product.objects.create(category=child, name='کالای زیر دسته', slug='child-product')
        ProductVariant.objects.create(product=product, name='زیرگونه', unit='kg')
        body = self.client.get(reverse('catalog:category_detail', args=[self.category.slug])).content.decode()
        self.assertNotIn('زیرگونه', body)

    def test_empty_catalog(self):
        ProductVariant.objects.all().delete()
        Product.objects.all().delete()
        response = self.client.get(reverse('catalog:category_detail', args=[self.category.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['category_indexable'])
        self.assertEqual(self.client.get(reverse('catalog:category_price_list', args=[self.category.slug])).status_code, 200)
        Category.objects.update(is_active=False)
        cache.clear()
        response = self.client.get(reverse('catalog:category_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['categories']), [])
        self.assertEqual(self.client.get(reverse('core:search'), {'q': 'میلگرد'}).status_code, 200)


class ProductJsonLdAndOrderingTests(CatalogFixtureMixin, TestCase):
    def url(self):
        return reverse('catalog:product_detail', args=[self.product.slug])

    def test_offer_only_with_fresh_valid_price(self):
        self.price()
        schema = self.jsonld_product(self.client.get(self.url()))
        self.assertEqual(schema['offers'][0]['price'], '300000')
        self.assertEqual(schema['offers'][0]['priceCurrency'], 'IRR')

    def test_irt_offer_is_converted_to_rial(self):
        self.price(amount='30000', currency='IRT')
        schema = self.jsonld_product(self.client.get(self.url()))
        self.assertEqual(schema['offers'][0]['price'], '300000')

    def test_no_offer_for_expired_unknown_or_unavailable_price(self):
        for kwargs in ({'valid_for': -timedelta(minutes=1)}, {'valid_for': None}, {'is_available': False}):
            PriceObservation.objects.filter(variant=self.variant).update(status='rejected')
            self.price(**kwargs)
            schema = self.jsonld_product(self.client.get(self.url()))
            self.assertNotIn('offers', schema, kwargs)

    def test_jsonld_escapes_script_breakout(self):
        self.product.summary = '</script><script>alert(1)</script>'
        self.product.save()
        self.variant.name = '</script><img src=x>'
        self.variant.save()
        self.price()
        response = self.client.get(self.url())
        body = response.content.decode()
        self.assertNotIn('</script><script>alert(1)', body)
        self.assertNotIn('<img src=x>', body)
        schema = self.jsonld_product(response)
        self.assertEqual(schema['description'], '</script><script>alert(1)</script>')

    def test_breadcrumb_jsonld_escapes_category_name(self):
        self.category.name = '</script><script>alert(1)</script>'
        self.category.save()
        body = self.client.get(self.url()).content.decode()
        self.assertNotIn('</script><script>alert(1)', body)

    def test_expired_price_disables_immediate_order(self):
        self.price(valid_for=-timedelta(hours=1))
        response = self.client.get(self.url())
        self.assertFalse(response.context['variants'][0].price_orderable)
        self.assertContains(response, 'data-order-disabled')
        self.assertContains(response, 'قیمت منقضی')

    def test_unknown_validity_disables_immediate_order(self):
        self.price(valid_for=None)
        response = self.client.get(self.url())
        self.assertFalse(response.context['variants'][0].price_orderable)
        self.assertContains(response, 'data-order-disabled')

    def test_valid_price_allows_order(self):
        self.price()
        response = self.client.get(self.url())
        self.assertTrue(response.context['variants'][0].price_orderable)
        self.assertNotContains(response, 'data-order-disabled')

    def test_latest_approved_price_wins(self):
        self.price(amount='300000')
        later = self.price(amount='310000')
        self.price(amount='999999', status='pending')
        variant = self.client.get(self.url()).context['variants'][0]
        self.assertEqual(variant.latest_price_observation_id, later.pk)


class PriceListCsvTests(CatalogFixtureMixin, TestCase):
    def rows(self):
        response = self.client.get(reverse('catalog:category_price_list', args=[self.category.slug]))
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertEqual(response['Cache-Control'], 'no-store')
        return list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))

    def test_formula_injection_is_neutralised(self):
        self.product.name = '=HYPERLINK("http://evil","x")'
        self.product.save()
        self.variant.name = '+cmd|calc'
        self.variant.size = '-2+3'
        self.variant.grade = '@SUM(A1)'
        self.variant.save()
        self.manufacturer.name = '\t=1+1'
        self.manufacturer.save()
        self.price(delivery_location='=1+1', unit_label='@x')
        header, row = self.rows()
        for cell in row:
            self.assertFalse(cell.startswith(('=', '+', '-', '@', '\t', '\r')), cell)
        self.assertEqual(row[0], '\'=HYPERLINK("http://evil","x")')
        self.assertIn("'-2+3", row)

    def test_states_and_pending_exclusion(self):
        self.price(valid_for=-timedelta(minutes=5))
        self.price(amount='777777', status='pending')
        header, row = self.rows()
        self.assertIn('منقضی', row)
        self.assertNotIn('777777', row)
        self.assertEqual(len(header), len(row))

    def test_no_price_row(self):
        header, row = self.rows()
        self.assertIn('بدون قیمت', row)


class CompareTests(CatalogFixtureMixin, TestCase):
    def make_variants(self, count):
        return [
            ProductVariant.objects.create(product=self.product, name=f'گونه {index}', size=str(20 + index), unit='kg')
            for index in range(count)
        ]

    def test_session_limit(self):
        variants = [self.variant, *self.make_variants(COMPARE_LIMIT)]
        for variant in variants:
            self.client.post(reverse('catalog:compare_add', args=[variant.pk]))
        self.assertEqual(len(self.client.session[COMPARE_SESSION_KEY]), COMPARE_LIMIT)
        response = self.client.get(reverse('catalog:compare'))
        self.assertEqual(len(response.context['variants']), COMPARE_LIMIT)

    def test_tampered_session_is_sanitised(self):
        session = self.client.session
        session[COMPARE_SESSION_KEY] = ['1 OR 1=1', str(self.variant.pk), '<script>', -1, *['9999'] * 10]
        session.save()
        response = self.client.get(reverse('catalog:compare'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([v.pk for v in response.context['variants']], [self.variant.pk])

    def test_compare_add_requires_post_and_blocks_open_redirect(self):
        url = reverse('catalog:compare_add', args=[self.variant.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        for target in ('https://evil.example/', '//evil.example', '/\\evil.example'):
            response = self.client.post(url, {'next': target})
            self.assertEqual(response['Location'], self.product.get_absolute_url())
        response = self.client.post(url, {'next': '/steel/'})
        self.assertEqual(response['Location'], '/steel/')

    def test_merge_session_into_db_respects_limit_and_activity(self):
        user = get_user_model().objects.create_user('buyer')
        profile = CustomerProfile.objects.create(user=user, mobile='09120000001')
        variants = self.make_variants(5)
        variants[4].is_active = False
        variants[4].save()
        comparison = SavedComparison.objects.create(profile=profile)
        SavedComparisonItem.objects.create(comparison=comparison, variant=variants[0], position=0)
        SavedComparisonItem.objects.create(comparison=comparison, variant=variants[1], position=1)
        session = {COMPARE_SESSION_KEY: [str(variants[4].pk), str(variants[1].pk), str(variants[2].pk), str(variants[3].pk), str(self.variant.pk)]}
        merge_session_comparison(profile, session)
        ids = list(comparison.items.values_list('variant_id', flat=True))
        self.assertEqual(ids, [variants[0].pk, variants[1].pk, variants[2].pk, variants[3].pk])
        self.assertNotIn(COMPARE_SESSION_KEY, session)

    def test_db_comparison_limit_and_remove_reorders(self):
        user = get_user_model().objects.create_user('buyer2')
        CustomerProfile.objects.create(user=user, mobile='09120000002')
        self.client.force_login(user)
        variants = [self.variant, *self.make_variants(COMPARE_LIMIT)]
        for variant in variants:
            self.client.post(reverse('catalog:compare_add', args=[variant.pk]))
        self.assertEqual(SavedComparisonItem.objects.count(), COMPARE_LIMIT)
        self.client.post(reverse('catalog:compare_remove', args=[variants[0].pk]))
        positions = list(SavedComparisonItem.objects.order_by('position').values_list('position', flat=True))
        self.assertEqual(positions, [0, 1, 2])
        self.assertTrue(self.client.get(reverse('catalog:compare')).context['saved_comparison'])

    def test_best_price_only_for_comparable_prices(self):
        other = self.make_variants(1)[0]
        self.price(amount='300000')
        self.price(variant=other, amount='290000')
        for variant in (self.variant, other):
            self.client.post(reverse('catalog:compare_add', args=[variant.pk]))
        best = {v.pk: v.is_best_price for v in self.client.get(reverse('catalog:compare')).context['variants']}
        self.assertEqual(best, {self.variant.pk: False, other.pk: True})
        self.price(variant=other, amount='10', currency='USD')
        best = {v.pk: v.is_best_price for v in self.client.get(reverse('catalog:compare')).context['variants']}
        self.assertFalse(any(best.values()))


class PriceHistoryTests(CatalogFixtureMixin, TestCase):
    def url(self, **params):
        return reverse('catalog:price_history', args=[self.product.slug]), params

    def test_ranges_and_bad_params(self):
        old = self.price(amount='250000')
        PriceObservation.objects.filter(pk=old.pk).update(observed_at=timezone.now() - timedelta(days=60))
        self.price(amount='300000')
        url, _ = self.url()
        response = self.client.get(url, {'range': 'bogus', 'variant': 'abc', 'page': 'x'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_range'], '30d')
        self.assertEqual(response.context['series_count'], 1)
        response = self.client.get(url, {'range': '90d'})
        self.assertEqual(response.context['series_count'], 2)
        self.assertTrue(response.context['chart_points'])
        response = self.client.get(url, {'range': 'all', 'variant': '٩٩٩٩٩٩٩٩٩٩٩٩٩٩٩٩٩٩'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_variant'], self.variant)

    def test_variant_of_other_product_is_ignored(self):
        other_product = Product.objects.create(category=self.category, name='دیگر', slug='other')
        foreign = ProductVariant.objects.create(product=other_product, name='بیگانه', unit='kg')
        self.price(variant=foreign, amount='123456')
        url, _ = self.url()
        response = self.client.get(url, {'variant': foreign.pk})
        self.assertEqual(response.context['selected_variant'], self.variant)
        self.assertNotContains(response, '123456')

    def test_series_uses_only_latest_currency_and_basis(self):
        self.price(amount='30', currency='USD')
        self.price(amount='300000')
        url, _ = self.url()
        response = self.client.get(url)
        self.assertEqual(response.context['series_currency'], 'IRR')
        self.assertEqual(response.context['series_count'], 1)

    def test_product_without_variants(self):
        ProductVariant.objects.all().delete()
        url, _ = self.url()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['selected_variant'])


class PersianSearchTests(CatalogFixtureMixin, TestCase):
    def test_normalisation(self):
        self.assertEqual(normalize_fa('ميلگرد ۱۲'), 'میلگرد 12')
        self.assertEqual(normalize_fa('آهن‌آلات'), 'آهن آلات')
        self.assertEqual(normalize_fa('a\x00b\x1fc'), 'a b c')
        self.assertEqual(tokens('قیمت امروز'), ['قیمت', 'امروز'])
        self.assertLessEqual(len(tokens(' '.join(['کلمه'] * 50))), 6)

    def test_arabic_letters_and_persian_digits_find_products(self):
        for query in ('ميلگرد', 'میلگرد ۱۲', 'ميلگرد 12 ذوب', 'rb-12'):
            response = self.client.get(reverse('core:search'), {'q': query})
            self.assertEqual(response.context['products'], [self.product], query)

    def test_did_you_mean_for_typo(self):
        response = self.client.get(reverse('core:search'), {'q': 'میلگرت آجدار'})
        self.assertEqual(response.context['suggestion'], 'میلگرد آجدار')
        self.assertEqual(response.context['products'], [self.product])

    def test_nul_and_control_characters_do_not_match_everything(self):
        for query in ('\x00', '\x00\x00', '\x1f'):
            response = self.client.get(reverse('core:search'), {'q': query})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['products'], [])
            payload = self.client.get(reverse('core:search_suggestions'), {'q': query}).json()
            self.assertEqual(payload['results'], [])

    def test_huge_query_is_truncated(self):
        response = self.client.get(reverse('core:search'), {'q': 'ي' * 10000})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['query']), 100)
        self.assertEqual(self.client.get(reverse('core:search_suggestions'), {'q': 'a' * 10000}).status_code, 200)

    def test_suggestions_require_get(self):
        self.assertEqual(self.client.post(reverse('core:search_suggestions'), {'q': 'میلگرد'}).status_code, 405)
