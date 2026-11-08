from django.test import TestCase

from catalog.models import Category, Product, ProductVariant
from core.models import AuditLog
from core.search import did_you_mean, normalize_fa, tokens


class PersianSearchTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name='تیرآهن تست', slug='beam-test')
        product = Product.objects.create(category=category, name='میلگرد آجدار', slug='rebar-x')
        ProductVariant.objects.create(product=product, name='سایز ۱۲', size='12', sku='X1')

    def test_normalisation(self):
        self.assertEqual(normalize_fa('ميلگرد  ۱۲'), 'میلگرد 12')
        self.assertEqual(normalize_fa('آهن‌آلات'), 'آهن آلات')
        self.assertEqual(tokens('قیمت میلگرد ۱۲'), ['میلگرد', '12'])

    def test_arabic_letters_and_persian_digits_match(self):
        response = self.client.get('/search/', {'q': 'ميلگرد ۱۲'})
        self.assertContains(response, 'میلگرد آجدار')

    def test_typo_suggestion(self):
        self.assertEqual(did_you_mean('میلگرت'), 'میلگرد')
        response = self.client.get('/search/', {'q': 'میلگرت آجدار'})
        self.assertContains(response, 'منظورتان')
        self.assertContains(response, 'میلگرد آجدار')

    def test_suggestions_endpoint(self):
        data = self.client.get('/search/suggestions/', {'q': 'ميلگرد'}).json()
        self.assertTrue(any('میلگرد' in item['label'] for item in data['results']))


class AuditLogTests(TestCase):
    def test_create_and_update_are_logged(self):
        category = Category.objects.create(name='الف', slug='a-cat')
        category.name = 'ب'
        category.save()
        actions = list(AuditLog.objects.filter(model_label='catalog.Category').values_list('action', flat=True))
        self.assertIn('create', actions)
        update = AuditLog.objects.get(model_label='catalog.Category', action='update')
        self.assertEqual(update.changes['name'], ['الف', 'ب'])
