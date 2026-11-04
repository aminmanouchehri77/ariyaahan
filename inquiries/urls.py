from django.urls import path

from . import views

app_name = 'inquiries'

urlpatterns = [
    path('inquiry/', views.quote_request, name='quote'),
    path('contact/', views.contact, name='contact'),
    path('requests/<uuid:public_id>/', views.inquiry_status, name='status'),
]
