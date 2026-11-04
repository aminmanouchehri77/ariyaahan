from django.urls import path

from . import views

app_name = 'content'

urlpatterns = [
    path('product/<slug:slug>/questions/', views.product_question_submit, name='product_question_submit'),
    path('about/', views.company_page, {'kind': 'about'}, name='about'),
    path('export/', views.company_request, {'kind': 'export'}, name='export'),
    path('careers/', views.company_request, {'kind': 'career'}, name='careers'),
    path('complaints/', views.company_request, {'kind': 'complaint'}, name='complaints'),
    path('feedback/', views.company_request, {'kind': 'feedback'}, name='feedback'),
    path('shipping/', views.company_page, {'kind': 'shipping'}, name='shipping'),
    path('privacy/', views.company_page, {'kind': 'privacy'}, name='privacy'),
    path('terms/', views.company_page, {'kind': 'terms'}, name='terms'),
    path('pages/<slug:slug>/', views.content_page, name='page'),
    path('articles/', views.article_list, name='article_list'),
    path('articles/<slug:slug>/', views.article_detail, name='article_detail'),
    path('market/news/', views.market_news_list, name='market_news_list'),
    path('market/news/<int:pk>/', views.market_news_detail, name='market_news_detail'),
    path('videos/', views.media_list, {'kind': 'video'}, name='videos'),
    path('podcasts/', views.media_list, {'kind': 'podcast'}, name='podcasts'),
    path('faq/', views.faq_list, name='faq'),
]
