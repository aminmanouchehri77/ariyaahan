from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('verify/', views.verify_view, name='verify'),
    path('resend/', views.resend_view, name='resend'),
    path('logout/', views.logout_view, name='logout'),
    path('orders/', views.orders_view, name='orders'),
    path('requests/', views.requests_view, name='requests'),
    path('addresses/', views.addresses_view, name='addresses'),
    path('addresses/add/', views.address_add, name='address_add'),
    path('addresses/<int:address_id>/edit/', views.address_edit, name='address_edit'),
    path('addresses/<int:address_id>/delete/', views.address_delete, name='address_delete'),
    path('price-alerts/', views.price_alerts_view, name='price_alerts'),
    path('price-alerts/<int:alert_id>/edit/', views.price_alert_edit, name='price_alert_edit'),
    path('price-alerts/<int:alert_id>/toggle/', views.price_alert_toggle, name='price_alert_toggle'),
    path('price-alerts/<int:alert_id>/delete/', views.price_alert_delete, name='price_alert_delete'),
    path('notifications/', views.notifications_view, name='notifications'),
    path('notifications/read/', views.notifications_read, name='notifications_read'),
    path('notifications/<int:notification_id>/read/', views.notification_read, name='notification_read'),
    path('push/subscribe/', views.push_subscribe, name='push_subscribe'),
    path('push/unsubscribe/', views.push_unsubscribe, name='push_unsubscribe'),
    path('', views.profile_view, name='profile'),
]
