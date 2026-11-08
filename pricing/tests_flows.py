import tempfile
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category, Product, ProductVariant
from pricing.models import (
    InventoryLocation, PriceObservation, PriceObservationTask, PriceReviewEvent, ShippingRate, StockObservation,
)
from pricing.shipping import combined_total, estimate, find_rate


class PricingFixtureMixin:
    def setUp(self):
        User = get_user_model()
        self.operator = User.objects.create_user('pricing-operator')
        self.category = Category.objects.create(name='تست قیمت', slug='pricing-test')
        self.product = Product.objects.create(category=self.category, name='میلگرد تست', slug='pricing-product')
        self.variant = ProductVariant.objects.create(product=self.product, name='۱۲', unit='kg', sku='PR-12')
        self.location = InventoryLocation.objects.create(name='انبار تست', city='تهران')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def observation(self, **kwargs):
        defaults = {
            'variant': self.variant, 'amount': Decimal('300000'), 'currency': 'IRR', 'price_basis': 'kg',
            'valid_until': timezone.now() + timedelta(days=1), 'created_by': self.operator,
        }
        defaults.update(kwargs)
        return PriceObservation.objects.create(**defaults)

    def write_csv(self, text, name='data.csv', encoding='utf-8'):
        path = Path(self.tmp.name) / name
        path.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
        return str(path)


class ApprovalWorkflowTests(PricingFixtureMixin, TestCase):
    def test_new_observation_is_pending_and_logged(self):
        observation = self.observation()
        self.assertEqual(observation.status, PriceObservation.Status.PENDING)
        self.assertEqual(PriceReviewEvent.objects.filter(observation=observation).count(), 1)
        self.assertFalse(PriceObservationTask.objects.exists())

    def test_cannot_save_approved_without_approver(self):
        with self.assertRaises(ValidationError):
            self.observation(status=PriceObservation.Status.APPROVED)

    def test_approve_enqueues_task_and_logs_event(self):
        observation = self.observation()
        observation.approve(self.operator)
        self.assertEqual(PriceObservationTask.objects.filter(observation=observation).count(), 1)
        self.assertTrue(PriceReviewEvent.objects.filter(observation=observation, to_status='approved').exists())

    def test_rejected_cannot_be_approved_and_only_pending_can_be_rejected(self):
        observation = self.observation()
        observation.reject(self.operator, 'x' * 900)
        self.assertEqual(len(PriceReviewEvent.objects.get(to_status='rejected').note), 500)
        with self.assertRaises(ValidationError):
            observation.approve(self.operator)
        with self.assertRaises(ValidationError):
            observation.reject(self.operator)
        approved = self.observation()
        approved.approve(self.operator)
        with self.assertRaises(ValidationError):
            approved.reject(self.operator)

    def test_observation_values_are_immutable(self):
        observation = self.observation()
        observation.amount = Decimal('1')
        with self.assertRaises(ValidationError):
            observation.save()

    def test_stock_rejected_cannot_be_approved(self):
        stock = StockObservation.objects.create(
            variant=self.variant, location=self.location, quantity=Decimal('5'), unit='ton',
            valid_until=timezone.now() + timedelta(days=1),
        )
        stock.reject(self.operator)
        with self.assertRaises(ValidationError):
            stock.approve(self.operator)


class AdminApprovalPermissionTests(PricingFixtureMixin, TestCase):
    def staff(self, username, *codenames):
        user = get_user_model().objects.create_user(username, password='pw-123456789', is_staff=True)
        user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
        self.client.force_login(user)
        return user

    def run_action(self, model, action, pk):
        url = reverse(f'admin:pricing_{model}_changelist')
        return self.client.post(url, {'action': action, '_selected_action': [pk], 'index': 0})

    def test_view_only_staff_cannot_approve_or_reject_prices(self):
        observation = self.observation()
        self.staff('viewer', 'view_priceobservation')
        changelist = self.client.get(reverse('admin:pricing_priceobservation_changelist'))
        self.assertEqual(changelist.status_code, 200)
        self.assertNotContains(changelist, 'approve_prices')
        for action in ('approve_prices', 'reject_prices'):
            self.run_action('priceobservation', action, observation.pk)
            observation.refresh_from_db()
            self.assertEqual(observation.status, PriceObservation.Status.PENDING)

    def test_view_only_staff_cannot_approve_stock(self):
        stock = StockObservation.objects.create(
            variant=self.variant, location=self.location, quantity=Decimal('5'), unit='ton',
            valid_until=timezone.now() + timedelta(days=1),
        )
        self.staff('stock-viewer', 'view_stockobservation')
        self.run_action('stockobservation', 'approve_stock', stock.pk)
        stock.refresh_from_db()
        self.assertEqual(stock.status, StockObservation.Status.PENDING)

    def test_change_permission_allows_approval_and_records_actor(self):
        observation = self.observation()
        user = self.staff('approver', 'view_priceobservation', 'change_priceobservation')
        response = self.run_action('priceobservation', 'approve_prices', observation.pk)
        self.assertEqual(response.status_code, 302)
        observation.refresh_from_db()
        self.assertEqual(observation.status, PriceObservation.Status.APPROVED)
        self.assertEqual(observation.approved_by, user)

    def test_admin_action_skips_non_pending(self):
        observation = self.observation()
        observation.reject(self.operator)
        self.staff('approver2', 'view_priceobservation', 'change_priceobservation')
        self.run_action('priceobservation', 'approve_prices', observation.pk)
        observation.refresh_from_db()
        self.assertEqual(observation.status, PriceObservation.Status.REJECTED)

    def test_anonymous_and_non_staff_cannot_reach_admin(self):
        observation = self.observation()
        response = self.run_action('priceobservation', 'approve_prices', observation.pk)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])
        observation.refresh_from_db()
        self.assertEqual(observation.status, PriceObservation.Status.PENDING)

    def test_view_only_staff_cannot_retry_failed_tasks(self):
        observation = self.observation()
        observation.approve(self.operator)
        task = PriceObservationTask.objects.get()
        task.status = PriceObservationTask.Status.FAILED
        task.save()
        self.staff('task-viewer', 'view_priceobservationtask')
        self.run_action('priceobservationtask', 'retry_price_tasks', task.pk)
        task.refresh_from_db()
        self.assertEqual(task.status, PriceObservationTask.Status.FAILED)


class ImportCatalogTests(PricingFixtureMixin, TestCase):
    header = 'category_slug,product_slug,product_name,variant_sku,variant_name,unit,manufacturer_slug,manufacturer_name,weight_per_unit_kg\n'

    def run_import(self, text, *args):
        call_command('import_catalog', self.write_csv(text), *args, stdout=StringIO())

    def test_dry_run_then_commit(self):
        text = self.header + 'pricing-test,new-product,کالای نو,NEW-1,گونه,ton,mfr,کارخانه,10.5\n'
        self.run_import(text)
        self.assertFalse(Product.objects.filter(slug='new-product').exists())
        self.run_import(text, '--commit')
        self.assertTrue(ProductVariant.objects.filter(sku='NEW-1', product__slug='new-product').exists())

    def assert_rejected(self, text, *, message=None):
        with self.assertRaises(CommandError) as raised:
            self.run_import(text, '--commit')
        if message:
            self.assertIn(message, str(raised.exception))
        self.assertFalse(Product.objects.filter(slug__startswith='bad').exists())

    def test_malformed_rows_are_rejected(self):
        cases = [
            self.header + 'pricing-test,bad-extra,P,B-1,V,ton,,,,EXTRA\n',
            self.header + 'pricing-test,bad slug!,P,B-1,V,ton,,,\n',
            self.header + 'pricing-test,bad-nul,P\x00,B-1,V,ton,,,\n',
            self.header + f'pricing-test,bad-long,{"x" * 181},B-1,V,ton,,,\n',
            self.header + 'pricing-test,bad-weight,P,B-1,V,ton,,,1e30\n',
            self.header + 'pricing-test,bad-weight2,P,B-1,V,ton,,,0.0001\n',
            self.header + 'pricing-test,bad-weight3,P,B-1,V,ton,,,NaN\n',
            self.header + 'pricing-test,bad-unit,P,B-1,V,gallon,,,\n',
            self.header + 'missing-cat,bad-cat,P,B-1,V,ton,,,\n',
            self.header + 'pricing-test,bad-mfr,P,B-1,V,ton,only-slug,,\n',
            self.header + 'pricing-test,bad-dup,P,B-1,V,ton,,,\npricing-test,bad-dup2,P,B-1,V,ton,,,\n',
            self.header + 'pricing-test,pricing-product,P,B-1,V,ton,,,\n',
        ]
        for text in cases:
            with self.subTest(text=text[-40:]):
                self.assert_rejected(text)
        self.assertFalse(ProductVariant.objects.filter(sku='B-1').exists())

    def test_inactive_category_rejected(self):
        Category.objects.create(name='غیرفعال', slug='inactive-cat', is_active=False)
        self.assert_rejected(self.header + 'inactive-cat,bad-inactive,P,B-1,V,ton,,,\n')

    def test_oversized_field_and_file_rejected(self):
        self.assert_rejected(self.header + f'pricing-test,bad-huge,{"x" * 200000},B-1,V,ton,,,\n', message='CSV')
        with mock.patch('catalog.csv_import.MAX_FILE_BYTES', 10):
            self.assert_rejected(self.header + 'pricing-test,bad-size,P,B-1,V,ton,,,\n', message='حجم')
        with mock.patch('catalog.csv_import.MAX_ROWS', 1):
            self.assert_rejected(self.header + 'pricing-test,bad-r1,P,B-1,V,ton,,,\npricing-test,bad-r2,P,B-2,V,ton,,,\n')

    def test_non_utf8_missing_columns_and_empty(self):
        with self.assertRaises(CommandError):
            call_command('import_catalog', self.write_csv(b'\xff\xfe\x00garbage'), stdout=StringIO())
        self.assert_rejected('category_slug,product_slug\nx,y\n', message='ستون')
        self.assert_rejected(self.header, message='ردیفی')
        with self.assertRaises(CommandError):
            call_command('import_catalog', '/nonexistent/file.csv', stdout=StringIO())

    def test_commit_is_transactional(self):
        text = self.header + (
            'pricing-test,bad-a,P,TX-1,V,ton,,,\n'
            'pricing-test,bad-b,P2,TX-2,V,ton,,,\n'
        )
        original = ProductVariant.objects.create
        calls = []

        def flaky(**kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise RuntimeError('boom')
            return original(**kwargs)

        with mock.patch.object(ProductVariant.objects, 'create', side_effect=flaky):
            with self.assertRaises(RuntimeError):
                self.run_import(text, '--commit')
        self.assertFalse(Product.objects.filter(slug__in=('bad-a', 'bad-b')).exists())
        self.assertFalse(ProductVariant.objects.filter(sku__startswith='TX-').exists())


class ImportPricesTests(PricingFixtureMixin, TestCase):
    header = 'variant_sku,amount,currency,price_basis,observed_at,valid_until,is_available,tax_included\n'

    def run_import(self, text, *args):
        call_command('import_prices', self.write_csv(text), *args, stdout=StringIO())

    def test_import_creates_pending_observations_only(self):
        self.run_import(self.header + 'PR-12,۳۰۰۰۰۰,irr,KG,2026-11-01T10:00:00+03:30,2026-11-02T10:00:00+03:30,بله,\n', '--commit')
        observation = PriceObservation.objects.get()
        self.assertEqual(observation.status, PriceObservation.Status.PENDING)
        self.assertEqual(observation.amount, Decimal('300000'))
        self.assertIsNone(observation.tax_included)
        self.assertFalse(PriceObservationTask.objects.exists())

    def test_invalid_rows_abort_whole_import(self):
        good = 'PR-12,300000,IRR,kg,,,,\n'
        cases = [
            'PR-12,1000000000000000000000,IRR,kg,,,,\n',
            'PR-12,0,IRR,kg,,,,\n',
            'PR-12,12.5,IRR,kg,,,,\n',
            'PR-12,abc,IRR,kg,,,,\n',
            'PR-12,Infinity,IRR,kg,,,,\n',
            'PR-12,300000,EUR,kg,,,,\n',
            'PR-12,300000,IRR,gallon,,,,\n',
            'NOPE,300000,IRR,kg,,,,\n',
            'PR-12,300000,IRR,kg,2026-11-02T10:00:00+03:30,2026-11-01T10:00:00+03:30,,\n',
            'PR-12,300000,IRR,kg,yesterday,,,\n',
            'PR-12,300000,IRR,kg,,,maybe,\n',
            'PR-12,300000,IRR,kg,,,,,EXTRA\n',
            'PR-12,=cmd|calc,IRR,kg,,,,\n',
        ]
        for bad in cases:
            with self.subTest(bad=bad):
                with self.assertRaises(CommandError):
                    self.run_import(self.header + good + bad, '--commit')
        self.assertFalse(PriceObservation.objects.exists())

    def test_malformed_csv_structure(self):
        with self.assertRaises(CommandError):
            self.run_import(self.header + f'PR-12,1,IRR,kg,,,,"{"x" * 200000}"\n', '--commit')
        with self.assertRaises(CommandError):
            call_command('import_prices', self.write_csv(b'\xff\xfe\x00\x01'), '--commit', stdout=StringIO())
        self.assertFalse(PriceObservation.objects.exists())


class ImportStockTests(PricingFixtureMixin, TestCase):
    header = 'variant_sku,location_name,quantity,unit,is_available,valid_until,observed_at\n'

    def run_import(self, text, *args):
        call_command('import_stock', self.write_csv(text), *args, stdout=StringIO())

    def test_valid_import(self):
        self.run_import(self.header + 'PR-12,انبار تست,12.5,ton,بله,2030-01-01T00:00:00+03:30,\n', '--commit')
        stock = StockObservation.objects.get()
        self.assertEqual(stock.status, StockObservation.Status.PENDING)

    def test_invalid_rows(self):
        cases = [
            'PR-12,انبار تست,-1,ton,yes,2030-01-01T00:00:00+03:30,\n',
            'PR-12,انبار تست,1.0001,ton,yes,2030-01-01T00:00:00+03:30,\n',
            'PR-12,انبار تست,1,ton,yes,2030-01-01T00:00:00,\n',
            'PR-12,انبار تست,1,ton,yes,,\n',
            'PR-12,ناشناخته,1,ton,yes,2030-01-01T00:00:00+03:30,\n',
            'PR-12,انبار تست,1,ton,,2030-01-01T00:00:00+03:30,\n',
            'PR-12,انبار تست,1,ton,yes,2030-01-01T00:00:00+03:30,2031-01-01T00:00:00+03:30\n',
            'PR-12,انبار تست,1,ton,yes,2030-01-01T00:00:00+03:30,,EXTRA\n',
        ]
        for bad in cases:
            with self.subTest(bad=bad):
                with self.assertRaises(CommandError):
                    self.run_import(self.header + bad, '--commit')
        self.assertFalse(StockObservation.objects.exists())

    def test_inactive_location_rejected(self):
        self.location.is_active = False
        self.location.save()
        with self.assertRaises(CommandError):
            self.run_import(self.header + 'PR-12,انبار تست,1,ton,yes,2030-01-01T00:00:00+03:30,\n', '--commit')


class ProcessPriceEventsTests(PricingFixtureMixin, TestCase):
    def test_processes_queue(self):
        observation = self.observation()
        observation.approve(self.operator)
        call_command('process_price_events', stdout=StringIO())
        task = PriceObservationTask.objects.get()
        self.assertEqual(task.status, PriceObservationTask.Status.COMPLETE)
        self.assertEqual(task.attempts, 1)

    def test_failure_backs_off_then_fails(self):
        observation = self.observation()
        observation.approve(self.operator)
        with mock.patch(
            'pricing.management.commands.process_price_events.process_approved_price_observation',
            side_effect=RuntimeError('x'),
        ):
            call_command('process_price_events', stdout=StringIO())
            task = PriceObservationTask.objects.get()
            self.assertEqual(task.status, PriceObservationTask.Status.PENDING)
            self.assertEqual(task.last_error, 'RuntimeError')
            self.assertGreater(task.available_at, timezone.now())
            for _ in range(10):
                PriceObservationTask.objects.update(available_at=timezone.now() - timedelta(seconds=1))
                call_command('process_price_events', stdout=StringIO())
        task.refresh_from_db()
        self.assertEqual(task.status, PriceObservationTask.Status.FAILED)
        self.assertEqual(task.attempts, 8)

    def test_limit_validation(self):
        with self.assertRaises(CommandError):
            call_command('process_price_events', '--limit', '0', stdout=StringIO())


class PriceFreshnessTests(PricingFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        ProductVariant.objects.exclude(pk=self.variant.pk).update(is_active=False)

    def test_missing_price_exits_with_error(self):
        with self.assertRaises(SystemExit) as raised:
            call_command('price_freshness', stdout=StringIO())
        self.assertEqual(raised.exception.code, 1)

    def test_expired_and_unknown_validity_exit_with_error(self):
        for valid_until in (timezone.now() - timedelta(hours=1), None):
            PriceObservation.objects.filter(variant=self.variant).update(status='rejected')
            observation = self.observation(valid_until=valid_until)
            observation.approve(self.operator)
            with self.assertRaises(SystemExit):
                call_command('price_freshness', stdout=StringIO())

    def test_fresh_prices_exit_cleanly(self):
        observation = self.observation()
        observation.approve(self.operator)
        self.observation(amount=Decimal('1'))  # pending price is ignored
        out = StringIO()
        call_command('price_freshness', stdout=out)
        self.assertIn('100٪', out.getvalue())


class ShippingTests(PricingFixtureMixin, TestCase):
    def rate(self, **kwargs):
        defaults = {
            'origin_city': 'اصفهان', 'destination_city': 'تهران', 'per_tonne': Decimal('1000'),
            'currency': 'IRT', 'valid_until': timezone.now() + timedelta(days=1),
        }
        defaults.update(kwargs)
        return ShippingRate.objects.create(**defaults)

    def test_method_specific_rate_wins_and_falls_back(self):
        generic = self.rate(per_tonne=Decimal('900'))
        truck = self.rate(method='truck', per_tonne=Decimal('1200'))
        self.assertEqual(find_rate('اصفهان', 'تهران', Decimal('5'), 'truck'), truck)
        self.assertEqual(find_rate('اصفهان', 'تهران', Decimal('5'), 'trailer'), generic)
        self.assertEqual(find_rate('اصفهان', 'تهران', Decimal('5')), generic)

    def test_expired_inactive_and_weight_bounds(self):
        self.rate(valid_until=timezone.now() - timedelta(minutes=1))
        self.rate(is_active=False)
        self.assertIsNone(find_rate('اصفهان', 'تهران', Decimal('5')))
        bounded = self.rate(minimum_tonnes=Decimal('10'), maximum_tonnes=Decimal('20'), base_fee=Decimal('500'))
        self.assertIsNone(find_rate('اصفهان', 'تهران', Decimal('5')))
        self.assertIsNone(find_rate('اصفهان', 'تهران', Decimal('25')))
        result = estimate('اصفهان', 'تهران', Decimal('10.5'))
        self.assertEqual(result['rate'], bounded)
        self.assertEqual(result['amount'], Decimal('11000'))

    def test_combined_total_mixed_currency(self):
        shipping = {'amount': Decimal('100'), 'currency': 'IRT'}
        self.assertEqual(combined_total([('IRR', Decimal('1000'))], shipping), Decimal('2000'))
        self.assertIsNone(combined_total([('USD', Decimal('1'))], shipping))
        self.assertIsNone(combined_total([('IRR', Decimal('1'))], {'amount': Decimal('1'), 'currency': 'USD'}))
        self.assertIsNone(combined_total([], shipping))

    def test_shipping_calculator_view(self):
        self.rate(method='truck')
        url = reverse('core:shipping_calculator')
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {
            'origin_city': 'اصفهان', 'destination_city': 'تهران', 'weight_tonnes': '۲', 'method': 'truck',
        })
        self.assertEqual(response.context['result']['amount'], Decimal('2000'))
        for data in (
            {'origin_city': '<script>alert(7)', 'destination_city': 'تهران', 'weight_tonnes': '1'},
            {'origin_city': 'اصفهان', 'destination_city': 'تهران', 'weight_tonnes': '-1'},
            {'origin_city': 'اصفهان', 'destination_city': 'تهران', 'weight_tonnes': 'NaN'},
            {'origin_city': 'اصفهان', 'destination_city': 'تهران', 'weight_tonnes': '1', 'method': 'rocket'},
        ):
            response = self.client.post(url, data)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.context['result'])
            self.assertNotContains(response, '<script>alert(7)')

    def test_shipping_calculator_reports_unavailable_route(self):
        self.rate()
        self.rate(origin_city='تبریز', destination_city='مشهد')
        response = self.client.post(reverse('core:shipping_calculator'), {
            'origin_city': 'تبریز', 'destination_city': 'تهران', 'weight_tonnes': '1',
        })
        self.assertTrue(response.context['unavailable'])


class WeightCalculatorTests(PricingFixtureMixin, TestCase):
    url = '/tools/weight/'

    def test_round_bar_with_persian_digits(self):
        response = self.client.post(self.url, {
            'calculation_type': 'round_bar', 'diameter_mm': '۱۲', 'length_m': '۱۲', 'count': '۱۰',
        })
        self.assertEqual(response.context['result']['weight_kg'], Decimal('106.538'))

    def test_catalog_variant_weight(self):
        self.variant.weight_per_unit_kg = Decimal('10.656')
        self.variant.save()
        response = self.client.post(self.url, {'calculation_type': 'catalog', 'variant': self.variant.pk, 'count': '2'})
        self.assertEqual(response.context['result']['weight_kg'], Decimal('21.312'))

    def test_invalid_inputs(self):
        hidden = ProductVariant.objects.create(
            product=self.product, name='غیرفعال', unit='kg', weight_per_unit_kg=Decimal('1'), is_active=False,
        )
        for data in (
            {'calculation_type': 'pipe', 'diameter_mm': '10', 'thickness_mm': '5', 'length_m': '1', 'count': '1'},
            {'calculation_type': 'catalog', 'variant': hidden.pk, 'count': '1'},
            {'calculation_type': 'catalog', 'variant': '1 OR 1=1', 'count': '1'},
            {'calculation_type': 'plate', 'thickness_mm': '1e400', 'width_mm': '1', 'length_mm': '1', 'count': '1'},
            {'calculation_type': 'round_bar', 'diameter_mm': '12', 'length_m': '12', 'count': '1.5'},
            {'calculation_type': 'nope'},
        ):
            response = self.client.post(self.url, data)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.context['result'], data)
