from django.urls import path

from . import views

app_name = 'marketplace'

urlpatterns = [
    path('market/listings/<uuid:public_id>/', views.listing_status, name='listing_status'),
    path('market/listings/<int:pk>/report/', views.report_listing, name='report_listing'),
    path('market/sell/', views.sell_hall, name='sell'),
    path('market/buy/', views.buy_hall, name='buy'),
]
