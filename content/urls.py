from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'content'

urlpatterns = [
    path('product/<slug:slug>/questions/', views.product_question_submit, name='product_question_submit'),
    path('product/<slug:slug>/reviews/', views.product_review_submit, name='product_review_submit'),
    path('mag/<slug:slug>/comments/', views.article_comment_submit, name='article_comment_submit'),
    path('articles/<slug:slug>/comments/', views.article_comment_submit, name='legacy_article_comment_submit'),
    path('company/about/', views.company_page, {'kind': 'about'}, name='about'),
    path('company/export/', views.company_request, {'kind': 'export'}, name='export'),
    path('company/careers/', views.company_request, {'kind': 'career'}, name='careers'),
    path('company/requests/<uuid:public_id>/', views.company_request_status, name='company_request_status'),
    path('company/complaints/', views.company_request, {'kind': 'complaint'}, name='complaints'),
    path('company/feedback/', views.company_request, {'kind': 'feedback'}, name='feedback'),
    path('company/shipping/', views.company_page, {'kind': 'shipping'}, name='shipping'),
    path('company/privacy/', views.company_page, {'kind': 'privacy'}, name='privacy'),
    path('company/terms/', views.company_page, {'kind': 'terms'}, name='terms'),
    path('about/', RedirectView.as_view(pattern_name='content:about', permanent=True, query_string=True), name='legacy_about'),
    path('export/', RedirectView.as_view(pattern_name='content:export', permanent=True, query_string=True), name='legacy_export'),
    path('careers/', RedirectView.as_view(pattern_name='content:careers', permanent=True, query_string=True), name='legacy_careers'),
    path('complaints/', RedirectView.as_view(pattern_name='content:complaints', permanent=True, query_string=True), name='legacy_complaints'),
    path('feedback/', RedirectView.as_view(pattern_name='content:feedback', permanent=True, query_string=True), name='legacy_feedback'),
    path('shipping/', RedirectView.as_view(pattern_name='content:shipping', permanent=True, query_string=True), name='legacy_shipping'),
    path('privacy/', RedirectView.as_view(pattern_name='content:privacy', permanent=True, query_string=True), name='legacy_privacy'),
    path('terms/', RedirectView.as_view(pattern_name='content:terms', permanent=True, query_string=True), name='legacy_terms'),
    path('pages/<slug:slug>/', views.content_page, name='page'),
    path('mag/', views.article_list, name='article_list'),
    path('mag/<slug:slug>/', views.article_detail, name='article_detail'),
    path('articles/', RedirectView.as_view(pattern_name='content:article_list', permanent=True, query_string=True), name='legacy_article_list'),
    path('articles/<slug:slug>/', RedirectView.as_view(pattern_name='content:article_detail', permanent=True, query_string=True), name='legacy_article_detail'),
    path('market/news/', views.market_news_list, name='market_news_list'),
    path('market/news/<int:pk>/', views.market_news_detail, name='market_news_detail'),
    path('videos/', views.media_list, {'kind': 'video'}, name='videos'),
    path('podcasts/', views.media_list, {'kind': 'podcast'}, name='podcasts'),
    path('faq/', views.faq_list, name='faq'),
]
