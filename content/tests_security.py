"""Security and flow tests for company pages, requests, magazine and product feedback."""

from datetime import timedelta
from io import StringIO
import uuid

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomerProfile
from catalog.models import Category, Product
from inquiries.models import Inquiry
from marketplace.models import MarketplaceListing

from .models import (
    Article, ArticleComment, ArticleTag, CompanyPage, CompanyRequest, FAQ, MediaItem, ProductQuestion, ProductReview,
)

XSS_PAYLOAD = (
    '<script>alert("s1")</script>\n\n'
    '[click](javascript:alert("s2"))\n\n'
    '<img src="x" onerror="alert(\'s3\')">\n\n'
    '<a href="data:text/html;base64,PHNjcmlwdD4=">d</a>\n\n'
    '<iframe src="https://evil.example/"></iframe>\n\n'
    '[out](https://evil.example/page)\n\n'
    '<svg onload="alert(1)"></svg>'
)


def assert_sanitised(test, html):
    lowered = html.lower()
    for needle in ('<script>alert', 'javascript:', 'onerror', 'onload', 'data:text/html', '<iframe', '<svg'):
        test.assertNotIn(needle, lowered, needle)


class CleanCacheMixin:
    def setUp(self):
        cache.clear()
        super().setUp()


class CompanyPageTests(CleanCacheMixin, TestCase):
    def test_unpublished_page_falls_back_to_noindex_placeholder(self):
        CompanyPage.objects.create(kind='about', slug='about-us', title='متن محرمانه', body='پیش‌نویس محرمانه')
        response = self.client.get(reverse('content:about'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'پیش‌نویس محرمانه')
        self.assertContains(response, 'noindex')
        self.assertEqual(self.client.get('/pages/about-us/').status_code, 404)

    def test_published_page_body_is_sanitised(self):
        CompanyPage.objects.create(kind='privacy', slug='privacy', title='حریم', body=XSS_PAYLOAD, is_published=True)
        response = self.client.get(reverse('content:privacy'))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        start = body.index('article-body')
        article_html = body[start:body.index('</article>', start)]
        assert_sanitised(self, article_html)
        self.assertIn('href="https://evil.example/page"', article_html)
        self.assertIn('rel="nofollow noopener noreferrer"', article_html)

    def test_all_company_pages_render(self):
        for name in ('about', 'shipping', 'privacy', 'terms', 'export', 'careers', 'complaints', 'feedback'):
            self.assertEqual(self.client.get(reverse(f'content:{name}')).status_code, 200, name)
        self.assertEqual(self.client.get(reverse('inquiries:contact')).status_code, 200)


@override_settings(FORM_SUBMISSION_LIMIT=100)
class CompanyRequestFormTests(CleanCacheMixin, TestCase):
    base = {'name': 'سارا', 'mobile': '۰۹۱۲۳۴۵۶۷۸۹', 'message': 'متن درخواست', 'consent': 'on'}

    def test_feedback_submission_creates_private_tracking(self):
        response = self.client.post(reverse('content:feedback'), self.base)
        self.assertEqual(response.status_code, 200)
        record = CompanyRequest.objects.get()
        self.assertEqual(record.kind, CompanyRequest.Kind.FEEDBACK)
        self.assertEqual(record.mobile, '09123456789')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertContains(response, str(record.public_id))

    def test_export_requires_quantity_and_incoterms(self):
        response = self.client.post(reverse('content:export'), self.base)
        self.assertEqual(CompanyRequest.objects.count(), 0)
        self.assertIn('quantity_tonnes', response.context['form'].errors)
        data = dict(self.base, destination_country='عراق', product_interest='میلگرد', quantity_tonnes='0', delivery_terms='XYZ')
        response = self.client.post(reverse('content:export'), data)
        self.assertIn('quantity_tonnes', response.context['form'].errors)
        self.assertIn('delivery_terms', response.context['form'].errors)
        data.update(quantity_tonnes='120.5', delivery_terms='FOB')
        self.client.post(reverse('content:export'), data)
        record = CompanyRequest.objects.get()
        self.assertEqual((record.kind, record.delivery_terms, str(record.quantity_tonnes)), ('export', 'FOB', '120.500'))

    def test_careers_minimises_fields_and_validates_experience(self):
        form = self.client.get(reverse('content:careers')).context['form']
        for name in ('company_name', 'destination_country', 'product_interest', 'quantity_tonnes', 'delivery_terms'):
            self.assertNotIn(name, form.fields)
        response = self.client.post(reverse('content:careers'), dict(self.base, subject='کارشناس فروش', experience_years='500'))
        self.assertIn('experience_years', response.context['form'].errors)
        # Extra fields sent by a client are ignored for careers.
        self.client.post(reverse('content:careers'), dict(
            self.base, subject='کارشناس فروش', experience_years='4', company_name='X', destination_country='Y',
        ))
        record = CompanyRequest.objects.get()
        self.assertEqual((record.kind, record.company_name, record.destination_country), ('career', '', ''))

    def test_consent_and_mobile_validation(self):
        response = self.client.post(reverse('content:complaints'), dict(self.base, consent='', mobile='12345'))
        errors = response.context['form'].errors
        self.assertIn('consent', errors)
        self.assertIn('mobile', errors)
        self.assertEqual(CompanyRequest.objects.count(), 0)

    def test_honeypot_blocks_submission(self):
        self.client.post(reverse('content:complaints'), dict(self.base, website='http://spam.example'))
        self.assertEqual(CompanyRequest.objects.count(), 0)

    def test_get_with_query_string_never_creates_request(self):
        self.client.get(reverse('content:complaints'), self.base)
        self.assertEqual(CompanyRequest.objects.count(), 0)
        self.assertEqual(self.client.put(reverse('content:complaints')).status_code, 405)

    @override_settings(FORM_SUBMISSION_LIMIT=2)
    def test_per_ip_throttle(self):
        for _ in range(3):
            response = self.client.post(reverse('content:feedback'), self.base, REMOTE_ADDR='5.5.5.5')
        self.assertEqual(CompanyRequest.objects.count(), 2)
        self.assertContains(response, 'تعداد ارسال‌های شما')
        self.client.post(reverse('content:feedback'), self.base, REMOTE_ADDR='6.6.6.6')
        self.assertEqual(CompanyRequest.objects.count(), 3)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('content:feedback'), self.base).status_code, 403)
        self.assertEqual(CompanyRequest.objects.count(), 0)

    def test_profile_linked_only_when_mobile_matches(self):
        user = User.objects.create_user('buyer', password='x')
        CustomerProfile.objects.create(user=user, mobile='09120000001')
        self.client.force_login(user)
        self.client.post(reverse('content:feedback'), self.base)
        self.assertIsNone(CompanyRequest.objects.get().profile)


class CompanyRequestTrackingTests(CleanCacheMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.record = CompanyRequest.objects.create(
            kind='career', name='نام محرمانه', mobile='09129998877', email='secret@example.com',
            subject='موقعیت', message='پیام خصوصی کاربر', admin_note='یادداشت داخلی',
        )

    def test_tracking_page_hides_private_data_and_sets_headers(self):
        response = self.client.get(reverse('content:company_request_status', args=[self.record.public_id]))
        self.assertEqual(response.status_code, 200)
        for secret in ('09129998877', 'secret@example.com', 'پیام خصوصی کاربر', 'یادداشت داخلی', 'نام محرمانه'):
            self.assertNotContains(response, secret)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertContains(response, 'noindex')

    def test_ids_are_random_uuids_and_not_enumerable(self):
        other = CompanyRequest.objects.create(kind='feedback', name='ب', mobile='09120000002', message='م')
        self.assertEqual(self.record.public_id.version, 4)
        self.assertNotEqual(self.record.public_id, other.public_id)
        self.assertEqual(self.client.get(f'/company/requests/{uuid.uuid4()}/').status_code, 404)
        self.assertEqual(self.client.get(f'/company/requests/{self.record.pk}/').status_code, 404)


class ArticleVisibilityTests(CleanCacheMixin, TestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.tag = ArticleTag.objects.create(name='بازار', slug='market')
        self.future_tag = ArticleTag.objects.create(name='آینده', slug='future-tag')
        self.published = Article.objects.create(
            title='مقالهٔ منتشرشده', slug='pub', excerpt='خلاصه', body=XSS_PAYLOAD,
            status=Article.Status.PUBLISHED, published_at=now - timedelta(hours=1),
        )
        self.published.tags.add(self.tag)
        self.draft = Article.objects.create(title='مقالهٔ پیش‌نویس', slug='draft', excerpt='خ', body='متن')
        self.future = Article.objects.create(
            title='مقالهٔ آینده', slug='future', excerpt='خ', body='متن',
            status=Article.Status.PUBLISHED, published_at=now + timedelta(days=2),
        )
        self.future.tags.add(self.future_tag)
        self.archived = Article.objects.create(
            title='مقالهٔ بایگانی', slug='archived', excerpt='خ', body='متن',
            status=Article.Status.ARCHIVED, published_at=now - timedelta(days=5),
        )

    def test_list_shows_only_live_articles_and_tags(self):
        response = self.client.get(reverse('content:article_list'))
        self.assertContains(response, 'مقالهٔ منتشرشده')
        for hidden in ('مقالهٔ پیش‌نویس', 'مقالهٔ آینده', 'مقالهٔ بایگانی'):
            self.assertNotContains(response, hidden)
        self.assertEqual(list(response.context['tags']), [self.tag])
        response = self.client.get(reverse('content:article_list'), {'tag': 'future-tag'})
        self.assertNotContains(response, 'مقالهٔ آینده')
        response = self.client.get(reverse('content:article_list'), {'tag': 'market', 'page': '999'})
        self.assertEqual(response.status_code, 200)

    def test_hidden_articles_404_for_public_and_non_editors(self):
        staff = User.objects.create_user('staff', password='x', is_staff=True)
        for client_user in (None, staff):
            if client_user:
                self.client.force_login(client_user)
            for slug in ('draft', 'future', 'archived'):
                self.assertEqual(self.client.get(f'/mag/{slug}/').status_code, 404)
                self.assertEqual(self.client.get(f'/mag/{slug}/?preview=1').status_code, 404)

    def test_editor_preview_is_private(self):
        editor = User.objects.create_user('editor', password='x', is_staff=True)
        editor.user_permissions.add(Permission.objects.get(codename='change_article'))
        self.client.force_login(editor)
        self.assertEqual(self.client.get('/mag/future/').status_code, 404)
        response = self.client.get('/mag/future/?preview=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    def test_article_body_is_sanitised(self):
        response = self.client.get('/mag/pub/')
        body = response.content.decode()
        start = body.index('article-body')
        assert_sanitised(self, body[start:body.index('</article>', start)])
        self.assertIn('rel="nofollow noopener noreferrer"', body)

    def test_json_ld_cannot_break_out_of_script(self):
        Article.objects.filter(pk=self.published.pk).update(title='</script><script>alert(1)</script>')
        response = self.client.get('/mag/pub/')
        self.assertNotContains(response, '</script><script>alert(1)')


@override_settings(FORM_SUBMISSION_LIMIT=100)
class ArticleCommentTests(CleanCacheMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.article = Article.objects.create(
            title='مقاله', slug='a1', excerpt='خ', body='متن', status=Article.Status.PUBLISHED,
            published_at=timezone.now() - timedelta(hours=1),
        )
        self.draft = Article.objects.create(title='پیش‌نویس', slug='d1', excerpt='خ', body='متن')
        self.user = User.objects.create_user('reader', password='x')
        self.profile = CustomerProfile.objects.create(user=self.user, mobile='09121112233', full_name='خواننده')
        self.url = reverse('content:article_comment_submit', args=['a1'])

    def test_login_and_post_required(self):
        response = self.client.post(self.url, {'comment': 'سلام', 'consent': 'on'})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response['Location'])
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url, {'comment': 'سلام', 'consent': 'on'}).status_code, 405)
        self.assertEqual(ArticleComment.objects.count(), 0)

    def test_comment_is_pending_until_approved_and_escaped(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {'comment': '<script>alert(9)</script><img src=x onerror=alert(1)>', 'consent': 'on'})
        comment = ArticleComment.objects.get()
        self.assertEqual(comment.status, ArticleComment.Status.PENDING)
        self.assertEqual(comment.display_name, 'خواننده')
        self.assertNotContains(self.client.get('/mag/a1/'), 'alert(9)')
        comment.status = ArticleComment.Status.APPROVED
        comment.published_at = timezone.now()
        comment.save()
        response = self.client.get('/mag/a1/')
        self.assertContains(response, '&lt;script&gt;alert(9)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(9)')
        self.assertNotContains(response, '<img src=x onerror')

    def test_rejected_comment_hidden(self):
        ArticleComment.objects.create(article=self.article, profile=self.profile, comment='ردشده‌ی خاص', status='rejected')
        self.assertNotContains(self.client.get('/mag/a1/'), 'ردشده‌ی خاص')

    def test_cannot_comment_on_draft_or_without_profile(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('content:article_comment_submit', args=['d1']), {'comment': 'x', 'consent': 'on'})
        self.assertEqual(response.status_code, 404)
        stranger = User.objects.create_user('stranger', password='x')
        self.client.force_login(stranger)
        self.client.post(self.url, {'comment': 'x', 'consent': 'on'})
        self.assertEqual(ArticleComment.objects.count(), 0)

    def test_honeypot_and_consent(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {'comment': 'x', 'consent': 'on', 'website': 'spam'})
        self.client.post(self.url, {'comment': 'x'})
        self.assertEqual(ArticleComment.objects.count(), 0)

    @override_settings(FORM_SUBMISSION_LIMIT=2)
    def test_throttled(self):
        self.client.force_login(self.user)
        for _ in range(4):
            self.client.post(self.url, {'comment': 'x', 'consent': 'on'})
        self.assertEqual(ArticleComment.objects.count(), 2)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, {'comment': 'x', 'consent': 'on'}).status_code, 403)


@override_settings(FORM_SUBMISSION_LIMIT=100)
class ProductFeedbackTests(CleanCacheMixin, TestCase):
    def setUp(self):
        super().setUp()
        category = Category.objects.create(name='میلگرد', slug='rebar-cat')
        self.product = Product.objects.create(category=category, name='میلگرد آجدار', slug='rebar-p')
        self.inactive = Product.objects.create(category=category, name='غیرفعال', slug='off-p', is_active=False)
        self.user = User.objects.create_user('buyer', password='x')
        self.profile = CustomerProfile.objects.create(user=self.user, mobile='09124445566', full_name='خریدار')
        self.client.force_login(self.user)

    def _question(self, **extra):
        data = {'question': 'آیا موجود است؟', 'consent': 'on', **extra}
        return self.client.post(reverse('content:product_question_submit', args=['rebar-p']), data)

    def _review(self, **extra):
        data = {'rating': '5', 'review': 'عالی بود', 'consent': 'on', **extra}
        return self.client.post(reverse('content:product_review_submit', args=['rebar-p']), data)

    def test_question_moderation_and_escaping(self):
        self._question(question='<script>alert("q")</script>')
        question = ProductQuestion.objects.get()
        self.assertEqual(question.status, ProductQuestion.Status.PENDING)
        page = self.client.get(self.product.get_absolute_url())
        self.assertNotContains(page, 'alert(&quot;q&quot;)')
        question.status = ProductQuestion.Status.ANSWERED
        question.answer = '<a href="javascript:alert(2)">x</a>'
        question.published_at = timezone.now()
        question.save()
        page = self.client.get(self.product.get_absolute_url())
        self.assertContains(page, '&lt;script&gt;')
        self.assertNotContains(page, '<script>alert("q")')
        self.assertNotContains(page, 'href="javascript:')

    def test_review_moderation_unique_and_escaping(self):
        self._review(title='<b onmouseover=alert(1)>t</b>', review='<script>alert("r")</script>')
        self._review()
        review = ProductReview.objects.get()
        self.assertEqual(review.status, ProductReview.Status.PENDING)
        self.assertNotContains(self.client.get(self.product.get_absolute_url()), 'alert(&quot;r&quot;)')
        review.status = ProductReview.Status.APPROVED
        review.published_at = timezone.now()
        review.save()
        page = self.client.get(self.product.get_absolute_url())
        self.assertContains(page, 'alert(&quot;r&quot;)')
        self.assertNotContains(page, '<script>alert("r")')
        self.assertNotContains(page, '<b onmouseover')

    def test_invalid_rating_and_honeypot_rejected(self):
        self._review(rating='9')
        self._review(rating='0')
        self._review(website='x')
        self._question(website='x')
        self._question(consent='')
        self.assertEqual(ProductReview.objects.count(), 0)
        self.assertEqual(ProductQuestion.objects.count(), 0)

    def test_inactive_product_and_get_rejected(self):
        response = self.client.post(reverse('content:product_review_submit', args=['off-p']), {'rating': '5', 'review': 'x', 'consent': 'on'})
        self.assertEqual(response.status_code, 404)
        response = self.client.get(reverse('content:product_question_submit', args=['rebar-p']), {'question': 'x', 'consent': 'on'})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(ProductQuestion.objects.count(), 0)

    @override_settings(FORM_SUBMISSION_LIMIT=2)
    def test_question_and_review_throttled(self):
        for index in range(4):
            self._question(question=f'پرسش {index}')
        self.assertEqual(ProductQuestion.objects.count(), 2)
        # The review endpoint shares the per-IP brake under its own scope.
        self._review(rating='9')
        self._review(rating='9')
        self._review()
        self.assertEqual(ProductReview.objects.count(), 0)


class PublicListsTests(CleanCacheMixin, TestCase):
    def test_media_hides_unpublished_and_future_and_marks_links(self):
        now = timezone.now()
        MediaItem.objects.create(title='ویدیوی منتشر', slug='v1', kind='video', media_url='https://video.example/1',
                                 is_published=True, published_at=now - timedelta(hours=1))
        MediaItem.objects.create(title='ویدیوی پیش‌نویس', slug='v2', kind='video', media_url='https://video.example/2')
        MediaItem.objects.create(title='ویدیوی آینده', slug='v3', kind='video', media_url='https://video.example/3',
                                 is_published=True, published_at=now + timedelta(days=1))
        response = self.client.get(reverse('content:videos'))
        self.assertContains(response, 'ویدیوی منتشر')
        self.assertNotContains(response, 'ویدیوی پیش‌نویس')
        self.assertNotContains(response, 'ویدیوی آینده')
        self.assertContains(response, 'rel="nofollow noopener noreferrer"')
        self.assertEqual(self.client.get(reverse('content:podcasts')).status_code, 200)

    def test_faq_hides_inactive_and_sanitises(self):
        FAQ.objects.create(question='پرسش فعال', answer=XSS_PAYLOAD)
        FAQ.objects.create(question='پرسش غیرفعال', answer='x', is_active=False)
        response = self.client.get(reverse('content:faq'))
        self.assertContains(response, 'پرسش فعال')
        self.assertNotContains(response, 'پرسش غیرفعال')
        body = response.content.decode()
        start = body.index('faq-list')
        assert_sanitised(self, body[start:body.index('</details>', start)])

    def test_market_news_filters_tolerate_bad_input(self):
        for params in ({'trend': 'bogus'}, {'category': '1 OR 1=1'}, {'category': '99999'}, {'page': 'x'}):
            self.assertEqual(self.client.get(reverse('content:market_news_list'), params).status_code, 200)
        self.assertEqual(self.client.get('/market/news/99999/').status_code, 404)


class PurgePersonalDataTests(TestCase):
    def setUp(self):
        old = timezone.now() - timedelta(days=800)
        mid = timezone.now() - timedelta(days=200)
        self.old_career = CompanyRequest.objects.create(kind='career', name='ا', mobile='09120000001', message='م', created_at=mid)
        self.new_career = CompanyRequest.objects.create(kind='career', name='ب', mobile='09120000002', message='م')
        self.mid_feedback = CompanyRequest.objects.create(kind='feedback', name='پ', mobile='09120000003', message='م', created_at=mid)
        self.old_export = CompanyRequest.objects.create(kind='export', name='ت', mobile='09120000004', message='م', created_at=old)
        self.old_inquiry = Inquiry.objects.create(kind='contact', customer_name='ث', mobile='09120000005')
        Inquiry.objects.filter(pk=self.old_inquiry.pk).update(created_at=old)
        self.new_inquiry = Inquiry.objects.create(kind='contact', customer_name='ج', mobile='09120000006')
        listing_common = {'kind': 'offer', 'product_label': 'ک', 'quantity': 1, 'quantity_unit': 'ton', 'city': 'ش',
                          'contact_name': 'ن', 'mobile': '09120000007'}
        self.old_listing = MarketplaceListing.objects.create(expires_at=old + timedelta(days=30), **listing_common)
        MarketplaceListing.objects.filter(pk=self.old_listing.pk).update(created_at=old)
        self.live_listing = MarketplaceListing.objects.create(**listing_common)

    def test_dry_run_deletes_nothing(self):
        out = StringIO()
        call_command('purge_personal_data', '--dry-run', stdout=out)
        self.assertIn('1', out.getvalue())
        self.assertEqual(CompanyRequest.objects.count(), 4)
        self.assertEqual(Inquiry.objects.count(), 2)
        self.assertEqual(MarketplaceListing.objects.count(), 2)

    def test_retention_periods(self):
        call_command('purge_personal_data', stdout=StringIO())
        self.assertEqual(
            set(CompanyRequest.objects.values_list('pk', flat=True)), {self.new_career.pk, self.mid_feedback.pk},
        )
        self.assertEqual(list(Inquiry.objects.values_list('pk', flat=True)), [self.new_inquiry.pk])
        self.assertEqual(list(MarketplaceListing.objects.values_list('pk', flat=True)), [self.live_listing.pk])

    @override_settings(CAREER_RETENTION_DAYS=1000)
    def test_retention_is_configurable(self):
        call_command('purge_personal_data', stdout=StringIO())
        self.assertTrue(CompanyRequest.objects.filter(pk=self.old_career.pk).exists())


class CheckLinksCommandTests(TestCase):
    def test_reports_broken_internal_and_lists_outbound(self):
        Article.objects.create(
            title='ل', slug='links', excerpt='خ', body='[ok](/mag/) [bad](/no-such-page-xyz/) [out](https://other.example/a)',
            status=Article.Status.PUBLISHED, published_at=timezone.now(),
        )
        out = StringIO()
        with self.assertRaises(SystemExit):
            call_command('check_links', stdout=out)
        output = out.getvalue()
        self.assertIn('/no-such-page-xyz/', output)
        self.assertIn('https://other.example/a', output)
        self.assertNotIn('شکسته (200)', output)
