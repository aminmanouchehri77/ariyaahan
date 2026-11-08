"""Data for the custom admin dashboard (templates/admin/index.html).

Every block is permission-aware: a staff member only sees the numbers and
shortcuts for models they are allowed to view.
"""

from datetime import timedelta
from decimal import Decimal

from django import template
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

register = template.Library()


def _url(name, query=''):
    try:
        return reverse(name) + (f'?{query}' if query else '')
    except NoReverseMatch:
        return ''


@register.simple_tag(takes_context=True)
def admin_dashboard(context):
    user = context['request'].user
    can = user.has_perm
    now = timezone.now()
    today = timezone.localdate()
    data = {'kpis': [], 'tasks': [], 'quick': [], 'recent_orders': [], 'audit': [], 'chart': [], 'freshness': None}

    if can('orders.view_preinvoice'):
        from orders.models import PreInvoice

        counts = PreInvoice.objects.aggregate(
            pending=Count('pk', filter=Q(status__in=(PreInvoice.Status.PENDING, PreInvoice.Status.REVIEW))),
            awaiting=Count('pk', filter=Q(status=PreInvoice.Status.AWAITING_CUSTOMER)),
            confirmed=Count('pk', filter=Q(status=PreInvoice.Status.CONFIRMED)),
            today=Count('pk', filter=Q(created_at__date=today)),
        )
        data['kpis'].append({'label': 'پیش‌فاکتور امروز', 'value': counts['today'], 'icon': 'receipt', 'url': _url('admin:orders_preinvoice_changelist')})
        if counts['pending']:
            data['tasks'].append({'label': 'پیش‌فاکتور منتظر صدور قیمت', 'value': counts['pending'], 'tone': 'molten', 'url': _url('admin:orders_preinvoice_changelist', 'status__in=pending,review')})
        if counts['confirmed']:
            data['tasks'].append({'label': 'پیش‌فاکتور پذیرفته‌شده؛ آمادهٔ ساخت سفارش', 'value': counts['confirmed'], 'tone': 'success', 'url': _url('admin:orders_preinvoice_changelist', 'status__exact=confirmed')})
        if counts['awaiting']:
            data['tasks'].append({'label': 'در انتظار پذیرش مشتری', 'value': counts['awaiting'], 'tone': 'info', 'url': _url('admin:orders_preinvoice_changelist', 'status__exact=awaiting_customer')})

    if can('orders.view_order'):
        from orders.models import Order, OrderItem

        awaiting = Order.objects.filter(status=Order.Status.AWAITING_PAYMENT).count()
        to_ship = Order.objects.filter(status__in=(Order.Status.PAID, Order.Status.PROCESSING)).count()
        data['kpis'].append({'label': 'سفارش در انتظار پرداخت', 'value': awaiting, 'icon': 'credit-card', 'url': _url('admin:orders_order_changelist', 'status__exact=awaiting_payment')})
        if to_ship:
            data['tasks'].append({'label': 'سفارش پرداخت‌شده برای آماده‌سازی/ارسال', 'value': to_ship, 'tone': 'molten', 'url': _url('admin:orders_order_changelist', 'status__in=paid,processing')})
        data['recent_orders'] = list(Order.objects.select_related('customer').order_by('-created_at')[:6])
        for order in data['recent_orders']:
            order.total = sum((item.line_total for item in OrderItem.objects.filter(order=order)), Decimal('0'))
        start = today - timedelta(days=13)
        rows = dict(
            Order.objects.filter(created_at__date__gte=start)
            .annotate(day=TruncDate('created_at')).values('day').annotate(n=Count('pk')).values_list('day', 'n')
        )
        series = [(start + timedelta(days=offset), rows.get(start + timedelta(days=offset), 0)) for offset in range(14)]
        peak = max([n for _, n in series] + [1])
        data['chart'] = [{'day': day, 'count': n, 'height': round(8 + 92 * n / peak)} for day, n in series]

    if can('orders.view_paymentrecord'):
        # Payment figures need their own permission, not just order access.
        from orders.models import PaymentRecord

        paid_today = PaymentRecord.objects.filter(status=PaymentRecord.Status.SUCCEEDED, verified_at__date=today)
        revenue = paid_today.aggregate(total=Sum('amount_rial'))['total'] or Decimal('0')
        data['kpis'].insert(0, {'label': 'دریافتی امروز (ریال)', 'value': revenue, 'money': True, 'icon': 'wallet', 'url': _url('admin:orders_paymentrecord_changelist')})
        review = PaymentRecord.objects.filter(status=PaymentRecord.Status.REQUIRES_REVIEW).count()
        if review:
            data['tasks'].append({'label': 'تراکنش نیازمند بررسی (حداکثر ۳۰ دقیقه برای Verify)', 'value': review, 'tone': 'danger', 'url': _url('admin:orders_paymentrecord_changelist', 'status__exact=review')})

    if can('pricing.view_priceobservation'):
        from catalog.models import ProductVariant
        from pricing.models import PriceObservation, StockObservation
        from pricing.selectors import with_latest_price

        pending_prices = PriceObservation.objects.filter(status=PriceObservation.Status.PENDING).count()
        pending_stock = (
            StockObservation.objects.filter(status=StockObservation.Status.PENDING).count()
            if can('pricing.view_stockobservation') else 0
        )
        if pending_prices:
            data['tasks'].append({'label': 'قیمت در انتظار تأیید', 'value': pending_prices, 'tone': 'molten', 'url': _url('admin:pricing_priceobservation_changelist', 'status__exact=pending')})
        if pending_stock:
            data['tasks'].append({'label': 'موجودی در انتظار تأیید', 'value': pending_stock, 'tone': 'info', 'url': _url('admin:pricing_stockobservation_changelist', 'status__exact=pending')})
        variants = list(with_latest_price(ProductVariant.objects.filter(is_active=True, product__is_active=True)).values(
            'latest_amount', 'latest_valid_until',
        ))
        if variants:
            fresh = sum(1 for v in variants if v['latest_amount'] is not None and v['latest_valid_until'] and v['latest_valid_until'] > now)
            score = round(100 * fresh / len(variants))
            data['freshness'] = {'score': score, 'fresh': fresh, 'total': len(variants), 'stale': len(variants) - fresh}
            data['kpis'].append({'label': 'تازگی قیمت‌ها', 'value': score, 'suffix': '٪', 'icon': 'timer', 'url': _url('admin:pricing_priceobservation_changelist')})
        if can('pricing.add_priceobservation'):
            data['quick'].append({'label': 'ثبت قیمت تازه', 'icon': 'plus', 'url': _url('admin:pricing_priceobservation_add')})
        if can('pricing.add_stockobservation'):
            data['quick'].append({'label': 'ثبت موجودی', 'icon': 'warehouse', 'url': _url('admin:pricing_stockobservation_add')})

    if can('catalog.add_product'):
        data['quick'].append({'label': 'افزودن کالا', 'icon': 'package', 'url': _url('admin:catalog_product_add')})
    if can('content.add_article'):
        data['quick'].append({'label': 'نوشتن مقاله', 'icon': 'pencil', 'url': _url('admin:content_article_add')})

    if can('inquiries.view_inquiry'):
        from inquiries.models import Inquiry

        new = Inquiry.objects.filter(status=Inquiry.Status.NEW).count()
        data['kpis'].append({'label': 'استعلام و پیام جدید', 'value': new, 'icon': 'message-circle', 'url': _url('admin:inquiries_inquiry_changelist', 'status__exact=new')})
        if new:
            data['tasks'].append({'label': 'استعلام/پیام بی‌پاسخ', 'value': new, 'tone': 'molten', 'url': _url('admin:inquiries_inquiry_changelist', 'status__exact=new')})

    if can('marketplace.view_marketplacelisting'):
        from marketplace.models import ListingReport, MarketplaceListing

        pending = MarketplaceListing.objects.filter(status=MarketplaceListing.Status.PENDING).count()
        reports = (
            ListingReport.objects.filter(status=ListingReport.Status.OPEN).count()
            if can('marketplace.view_listingreport') else 0
        )
        if pending:
            data['tasks'].append({'label': 'آگهی تالار منتظر بررسی', 'value': pending, 'tone': 'info', 'url': _url('admin:marketplace_marketplacelisting_changelist', 'status__exact=pending')})
        if reports:
            data['tasks'].append({'label': 'گزارش تخلف باز', 'value': reports, 'tone': 'danger', 'url': _url('admin:marketplace_listingreport_changelist', 'status__exact=open')})

    from content.models import ArticleComment, ProductQuestion, ProductReview

    moderation_queues = [
        (model, name) for model, name in (
            (ProductQuestion, 'productquestion'), (ProductReview, 'productreview'), (ArticleComment, 'articlecomment'),
        ) if can(f'content.view_{name}')
    ]
    moderation = sum(model.objects.filter(status=model.Status.PENDING).count() for model, _ in moderation_queues)
    if moderation:
        first = moderation_queues[0][1]
        data['tasks'].append({'label': 'دیدگاه/پرسش منتظر بازبینی', 'value': moderation, 'tone': 'info', 'url': _url(f'admin:content_{first}_changelist', 'status__exact=pending')})

    if can('core.view_auditlog'):
        from core.models import AuditLog

        data['audit'] = list(AuditLog.objects.select_related('actor').order_by('-created_at')[:8])
    return data
