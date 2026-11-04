from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from catalog.models import Category, Product


class StaticPageSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return (
            'core:home',
            'catalog:category_list',
            'marketplace:sell',
            'marketplace:buy',
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
