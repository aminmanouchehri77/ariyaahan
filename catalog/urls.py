from django.urls import path

from . import views

app_name = 'catalog'

urlpatterns = [
    path('compare/', views.compare, name='compare'),
    path('compare/add/<int:variant_id>/', views.compare_add, name='compare_add'),
    path('compare/remove/<int:variant_id>/', views.compare_remove, name='compare_remove'),
    path('steel/', views.category_list, name='category_list'),
    path('steel/<slug:slug>/', views.category_detail, name='category_detail'),
    path('steel/<slug:slug>/price-list.csv', views.category_price_list, name='category_price_list'),
    path('product/<slug:slug>/price-history/', views.price_history, name='price_history'),
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),
]
