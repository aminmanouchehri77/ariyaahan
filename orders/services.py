from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from catalog.models import ProductVariant
from pricing.models import PriceObservation
from pricing.selectors import mark_price_state, with_latest_price

from .cart import Cart
from .models import Order, OrderItem, PreInvoice


CURRENCY_LABELS = {'IRR': 'ریال', 'IRT': 'تومان', 'USD': 'دلار آمریکا'}
PRICE_BASIS_LABELS = dict(PriceObservation.PriceBasis.choices)
KG_PER_TONNE = Decimal('1000')


def _price_factor(variant):
    basis = variant.latest_price_basis
    quantity_unit = variant.unit
    if not basis:
        return None
    if basis == quantity_unit:
        return Decimal('1')
    if quantity_unit == 'ton' and basis == 'kg':
        return KG_PER_TONNE
    if quantity_unit == 'kg' and basis == 'ton':
        return Decimal('1') / KG_PER_TONNE
    return None


def _line_total(variant, quantity):
    if (
        variant.latest_amount is None
        or variant.latest_available is not True
        or variant.price_expired
        or variant.price_validity_unknown
    ):
        return None
    factor = _price_factor(variant)
    if factor is None:
        return None
    total = variant.latest_amount * quantity * factor
    return total.quantize(Decimal('1'), rounding=ROUND_HALF_UP)


def build_cart_context(request):
    cart = Cart(request)
    entries = list(cart.items.items())
    variant_ids = [int(variant_id) for variant_id, _ in entries]
    variants = mark_price_state(list(with_latest_price(
        ProductVariant.objects.filter(
            pk__in=variant_ids,
            is_active=True,
            product__is_active=True,
            product__category__is_active=True,
        ).select_related('product', 'manufacturer')
    )))
    by_id = {str(variant.pk): variant for variant in variants}
    totals = defaultdict(lambda: Decimal('0'))
    lines = []

    for variant_id, raw_quantity in entries:
        variant = by_id.get(variant_id)
        if variant is None:
            cart.remove(variant_id)
            continue
        quantity = Decimal(raw_quantity)
        line_total = _line_total(variant, quantity)
        if line_total is not None:
            totals[variant.latest_currency] += line_total

        if variant.latest_amount is None:
            price_state = 'قیمتی ثبت نشده؛ نیازمند استعلام'
        elif variant.latest_available is False:
            price_state = 'در آخرین ثبت ناموجود بوده است'
        elif variant.price_expired:
            price_state = 'آخرین قیمت منقضی شده است'
        elif variant.price_validity_unknown:
            price_state = 'اعتبار آخرین قیمت مشخص نیست'
        elif _price_factor(variant) is None:
            price_state = 'واحد محاسباتی قیمت مشخص یا سازگار نیست'
        else:
            price_state = 'قیمت ثبت‌شده قابل محاسبه است'

        lines.append({
            'variant': variant,
            'quantity': quantity,
            'line_total': line_total,
            'price_state': price_state,
            'price_basis_label': PRICE_BASIS_LABELS.get(variant.latest_price_basis, ''),
            'price_is_usable': line_total is not None,
            'tax_included': variant.latest_tax_included,
        })

    has_unpriced_items = any(line['line_total'] is None for line in lines)
    currency_totals = [
        {'currency': currency, 'label': CURRENCY_LABELS.get(currency, currency), 'amount': amount}
        for currency, amount in sorted(totals.items())
    ]
    return {
        'cart': cart,
        'cart_lines': lines,
        'cart_count': len(lines),
        'currency_totals': currency_totals,
        'has_unpriced_items': has_unpriced_items,
        'cart_is_empty': not lines,
    }


def snapshot_line(line):
    variant = line['variant']
    return {
        'variant': variant,
        'price_observation_id': variant.latest_price_observation_id,
        'product_name': variant.product.name,
        'variant_name': variant.name,
        'sku': variant.sku or '',
        'quantity': line['quantity'],
        'quantity_unit': variant.unit,
        'unit_price': variant.latest_amount,
        'currency': variant.latest_currency or '',
        'price_basis': variant.latest_price_basis or '',
        'price_unit_label': variant.latest_unit_label or '',
        'line_total': line['line_total'],
        'price_is_usable': line['price_is_usable'],
        'tax_included': variant.latest_tax_included,
        'availability': variant.latest_available,
        'price_location': variant.latest_location or '',
        'price_observed_at': variant.latest_observed_at,
        'price_valid_until': variant.latest_valid_until,
    }


@transaction.atomic
def convert_preinvoice_to_order(preinvoice_id, actor=None):
    """Convert a confirmed quote request only while its exact prices remain valid."""
    preinvoice = PreInvoice.objects.select_for_update().select_related('customer').get(pk=preinvoice_id)
    if preinvoice.status != PreInvoice.Status.CONFIRMED:
        raise ValidationError('ابتدا درخواست پیش‌فاکتور را بررسی و تأیید کنید.')
    if hasattr(preinvoice, 'order'):
        raise ValidationError('برای این پیش‌فاکتور قبلاً سفارش ساخته شده است.')

    lines = list(preinvoice.items.select_related('variant__product').order_by('pk'))
    currencies = {line.currency for line in lines if line.price_is_usable and line.currency}
    if not lines or len(currencies) != 1 or any(not line.price_is_usable for line in lines):
        preinvoice.status = PreInvoice.Status.REVIEW
        preinvoice.admin_note = (preinvoice.admin_note + '\nرد خودکار تبدیل: ردیف‌ها قیمت معتبر و یک ارز مشترک ندارند.').strip()[:5000]
        preinvoice.save(update_fields=('status', 'admin_note', 'updated_at'))
        return None

    now = timezone.now()
    for line in lines:
        latest = PriceObservation.objects.filter(
            variant_id=line.variant_id,
            status=PriceObservation.Status.APPROVED,
        ).order_by('-observed_at', '-pk').first() if line.variant_id else None
        if (
            not latest
            or latest.pk != line.price_observation_id
            or not latest.is_available
            or not latest.valid_until
            or latest.valid_until <= now
            or latest.amount != line.unit_price
            or latest.currency != line.currency
            or latest.price_basis != line.price_basis
        ):
            preinvoice.status = PreInvoice.Status.REVIEW
            preinvoice.admin_note = (preinvoice.admin_note + '\nرد خودکار تبدیل: قیمت یا موجودی تغییر کرده/منقضی شده است.').strip()[:5000]
            preinvoice.save(update_fields=('status', 'admin_note', 'updated_at'))
            return None

    order = Order(
        preinvoice=preinvoice,
        customer=preinvoice.customer,
        currency=next(iter(currencies)),
        delivery_recipient=preinvoice.delivery_recipient,
        delivery_mobile=preinvoice.delivery_mobile,
        delivery_province=preinvoice.delivery_province,
        delivery_city=preinvoice.delivery_city,
        delivery_postal_code=preinvoice.delivery_postal_code,
        delivery_address=preinvoice.delivery_address,
        delivery_note=preinvoice.delivery_note,
        customer_note=preinvoice.customer_note,
    )
    order._status_actor = actor
    order.save()
    for line in lines:
        OrderItem.objects.create(
            order=order,
            variant=line.variant,
            product_name=line.product_name,
            variant_name=line.variant_name,
            sku=line.sku,
            quantity=line.quantity,
            quantity_unit=line.quantity_unit,
            unit_price=line.unit_price,
            currency=line.currency,
            price_basis=line.price_basis,
            price_unit_label=line.price_unit_label,
            line_total=line.line_total,
            tax_included=line.tax_included,
        )
    preinvoice.status = PreInvoice.Status.CONVERTED
    preinvoice.save(update_fields=('status', 'updated_at'))
    return order
