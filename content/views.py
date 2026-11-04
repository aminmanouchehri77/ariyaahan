import json

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.seo import breadcrumb_schema
from .forms import CompanyRequestForm
from .models import Article, ArticleTag, CompanyPage, CompanyRequest, FAQ, MediaItem


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
        Article.objects.prefetch_related('tags'),
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
    return render(request, 'content/article_detail.html', {
        'article': article,
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
