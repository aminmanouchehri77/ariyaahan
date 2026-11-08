from django.contrib.sitemaps.views import sitemap
from django.urls import path
from django.views.generic import RedirectView

from .sitemaps import ArticleSitemap, CategorySitemap, CompanyPageSitemap, MarketNewsSitemap, ProductSitemap, StaticPageSitemap
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('.well-known/assetlinks.json', views.assetlinks_json, name='assetlinks'),
    path('search/', views.search, name='search'),
    path('search/suggestions/', views.search_suggestions, name='search_suggestions'),
    path('tools/weight/', views.weight_calculator, name='weight_calculator'),
    path('calculators/steel-weight/', RedirectView.as_view(pattern_name='core:weight_calculator', permanent=True, query_string=True), name='legacy_weight_calculator'),
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
            'market_news': MarketNewsSitemap,
        },
    }, name='sitemap'),
    # Paths from the proposal's site map, kept as permanent aliases.
    path('market/offers/', RedirectView.as_view(pattern_name='marketplace:sell', permanent=True, query_string=True)),
    path('market/requests/', RedirectView.as_view(pattern_name='marketplace:buy', permanent=True, query_string=True)),
    path('price-alerts/', RedirectView.as_view(pattern_name='accounts:price_alerts', permanent=True)),
    path('tools/shipping/', RedirectView.as_view(pattern_name='core:shipping_calculator', permanent=True)),
    path('service-worker.js', views.service_worker, name='service_worker'),
]
