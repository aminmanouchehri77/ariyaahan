from types import SimpleNamespace
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from catalog.models import Category, Product
from content.models import Article, CompanyPage, MarketNews


class CanonicalSitemap(Sitemap):
    def get_urls(self, page=1, site=None, protocol=None):
        if settings.PUBLIC_SITE_URL:
            canonical = urlsplit(settings.PUBLIC_SITE_URL)
            site = SimpleNamespace(domain=canonical.netloc)
            protocol = canonical.scheme
        return super().get_urls(page=page, site=site, protocol=protocol)


class StaticPageSitemap(CanonicalSitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return (
            'core:home',
            'catalog:category_list',
            'marketplace:sell',
            'marketplace:buy',
            'inquiries:contact',
            'core:weight_calculator',
            'core:shipping_calculator',
            'content:article_list',
            'content:market_news_list',
            'content:faq',
            'content:videos',
            'content:podcasts',
        )

    def location(self, item):
        return reverse(item)


class CategorySitemap(CanonicalSitemap):
    changefreq = 'daily'
    priority = 0.7

    def items(self):
        return Category.objects.filter(
            is_active=True,
            products__is_active=True,
        ).distinct()

    def lastmod(self, item):
        return item.updated_at


class ProductSitemap(CanonicalSitemap):
    changefreq = 'daily'
    priority = 0.8

    def items(self):
        return Product.objects.filter(is_active=True, category__is_active=True)

    def lastmod(self, item):
        return item.updated_at


class CompanyPageSitemap(CanonicalSitemap):
    changefreq = 'monthly'
    priority = 0.5

    def items(self):
        return CompanyPage.objects.filter(
            is_published=True,
        ).exclude(kind__in=(CompanyPage.Kind.EXPORT, CompanyPage.Kind.CAREERS))

    def lastmod(self, item):
        return item.updated_at


class ArticleSitemap(CanonicalSitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        from django.utils import timezone

        return Article.objects.filter(
            status=Article.Status.PUBLISHED,
            published_at__lte=timezone.now(),
        )

    def lastmod(self, item):
        return item.updated_at


class MarketNewsSitemap(CanonicalSitemap):
    changefreq = 'hourly'
    priority = 0.6

    def items(self):
        return MarketNews.objects.all()

    def lastmod(self, item):
        return item.published_at
