import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.seo import breadcrumb_schema
from .forms import ArticleCommentForm, CompanyRequestForm, ProductQuestionForm, ProductReviewForm
from .models import Article, ArticleComment, ArticleTag, CompanyPage, CompanyRequest, FAQ, MarketNews, MediaItem, ProductQuestion, ProductReview


PAGE_SIZE = 12
PAGE_DEFAULTS = {
    CompanyPage.Kind.ABOUT: ('دربارهٔ ما', 'اطلاعات معرفی و راه‌های شناخت شرکت آهن‌آلات آریا.'),
    CompanyPage.Kind.EXPORT: ('صادرات', 'برای بررسی امکان تأمین و ارسال برون‌مرزی درخواست خود را ثبت کنید.'),
    CompanyPage.Kind.CAREERS: ('فرصت‌های شغلی', 'درخواست همکاری خود را برای بررسی تیم آریا ارسال کنید.'),
    CompanyPage.Kind.SHIPPING: ('راهنمای تحویل', 'اطلاعات مربوط به مقصد، هماهنگی و برآورد حمل.'),
    CompanyPage.Kind.PRIVACY: ('حریم خصوصی', 'نحوهٔ استفاده از اطلاعات ثبت‌شده در سایت.'),
    CompanyPage.Kind.TERMS: ('شرایط استفاده', 'قواعد استفاده از محتوای سایت و ارسال درخواست.'),
}


def _public_page_context(page, kind, request):
    default_title, default_summary = PAGE_DEFAULTS[kind]
    body = page.body if page else ''
    return {
        'page': page,
        'title_text': page.title if page else default_title,
        'summary_text': (page.summary or default_summary) if page else default_summary,
        'body_text': body or 'متن رسمی این صفحه هنوز از پنل مدیریت منتشر نشده است.',
        'robots_noindex': not bool(page and page.is_published),
        'canonical': request.build_absolute_uri(request.path),
        'breadcrumb_schema': breadcrumb_schema(request, [
            ('خانه', '/'), (page.title if page else default_title, request.path),
        ]),
    }


def _json_ld(data):
    return json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def company_page(request, kind):
    if kind not in PAGE_DEFAULTS:
        raise Http404
    page = CompanyPage.objects.filter(kind=kind, is_published=True).first()
    context = _public_page_context(page, kind, request)
    return render(request, 'content/page.html', context)


def content_page(request, slug):
    page = get_object_or_404(CompanyPage, slug=slug, is_published=True)
    kind = page.kind
    context = _public_page_context(page, kind, request)
    return render(request, 'content/page.html', context)


@require_http_methods(['GET', 'POST'])
def company_request(request, kind):
    kinds = {
        'complaint': (CompanyRequest.Kind.COMPLAINT, 'ثبت شکایت', 'شرح موضوع را برای پیگیری محرمانهٔ تیم آریا ارسال کنید.'),
        'feedback': (CompanyRequest.Kind.FEEDBACK, 'پیشنهاد و انتقاد', 'نظر شما برای بهبود فرایندهای شرکت ثبت می‌شود.'),
        'career': (CompanyRequest.Kind.CAREER, 'درخواست همکاری', 'اطلاعات و سوابق مرتبط با موقعیت موردنظر را ارسال کنید.'),
        'export': (CompanyRequest.Kind.EXPORT, 'استعلام صادرات', 'کشور مقصد، نوع محصول و حجم موردنیاز را برای بررسی ارسال کنید.'),
    }
    try:
        model_kind, title, intro = kinds[kind]
    except KeyError as error:
        raise Http404 from error
    form = CompanyRequestForm(request.POST or None, kind=model_kind)
    if request.method == 'POST' and form.is_valid():
        company_request_obj = form.save(commit=False)
        company_request_obj.source_path = request.path[:255]
        company_request_obj.save()
        return render(request, 'content/request_sent.html', {
            'request_record': company_request_obj,
            'title_text': title,
        })
    return render(request, 'content/request_form.html', {
        'form': form,
        'title_text': title,
        'intro_text': intro,
        'kind': kind,
    })


def article_list(request):
    articles = Article.objects.filter(
        status=Article.Status.PUBLISHED,
        published_at__lte=timezone.now(),
    ).prefetch_related('tags')
    selected_tag = request.GET.get('tag', '').strip()[:80]
    if selected_tag:
        articles = articles.filter(tags__slug=selected_tag)
    page_obj = Paginator(articles, PAGE_SIZE).get_page(request.GET.get('page'))
    tag = ArticleTag.objects.filter(slug=selected_tag).first() if selected_tag else None
    return render(request, 'content/article_list.html', {
        'page_obj': page_obj,
        'articles': page_obj.object_list,
        'selected_tag': tag,
        'tags': ArticleTag.objects.filter(articles__status=Article.Status.PUBLISHED).distinct(),
        'breadcrumb_schema': breadcrumb_schema(request, [
            ('خانه', '/'), ('مجله', request.path),
        ]),
    })


def article_detail(request, slug):
    article = get_object_or_404(
        Article.objects.prefetch_related('tags', 'related_products'),
        slug=slug,
        status=Article.Status.PUBLISHED,
        published_at__lte=timezone.now(),
    )
    absolute_url = request.build_absolute_uri(article.get_absolute_url())
    schema = {
        '@context': 'https://schema.org',
        '@type': 'Article',
        'headline': article.title,
        'description': article.meta_description or article.excerpt,
        'datePublished': article.published_at.isoformat(),
        'dateModified': article.updated_at.isoformat(),
        'mainEntityOfPage': absolute_url,
        'author': {'@type': 'Person', 'name': article.author_name or 'تحریریهٔ آهن‌آلات آریا'},
        'publisher': {'@type': 'Organization', 'name': 'آهن‌آلات آریا'},
    }
    if article.cover_image_url:
        schema['image'] = [article.cover_image_url]
    from accounts.models import CustomerProfile

    profile = CustomerProfile.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    comments = ArticleComment.objects.filter(
        article=article,
        status=ArticleComment.Status.APPROVED,
    ).order_by('published_at', 'pk')[:50]
    return render(request, 'content/article_detail.html', {
        'article': article,
        'related_products': article.related_products.filter(is_active=True, category__is_active=True),
        'article_comments': comments,
        'article_comment_form': ArticleCommentForm() if profile else None,
        'comment_account_missing': request.user.is_authenticated and profile is None,
        'article_schema': _json_ld(schema),
        'breadcrumb_schema': breadcrumb_schema(request, [
            ('خانه', '/'), ('مجله', reverse('content:article_list')),
            (article.title, article.get_absolute_url()),
        ]),
    })


def media_list(request, kind):
    if kind not in MediaItem.Kind.values:
        raise Http404
    items = MediaItem.objects.filter(
        kind=kind,
        is_published=True,
        published_at__lte=timezone.now(),
    )
    page_obj = Paginator(items, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'content/media_list.html', {
        'kind': kind,
        'is_video': kind == MediaItem.Kind.VIDEO,
        'page_obj': page_obj,
        'items': page_obj.object_list,
        'breadcrumb_schema': breadcrumb_schema(request, [
            ('خانه', '/'), ('ویدیوها' if kind == MediaItem.Kind.VIDEO else 'پادکست‌ها', request.path),
        ]),
    })


def faq_list(request):
    faqs = FAQ.objects.filter(is_active=True)
    schema = {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        'mainEntity': [{
            '@type': 'Question',
            'name': faq.question,
            'acceptedAnswer': {'@type': 'Answer', 'text': faq.answer},
        } for faq in faqs],
    }
    return render(request, 'content/faq.html', {
        'faqs': faqs,
        'faq_schema': _json_ld(schema),
        'breadcrumb_schema': breadcrumb_schema(request, [
            ('خانه', '/'), ('پرسش‌های متداول', request.path),
        ]),
    })


def market_news_list(request):
    news = MarketNews.objects.select_related(
        'variant__product', 'variant__product__category', 'price_observation',
    )
    trend = request.GET.get('trend', '').strip()
    if trend in MarketNews.Trend.values:
        news = news.filter(trend=trend)
    category = request.GET.get('category', '').strip()
    selected_category = None
    if category.isdigit():
        from catalog.models import Category
        selected_category = Category.objects.filter(pk=category, is_active=True).first()
        if selected_category:
            news = news.filter(variant__product__category=selected_category)
    page_obj = Paginator(news, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'content/market_news_list.html', {
        'page_obj': page_obj,
        'news_items': page_obj.object_list,
        'selected_trend': trend if trend in MarketNews.Trend.values else '',
        'selected_category': selected_category,
        'categories': MarketNews.objects.filter(
            variant__product__category__is_active=True,
        ).values_list('variant__product__category_id', 'variant__product__category__name').distinct().order_by('variant__product__category__name'),
        'trends': MarketNews.Trend.choices,
        'breadcrumb_schema': breadcrumb_schema(request, [('خانه', '/'), ('اخبار قیمت', request.path)]),
    })


def market_news_detail(request, pk):
    item = get_object_or_404(
        MarketNews.objects.select_related('variant__product__category', 'price_observation'),
        pk=pk,
    )
    news_schema = {
        '@context': 'https://schema.org',
        '@type': 'NewsArticle',
        'headline': item.headline,
        'datePublished': item.published_at.isoformat(),
        'mainEntityOfPage': request.build_absolute_uri(item.get_absolute_url()),
        'about': {'@type': 'Product', 'name': item.variant.product.name},
        'publisher': {'@type': 'Organization', 'name': 'آهن‌آلات آریا'},
    }
    return render(request, 'content/market_news_detail.html', {
        'news_item': item,
        'news_schema': _json_ld(news_schema),
        'breadcrumb_schema': breadcrumb_schema(request, [
            ('خانه', '/'), ('اخبار قیمت', reverse('content:market_news_list')),
            (item.headline, item.get_absolute_url()),
        ]),
    })


@login_required
@require_http_methods(['POST'])
def product_question_submit(request, slug):
    from catalog.models import Product
    from accounts.models import CustomerProfile

    product = get_object_or_404(Product, slug=slug, is_active=True, category__is_active=True)
    profile = CustomerProfile.objects.filter(user=request.user).first()
    if not profile:
        messages.error(request, 'برای ثبت پرسش، حساب مشتری تأییدشده لازم است.')
        return redirect(product.get_absolute_url())
    form = ProductQuestionForm(request.POST)
    if form.is_valid():
        question = form.save(commit=False)
        question.product = product
        question.profile = profile
        question.display_name = (question.display_name or profile.full_name or 'مشتری آریا').strip()[:80]
        question.save()
        messages.success(request, 'پرسش شما ثبت شد و پس از بازبینی منتشر می‌شود.')
    else:
        messages.error(request, 'پرسش ثبت نشد؛ موارد فرم را بررسی کنید.')
    return redirect(f'{product.get_absolute_url()}#product-questions')


@login_required
@require_http_methods(['POST'])
def product_review_submit(request, slug):
    from accounts.models import CustomerProfile
    from catalog.models import Product

    product = get_object_or_404(Product, slug=slug, is_active=True, category__is_active=True)
    profile = CustomerProfile.objects.filter(user=request.user).first()
    if not profile:
        messages.error(request, 'برای ثبت دیدگاه، حساب مشتری تأییدشده لازم است.')
        return redirect(product.get_absolute_url())
    form = ProductReviewForm(request.POST)
    if form.is_valid():
        review = form.save(commit=False)
        review.product = product
        review.profile = profile
        review.display_name = (profile.full_name or 'مشتری تأییدشده').strip()[:80]
        try:
            with transaction.atomic():
                review.save()
        except IntegrityError:
            messages.error(request, 'برای این کالا از حساب شما قبلاً دیدگاهی ثبت شده است.')
        else:
            messages.success(request, 'دیدگاه شما ثبت شد و پس از بازبینی منتشر می‌شود.')
    else:
        messages.error(request, 'دیدگاه ثبت نشد؛ امتیاز و متن را بررسی کنید.')
    return redirect(f'{product.get_absolute_url()}#product-reviews')


@login_required
@require_http_methods(['POST'])
def article_comment_submit(request, slug):
    from accounts.models import CustomerProfile

    article = get_object_or_404(
        Article, slug=slug, status=Article.Status.PUBLISHED, published_at__lte=timezone.now(),
    )
    profile = CustomerProfile.objects.filter(user=request.user).first()
    if not profile:
        messages.error(request, 'برای ثبت دیدگاه، حساب مشتری تأییدشده لازم است.')
        return redirect(article.get_absolute_url())
    form = ArticleCommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.article = article
        comment.profile = profile
        comment.display_name = (profile.full_name or 'مشتری تأییدشده').strip()[:80]
        comment.save()
        messages.success(request, 'دیدگاه شما ثبت شد و پس از بازبینی منتشر می‌شود.')
    else:
        messages.error(request, 'دیدگاه ثبت نشد؛ متن را بررسی کنید.')
    return redirect(f'{article.get_absolute_url()}#article-comments')
