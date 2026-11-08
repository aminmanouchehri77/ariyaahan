from django.urls import path

from . import project_views, views

app_name = 'orders'

urlpatterns = [
    path('cart/', views.cart_detail, name='cart'),
    path('cart/add/<int:variant_id>/', views.cart_add, name='cart_add'),
    path('cart/update/<int:variant_id>/', views.cart_update, name='cart_update'),
    path('cart/remove/<int:variant_id>/', views.cart_remove, name='cart_remove'),
    path('checkout/', views.checkout, name='checkout'),
    path('checkout/submit/', views.submit_preinvoice, name='submit_preinvoice'),
    path('preinvoice/<uuid:public_id>/accept/send-code/', views.request_preinvoice_acceptance_code, name='preinvoice_acceptance_code'),
    path('preinvoice/<uuid:public_id>/accept/', views.accept_preinvoice_quote, name='preinvoice_accept'),
    path('preinvoice/<uuid:public_id>/', views.preinvoice_detail, name='preinvoice_detail'),
    path('account/projects/', project_views.project_list, name='project_list'),
    path('account/projects/add/<int:variant_id>/', project_views.project_add_item, name='project_add_item'),
    path('account/projects/<uuid:public_id>/', project_views.project_detail, name='project_detail'),
    path('account/projects/<uuid:public_id>/update/', project_views.project_update, name='project_update'),
    path('account/projects/<uuid:public_id>/items/<int:item_id>/', project_views.project_item_update, name='project_item_update'),
    path('projects/shared/<uuid:public_id>/', project_views.project_shared, name='project_shared'),
    path('account/orders/<uuid:public_id>/', views.order_detail, name='order_detail'),
    path('account/orders/<uuid:public_id>/pay/', views.order_pay, name='order_pay'),
    path('payment/sep/callback/', views.sep_callback, name='sep_callback'),
    path('payment/result/<uuid:key>/', views.payment_result, name='payment_result'),
]
