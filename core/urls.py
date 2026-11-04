from django.contrib.sitemaps.views import sitemap
from django.urls import path

from .sitemaps import ArticleSitemap, CategorySitemap, CompanyPageSitemap, ProductSitemap, StaticPageSitemap
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('search/', views.search, name='search'),
    path('calculators/steel-weight/', views.weight_calculator, name='weight_calculator'),
    path('calculators/shipping/', views.shipping_calculator, name='shipping_calculator'),
    path('offline/', views.offline, name='offline'),
    path('robots.txt', views.robots_txt, name='robots'),
    path('sitemap.xml', sitemap, {
        'sitemaps': {
            'static': StaticPageSitemap,
            'categories': CategorySitemap,
            'products': ProductSitemap,
            'company_pages': CompanyPageSitemap,
            'articles': ArticleSitemap,
        },
    }, name='sitemap'),
    path('service-worker.js', views.service_worker, name='service_worker'),
]
