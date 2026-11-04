from django.contrib.sitemaps.views import sitemap
from django.urls import path

from .sitemaps import CategorySitemap, ProductSitemap, StaticPageSitemap
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('search/', views.search, name='search'),
    path('offline/', views.offline, name='offline'),
    path('robots.txt', views.robots_txt, name='robots'),
    path('sitemap.xml', sitemap, {
        'sitemaps': {
            'static': StaticPageSitemap,
            'categories': CategorySitemap,
            'products': ProductSitemap,
        },
    }, name='sitemap'),
    path('service-worker.js', views.service_worker, name='service_worker'),
]
