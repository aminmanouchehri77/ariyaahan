from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'inquiries'

urlpatterns = [
    path('inquiry/', views.quote_request, name='quote'),
    path('company/contact/', views.contact, name='contact'),
    path('contact/', RedirectView.as_view(pattern_name='inquiries:contact', permanent=True, query_string=True), name='legacy_contact'),
    path('requests/<uuid:public_id>/', views.inquiry_status, name='status'),
]
