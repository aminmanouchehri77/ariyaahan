from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from catalog.models import Category, Product
from content.models import Article, CompanyPage


class StaticPageSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return (
            'core:home',
            'catalog:category_list',
            'marketplace:sell',
            'marketplace:buy',
            'core:weight_calculator',
            'core:shipping_calculator',
            'content:article_list',
            'content:faq',
            'content:videos',
            'content:podcasts',
        )

    def location(self, item):
        return reverse(item)


class CategorySitemap(Sitemap):
    changefreq = 'daily'
    priority = 0.7

    def items(self):
        return Category.objects.filter(
            is_active=True,
            products__is_active=True,
        ).distinct()

    def lastmod(self, item):
        return item.updated_at


class ProductSitemap(Sitemap):
    changefreq = 'daily'
    priority = 0.8

    def items(self):
        return Product.objects.filter(is_active=True, category__is_active=True)

    def lastmod(self, item):
        return item.updated_at


class CompanyPageSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.5

    def items(self):
        return CompanyPage.objects.filter(
            is_published=True,
        ).exclude(kind__in=(CompanyPage.Kind.EXPORT, CompanyPage.Kind.CAREERS))

    def lastmod(self, item):
        return item.updated_at


class ArticleSitemap(Sitemap):
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
