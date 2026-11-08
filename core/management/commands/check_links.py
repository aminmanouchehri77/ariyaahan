"""Audit links inside editorial content.

* Internal links (/...) are resolved through Django's test client; any 4xx/5xx
  is reported as broken.
* Outbound links are listed per page so editors can review injected or stale
  links (the proposal's «پایش لینک خروجی»). With --check-external each one is
  requested with HEAD (timeout 6s).

Exit code 1 when broken internal links exist, so it can run in cron/CI.
"""

import re
import urllib.request
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import Client

LINK = re.compile(r'(?:href=["\']|\]\()([^"\')\s]+)')


class Command(BaseCommand):
    help = 'بررسی لینک‌های داخلی شکسته و فهرست لینک‌های خروجی در مقاله‌ها، صفحه‌ها و توضیح محصولات.'

    def add_arguments(self, parser):
        parser.add_argument('--check-external', action='store_true')

    def _sources(self):
        from catalog.models import Product
        from content.models import Article, CompanyPage

        for article in Article.objects.all():
            yield f'مقاله «{article.title}»', article.body
        for page in CompanyPage.objects.all():
            yield f'صفحه «{page}»', ' '.join(str(getattr(page, name, '') or '') for name in ('body', 'content', 'text'))
        for product in Product.objects.exclude(description=''):
            yield f'کالا «{product.name}»', product.description

    def handle(self, *args, **options):
        client = Client(HTTP_HOST=(settings.ALLOWED_HOSTS or ['localhost'])[0].lstrip('.'))
        public_host = urlsplit(settings.PUBLIC_SITE_URL).hostname if settings.PUBLIC_SITE_URL else None
        broken, external = [], []
        checked = {}
        for source, text in self._sources():
            for url in set(LINK.findall(text or '')):
                parts = urlsplit(url)
                if parts.scheme in {'mailto', 'tel'}:
                    continue
                internal = url.startswith('/') and not url.startswith('//') or (public_host and parts.hostname == public_host)
                if internal:
                    path = parts.path or '/'
                    if path not in checked:
                        checked[path] = client.get(path, follow=True).status_code
                    if checked[path] >= 400:
                        broken.append((source, url, checked[path]))
                elif parts.scheme in {'http', 'https'}:
                    status = ''
                    if options['check_external']:
                        try:
                            request = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'AriaLinkCheck/1.0'})
                            with urllib.request.urlopen(request, timeout=6) as response:
                                status = response.status
                        except Exception as error:  # noqa: BLE001
                            status = type(error).__name__
                    external.append((source, url, status))
        for source, url, status in broken:
            self.stdout.write(self.style.ERROR(f'شکسته ({status}): {url} ← {source}'))
        for source, url, status in external:
            self.stdout.write(f'خروجی{f" ({status})" if status else ""}: {url} ← {source}')
        self.stdout.write(self.style.SUCCESS(f'{len(checked)} مسیر داخلی بررسی شد؛ {len(broken)} شکسته؛ {len(external)} لینک خروجی.'))
        if broken:
            raise SystemExit(1)
