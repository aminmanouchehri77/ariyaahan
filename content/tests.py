from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.utils import timezone

from pricing.models import ShippingRate
from pricing.shipping import estimate

from .forms import CompanyRequestForm
from .models import Article, CompanyRequest


class CompanyRequestStatusTests(TestCase):
    def setUp(self):
        self.record = CompanyRequest.objects.create(kind='feedback', name='تست', mobile='09120000000', message='پیام')

    def test_status_page_is_reachable(self):
        response = self.client.get(f'/company/requests/{self.record.public_id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    def test_old_shared_path_redirects(self):
        response = self.client.get(f'/requests/{self.record.public_id}/')
        self.assertRedirects(response, f'/company/requests/{self.record.public_id}/', status_code=301)

    def test_unknown_id_is_404(self):
        self.assertEqual(self.client.get('/requests/00000000-0000-0000-0000-000000000000/').status_code, 404)


class ExportFormTests(TestCase):
    def test_quantity_and_terms_required_for_export_only(self):
        form = CompanyRequestForm(data={}, kind=CompanyRequest.Kind.EXPORT)
        form.is_valid()
        self.assertIn('quantity_tonnes', form.errors)
        self.assertIn('delivery_terms', form.errors)
        self.assertNotIn('quantity_tonnes', CompanyRequestForm(kind=CompanyRequest.Kind.CAREER).fields)


class ShippingMethodTests(TestCase):
    def setUp(self):
        later = timezone.now() + timedelta(days=3)
        common = {'origin_city': 'اصفهان', 'destination_city': 'تهران', 'valid_until': later}
        ShippingRate.objects.create(per_tonne=Decimal('100'), **common)
        ShippingRate.objects.create(per_tonne=Decimal('150'), method='light', **common)

    def test_exact_method_rate_wins(self):
        self.assertEqual(estimate('اصفهان', 'تهران', Decimal('2'), 'light')['amount'], Decimal('300'))

    def test_falls_back_to_general_rate(self):
        self.assertEqual(estimate('اصفهان', 'تهران', Decimal('2'), 'trailer')['amount'], Decimal('200'))
        self.assertEqual(estimate('اصفهان', 'تهران', Decimal('2'))['amount'], Decimal('200'))


class ArticlePreviewTests(TestCase):
    def setUp(self):
        self.article = Article.objects.create(title='پیش‌نویس', slug='draft-a', excerpt='خلاصه', body='متن')

    def test_draft_hidden_from_public(self):
        self.assertEqual(self.client.get('/mag/draft-a/?preview=1').status_code, 404)

    def test_editor_can_preview(self):
        editor = User.objects.create_user('editor', password='x', is_staff=True)
        editor.user_permissions.add(Permission.objects.get(codename='change_article'))
        self.client.force_login(editor)
        response = self.client.get('/mag/draft-a/?preview=1')
        self.assertContains(response, 'پیش‌نمایش ویرایشگر')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')


class ProposalPathTests(TestCase):
    def test_site_map_aliases(self):
        self.assertRedirects(self.client.get('/market/offers/'), '/market/sell/', status_code=301, fetch_redirect_response=False)
        self.assertRedirects(self.client.get('/market/requests/'), '/market/buy/', status_code=301, fetch_redirect_response=False)
