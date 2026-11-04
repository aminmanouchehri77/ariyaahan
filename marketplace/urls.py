from django.urls import path

from . import views

app_name = 'marketplace'

urlpatterns = [
    path('market/sell/', views.sell_hall, name='sell'),
    path('market/buy/', views.buy_hall, name='buy'),
]
