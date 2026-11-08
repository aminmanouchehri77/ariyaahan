"""Security tests for the cross-cutting platform layer (settings, headers,
redirects, robots/sitemap, service worker, error pages, throttling, sanitiser).
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from core.models import RedirectRule, is_safe_internal_path
from core.templatetags.ariaa_tags import rich_text
from core.throttle import client_ip, submission_allowed
from core.views import server_error

BASE_DIR = Path(settings.BASE_DIR)
STRONG_KEY = 'q7Hk2-vN9xLp4RzT8mWc1YbE6uJd3SfGa0QiZo5KtXr_PwVyBnMhCeUlDj'  # test-only

PROD_ENV = {
    'DEBUG': '0',
    'DJANGO_SECRET_KEY': STRONG_KEY,
    'ALLOWED_HOSTS': 'example.ir,www.example.ir',
    'PUBLIC_SITE_URL': 'https://example.ir',
    'KAVENEGAR_API_KEY': 'test-key',
    'KAVENEGAR_OTP_TEMPLATE': 'otp',
    'KAVENEGAR_ACCEPT_TEMPLATE': 'accept',
    'DB_ENGINE': 'django.db.backends.sqlite3',
    'DB_NAME': ':memory:',
}
SETTINGS_KEYS = {
    'DEBUG', 'DJANGO_SECRET_KEY', 'ALLOWED_HOSTS', 'PUBLIC_SITE_URL', 'CSRF_TRUSTED_ORIGINS', 'SMS_BACKEND',
    'KAVENEGAR_API_KEY', 'KAVENEGAR_OTP_TEMPLATE', 'KAVENEGAR_ACCEPT_TEMPLATE', 'PAYMENT_ENABLED',
    'TRUSTED_PROXY_COUNT', 'DEBUG_ALLOW_PUBLIC_HOSTS', 'SECURE_HSTS_SECONDS', 'SECURE_SSL_REDIRECT',
    'SECURE_HSTS_INCLUDE_SUBDOMAINS', 'SECURE_HSTS_PRELOAD',
    'DJANGO_SETTINGS_MODULE',
}


def load_settings(**overrides):
    """Import config.settings in a fresh interpreter; return (ok, output)."""
    env = {key: value for key, value in os.environ.items() if key not in SETTINGS_KEYS}
    env.update(overrides)
    code = (
        'import json, config.settings as s; '
        'print(json.dumps({k: getattr(s, k, None) for k in ('
        '"SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE", "SESSION_COOKIE_HTTPONLY", "SECURE_SSL_REDIRECT", '
        '"SECURE_HSTS_SECONDS", "CSRF_TRUSTED_ORIGINS", "X_FRAME_OPTIONS", "SECURE_CONTENT_TYPE_NOSNIFF", '
        '"SECURE_REFERRER_POLICY", "SECURE_PROXY_SSL_HEADER", "SESSION_COOKIE_SAMESITE", "TRUSTED_PROXY_COUNT")}, default=list))'
    )
    result = subprocess.run(
        [sys.executable, '-c', code], cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=60,
    )
    return result.returncode == 0, result.stdout + result.stderr


class ProductionSettingsTests(SimpleTestCase):
    def assertRefused(self, message_part, **env):
        ok, output = load_settings(**{**PROD_ENV, **env})
        self.assertFalse(ok, output)
        self.assertIn(message_part, output)

    def test_valid_production_settings_are_hardened(self):
        import json

        ok, output = load_settings(**PROD_ENV)
        self.assertTrue(ok, output)
        values = json.loads(output.strip().splitlines()[-1])
        self.assertTrue(values['SESSION_COOKIE_SECURE'])
        self.assertTrue(values['CSRF_COOKIE_SECURE'])
        self.assertTrue(values['SESSION_COOKIE_HTTPONLY'])
        self.assertTrue(values['SECURE_SSL_REDIRECT'])
        self.assertEqual(values['SESSION_COOKIE_SAMESITE'], 'Lax')
        self.assertEqual(values['X_FRAME_OPTIONS'], 'DENY')
        self.assertTrue(values['SECURE_CONTENT_TYPE_NOSNIFF'])
        self.assertEqual(values['SECURE_REFERRER_POLICY'], 'strict-origin-when-cross-origin')
        self.assertIn('https://example.ir', values['CSRF_TRUSTED_ORIGINS'])
        self.assertIsNone(values['SECURE_PROXY_SSL_HEADER'])
        self.assertEqual(values['TRUSTED_PROXY_COUNT'], 0)

    def test_hsts_and_proxy_options(self):
        import json

        ok, output = load_settings(**PROD_ENV, SECURE_HSTS_SECONDS='31536000', TRUSTED_PROXY_COUNT='1')
        self.assertTrue(ok, output)
        values = json.loads(output.strip().splitlines()[-1])
        self.assertEqual(values['SECURE_HSTS_SECONDS'], 31536000)
        self.assertEqual(values['SECURE_PROXY_SSL_HEADER'], ['HTTP_X_FORWARDED_PROTO', 'https'])

    def test_dev_and_weak_secret_keys_refused(self):
        self.assertRefused('DJANGO_SECRET_KEY', DJANGO_SECRET_KEY='dev-only-change-this-key')
        self.assertRefused('secret key', DJANGO_SECRET_KEY='replace-with-a-long-random-secret')
        self.assertRefused('secret key', DJANGO_SECRET_KEY='a' * 64)
        self.assertRefused('secret key', DJANGO_SECRET_KEY='django-insecure-' + STRONG_KEY)

    def test_wildcard_and_local_only_hosts_refused(self):
        self.assertRefused('ALLOWED_HOSTS', ALLOWED_HOSTS='*')
        self.assertRefused('ALLOWED_HOSTS', ALLOWED_HOSTS='example.ir,*')
        self.assertRefused('ALLOWED_HOSTS', ALLOWED_HOSTS='localhost,127.0.0.1')
        self.assertRefused('ALLOWED_HOSTS', ALLOWED_HOSTS='')

    def test_debug_with_public_hosts_refused(self):
        self.assertRefused('DEBUG=1', DEBUG='1', ALLOWED_HOSTS='example.ir')
        self.assertRefused('DEBUG=1', DEBUG='1', ALLOWED_HOSTS='*')
        ok, output = load_settings(DEBUG='1', ALLOWED_HOSTS='localhost,127.0.0.1,192.168.1.5,aria.test')
        self.assertTrue(ok, output)
        ok, output = load_settings(DEBUG='1', ALLOWED_HOSTS='staging.example.ir', DEBUG_ALLOW_PUBLIC_HOSTS='1')
        self.assertTrue(ok, output)

    def test_production_requires_https_public_url_and_csrf_origins(self):
        self.assertRefused('PUBLIC_SITE_URL', PUBLIC_SITE_URL='http://example.ir')
        self.assertRefused('CSRF_TRUSTED_ORIGINS', CSRF_TRUSTED_ORIGINS='http://example.ir')
        self.assertRefused('CSRF_TRUSTED_ORIGINS', CSRF_TRUSTED_ORIGINS='https://*')
        self.assertRefused('CSRF_TRUSTED_ORIGINS', CSRF_TRUSTED_ORIGINS='example.ir')

    def test_console_sms_backend_refused_in_production(self):
        self.assertRefused('console SMS backend', SMS_BACKEND='accounts.sms.ConsoleSMSBackend')

    def test_check_deploy_has_only_hsts_warning_when_hsts_unset(self):
        env = {key: value for key, value in os.environ.items() if key not in SETTINGS_KEYS}
        env.update(PROD_ENV)
        result = subprocess.run(
            [sys.executable, 'manage.py', 'check', '--deploy', '--fail-level', 'ERROR'],
            cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout + result.stderr
        issues = {line.split(')')[0].strip('?: (') for line in output.splitlines() if line.startswith('?: (')}
        self.assertLessEqual(issues, {'security.W004'}, output)
        env.update(SECURE_HSTS_SECONDS='31536000', SECURE_HSTS_INCLUDE_SUBDOMAINS='1', SECURE_HSTS_PRELOAD='1')
        result = subprocess.run(
            [sys.executable, 'manage.py', 'check', '--deploy'],
            cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=120,
        )
        self.assertIn('no issues', result.stdout + result.stderr)


class SecurityHeaderTests(TestCase):
    def test_public_pages_send_security_headers_and_render(self):
        for path in ('/', '/offline/', '/search/?q=x', '/steel/', '/admin/login/'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['X-Frame-Options'], 'DENY')
                self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
                self.assertEqual(response['Referrer-Policy'], 'strict-origin-when-cross-origin')
                self.assertEqual(response['Cross-Origin-Opener-Policy'], 'same-origin')
                self.assertIn('camera=()', response['Permissions-Policy'])
                self.assertIn('geolocation=()', response['Permissions-Policy'])
                csp = response['Content-Security-Policy']
                self.assertIn("frame-ancestors 'none'", csp)
                self.assertIn("object-src 'none'", csp)
                self.assertIn("base-uri 'self'", csp)

    def test_csp_allows_site_assets_and_sep_form_post(self):
        csp = dict(
            (part.strip().split(' ', 1) + [''])[:2]
            for part in self.client.get('/')['Content-Security-Policy'].split(';')
        )
        self.assertEqual(csp['script-src'], "'self' 'unsafe-inline'")  # inline bootstrap + JSON-LD
        self.assertIn("'self'", csp['font-src'])
        self.assertIn('https:', csp['img-src'])  # e-Namad / Samandehi seals, article covers
        self.assertIn("'self'", csp['worker-src'])
        sep = urlsplit(settings.SEP_PAYMENT_URL)
        self.assertIn(f'{sep.scheme}://{sep.netloc}', csp['form-action'])
        self.assertNotIn('*', csp['script-src'])
        self.assertNotIn('unsafe-eval', csp['script-src'])

    def test_home_inline_json_ld_and_hero_module_still_present(self):
        response = self.client.get('/')
        self.assertContains(response, 'application/ld+json')
        self.assertContains(response, 'core/js/site.js')

    def test_session_cookie_httponly(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, 'Lax')


class RedirectRuleSecurityTests(TestCase):
    def test_safe_internal_path_helper(self):
        for good in ('/steel/', '/steel/rebar/?size=12#top', '/مقاله/'):
            self.assertTrue(is_safe_internal_path(good), good)
        for bad in (
            '', 'steel/', '//evil.example', '/\\evil.example', 'https://evil.example/', 'javascript:alert(1)',
            '/\t/evil.example', '/\n/evil.example', '/ /evil.example', '/\x00x', '\\\\evil.example',
        ):
            self.assertFalse(is_safe_internal_path(bad), repr(bad))

    def test_model_rejects_external_destinations(self):
        for destination in ('https://evil.example/', '//evil.example', '/\t/evil.example', '/\\evil'):
            with self.subTest(destination=destination), self.assertRaises(ValidationError):
                RedirectRule.objects.create(old_path='/old-x/', destination=destination)

    def test_redirect_and_gone(self):
        RedirectRule.objects.create(old_path='/old-page/', destination='/steel/')
        RedirectRule.objects.create(old_path='/dead/', status_code=RedirectRule.StatusCode.GONE)
        response = self.client.get('/old-page/')
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response['Location'], '/steel/')
        self.assertEqual(self.client.get('/dead/').status_code, 410)
        self.assertEqual(self.client.get('/never-existed/').status_code, 404)

    def test_rule_bypassing_validation_never_redirects_off_site(self):
        rule = RedirectRule.objects.create(old_path='/bulk/', destination='/steel/')
        for destination in ('https://evil.example/', '//evil.example', '/\t/evil.example', ''):
            RedirectRule.objects.filter(pk=rule.pk).update(destination=destination)
            response = self.client.get('/bulk/')
            self.assertEqual(response.status_code, 404, destination)
            self.assertFalse(response.has_header('Location'))

    def test_legacy_route_rejects_post(self):
        RedirectRule.objects.create(old_path='/old-post/', destination='/steel/')
        self.assertEqual(self.client.post('/old-post/').status_code, 405)


class RobotsSitemapTests(TestCase):
    PRIVATE = ('/admin/', '/account/', '/cart/', '/checkout/', '/payment/', '/preinvoice/', '/search/')

    def test_robots_disallows_private_paths(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response['Content-Type'], 'text/plain; charset=utf-8')
        body = response.content.decode()
        for path in self.PRIVATE:
            self.assertIn(f'Disallow: {path}\n', body)
        self.assertNotIn('Disallow: /\n', body)
        self.assertIn('Sitemap: ', body)

    def test_sitemap_has_no_private_urls(self):
        body = self.client.get('/sitemap.xml').content.decode()
        self.assertIn('<urlset', body)
        for path in self.PRIVATE + ('/compare/', '/projects/shared/', '/company/requests/'):
            self.assertNotIn(path, body.replace('<loc>', ' '))


class ServiceWorkerTests(SimpleTestCase):
    def setUp(self):
        self.source = (BASE_DIR / 'static' / 'service-worker.js').read_text(encoding='utf-8')

    def test_served_uncached_from_root_scope(self):
        response = self.client.get('/service-worker.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-cache')
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        self.assertTrue(response['Content-Type'].startswith('application/javascript'))

    def test_only_get_same_origin_static_assets_are_cached(self):
        self.assertIn("request.method !== 'GET' || url.origin !== self.location.origin) return;", self.source)
        self.assertIn("url.pathname.startsWith('/static/')", self.source)
        # Navigations (account, cart, checkout, payment, price pages) go to the network.
        self.assertIn("request.mode === 'navigate'", self.source)
        self.assertEqual(self.source.count('cache.put('), 1)
        for private in ('/account/', '/cart/', '/checkout/', '/payment/', '/steel/', '/product/'):
            self.assertNotIn(private, self.source)
        shell = self.source.split('SHELL_ASSETS = [', 1)[1].split('];', 1)[0]
        for asset in [line.strip(" ',") for line in shell.splitlines() if line.strip()]:
            self.assertTrue(asset == '/offline/' or asset.startswith('/static/'), asset)

    def test_push_click_urls_stay_same_origin(self):
        self.assertEqual(self.source.count('target.origin === self.location.origin'), 2)


@override_settings(DEBUG=False)
class ErrorPageTests(TestCase):
    def test_404_is_branded_and_noindex(self):
        response = self.client.get('/no-such-page-xyz/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'noindex', status_code=404)
        self.assertNotContains(response, 'Traceback', status_code=404)
        self.assertNotContains(response, 'urlpatterns', status_code=404)
        response = self.client.get('/"><script>alert(1)</script>/')
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, '<script>alert(1)', status_code=404)

    def test_500_is_static_and_leaks_nothing(self):
        response = server_error(RequestFactory().get('/boom/'))
        self.assertEqual(response.status_code, 500)
        body = response.content.decode()
        self.assertIn('noindex', body)
        for leak in ('Traceback', 'SECRET', 'settings', '/boom/', 'Exception'):
            self.assertNotIn(leak, body)


class ThrottleTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def test_forwarded_for_ignored_by_default(self):
        request = self.factory.post('/', REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='1.2.3.4')
        self.assertEqual(client_ip(request), '10.0.0.1')

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_forwarded_for_uses_rightmost_trusted_entry(self):
        request = self.factory.post('/', REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='6.6.6.6, 203.0.113.9')
        self.assertEqual(client_ip(request), '203.0.113.9')
        request = self.factory.post('/', REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='not-an-ip')
        self.assertEqual(client_ip(request), '10.0.0.1')
        request = self.factory.post('/', REMOTE_ADDR='10.0.0.1')
        self.assertEqual(client_ip(request), '10.0.0.1')

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_two_proxies(self):
        request = self.factory.post('/', REMOTE_ADDR='10.0.0.2', HTTP_X_FORWARDED_FOR='6.6.6.6, 198.51.100.7, 10.0.0.1')
        self.assertEqual(client_ip(request), '198.51.100.7')

    def test_limit_enforced_and_spoofed_header_cannot_reset_it(self):
        for attempt in range(3):
            request = self.factory.post('/', REMOTE_ADDR='192.0.2.1', HTTP_X_FORWARDED_FOR=f'1.1.1.{attempt}')
            self.assertTrue(submission_allowed(request, 't', limit=3, window=60))
        request = self.factory.post('/', REMOTE_ADDR='192.0.2.1', HTTP_X_FORWARDED_FOR='9.9.9.9')
        self.assertFalse(submission_allowed(request, 't', limit=3, window=60))
        self.assertTrue(submission_allowed(self.factory.post('/', REMOTE_ADDR='192.0.2.2'), 't', limit=3, window=60))
        self.assertTrue(submission_allowed(request, 'other-scope', limit=3, window=60))

    def test_cache_key_does_not_contain_raw_ip(self):
        from core.throttle import _client_key

        key = _client_key(self.factory.get('/', REMOTE_ADDR='192.0.2.55'), 'x')
        self.assertNotIn('192.0.2.55', key)


class RichTextSanitiserTests(SimpleTestCase):
    def test_strips_scripts_handlers_and_dangerous_urls(self):
        html = str(rich_text(
            '<script>alert(1)</script><img src=x onerror=alert(1)>[a](javascript:alert(1)) '
            '<a href="data:text/html,x">d</a><iframe src="https://evil"></iframe><p style="x:y">s</p>'
            '<img src="data:image/png;base64,AAAA"><svg onload=alert(1)></svg>'
        ))
        for bad in ('<script', 'onerror', 'javascript:', 'data:', '<iframe', 'style=', '<svg', 'onload'):
            self.assertNotIn(bad, html)

    def test_links_get_rel_and_images_lazy_once(self):
        html = str(rich_text('[x](https://example.com) ![a](https://example.com/a.png) <img src="https://e/b.png" loading="eager">'))
        self.assertIn('rel="nofollow noopener noreferrer"', html)
        self.assertNotIn('loading="eager"', html)
        for tag in html.split('<img')[1:]:
            self.assertEqual(tag.split('>')[0].count('loading='), 1)

    def test_tables_are_wrapped(self):
        html = str(rich_text('| a | b |\n|---|---|\n| 1 | 2 |'))
        self.assertIn('<div class="table-scroll"><table>', html)

    def test_parser_crash_falls_back_to_escaped_text(self):
        from unittest import mock

        with mock.patch('markdown.markdown', side_effect=AssertionError('boom')):
            html = str(rich_text('<b>x</b>\n\ny'))
        self.assertIn('&lt;b&gt;', html)
        self.assertIn('<p>', html)

    def test_empty(self):
        self.assertEqual(rich_text(''), '')
