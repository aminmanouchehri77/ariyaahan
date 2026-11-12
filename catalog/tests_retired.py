from django.test import TestCase

from catalog.models import Category


class RetiredCategoryTests(TestCase):
    """«مواد اولیه» and «فروآلیاژ» are retired (inactive, not deleted)."""

    def test_categories_and_children_are_inactive(self):
        for slug in ('raw-materials', 'ferroalloy'):
            category = Category.objects.get(slug=slug)
            self.assertFalse(category.is_active)
            self.assertFalse(Category.objects.filter(parent=category, is_active=True).exists())

    def test_not_public(self):
        self.assertEqual(self.client.get('/steel/ferroalloy/').status_code, 404)
        self.assertEqual(self.client.get('/steel/raw-materials/').status_code, 404)
        for path in ('/', '/steel/', '/sitemap.xml'):
            body = self.client.get(path).content.decode()
            self.assertNotIn('فروآلیاژ', body)
            self.assertNotIn('/steel/raw-materials/', body)
