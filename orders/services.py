from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from catalog.models import ProductVariant
from pricing.models import PriceObservation, StockObservation
from pricing.selectors import latest_stock_observations, mark_price_state, mark_stock_state, with_latest_price

from .cart import Cart
from .models import Order, OrderItem, PreInvoice


CURRENCY_LABELS = {'IRR': 'ریال', 'IRT': 'تومان', 'USD': 'دلار آمریکا'}
PRICE_BASIS_LABELS = dict(PriceObservation.PriceBasis.choices)
KG_PER_TONNE = Decimal('1000')
MASS_UNITS = {'kg', 'ton'}


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


def _convert_stock_quantity(stock_quantity, stock_unit, variant):
    order_unit = variant.unit
    if stock_quantity is None or not stock_unit:
        return None
    if stock_unit == order_unit:
        return stock_quantity
    if stock_unit == 'kg' and order_unit == 'ton':
        return stock_quantity / KG_PER_TONNE
    if stock_unit == 'ton' and order_unit == 'kg':
        return stock_quantity * KG_PER_TONNE
    weight_per_unit = variant.weight_per_unit_kg
    if not weight_per_unit or weight_per_unit <= 0:
        return None
    if stock_unit in MASS_UNITS and order_unit not in MASS_UNITS:
        stock_kg = stock_quantity * (KG_PER_TONNE if stock_unit == 'ton' else Decimal('1'))
        return stock_kg / weight_per_unit
    if stock_unit not in MASS_UNITS and order_unit in MASS_UNITS:
        stock_kg = stock_quantity * weight_per_unit
        return stock_kg / KG_PER_TONNE if order_unit == 'ton' else stock_kg
    return None


def _stock_quantity_in_order_units(variant):
    return _convert_stock_quantity(
        variant.latest_stock_quantity,
        variant.latest_stock_unit,
        variant,
    )


def _stock_is_usable(variant, quantity):
    if (
        not variant.latest_stock_observation_id
        or variant.stock_expired
        or variant.stock_validity_unknown
        or variant.latest_stock_available is not True
        or not variant.latest_stock_valid_until
        or variant.latest_stock_valid_until <= timezone.now()
    ):
        return False
    available_quantity = _stock_quantity_in_order_units(variant)
    return available_quantity is not None and available_quantity >= quantity


def build_cart_context(request):
    cart = Cart(request)
    entries = list(cart.items.items())
    variant_ids = [int(variant_id) for variant_id, _ in entries]
    variants = mark_stock_state(mark_price_state(list(latest_stock_observations(with_latest_price(
        ProductVariant.objects.filter(
            pk__in=variant_ids,
            is_active=True,
            product__is_active=True,
            product__category__is_active=True,
        ).select_related('product', 'manufacturer')
    )))))
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
            'stock_is_usable': _stock_is_usable(variant, quantity),
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
        'stock_observation_id': variant.latest_stock_observation_id,
        'stock_quantity': variant.latest_stock_quantity,
        'stock_unit': variant.latest_stock_unit or '',
        'stock_is_usable': line['stock_is_usable'],
        'stock_available': variant.latest_stock_available,
        'stock_location': variant.latest_stock_location or '',
        'stock_source': variant.latest_stock_source or '',
        'stock_observed_at': variant.latest_stock_observed_at,
        'stock_valid_until': variant.latest_stock_valid_until,
    }


def _session_value(value):
    if isinstance(value, Decimal):
        return format(value, 'f')
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value


def checkout_quote_snapshot(context):
    lines = {}
    for line in context['cart_lines']:
        variant = line['variant']
        lines[str(variant.pk)] = {
            'product_name': variant.product.name,
            'variant_name': variant.name,
            'quantity': _session_value(line['quantity']),
            'price_observation_id': variant.latest_price_observation_id,
            'unit_price': _session_value(variant.latest_amount),
            'currency': variant.latest_currency or '',
            'price_basis': variant.latest_price_basis or '',
            'price_unit_label': variant.latest_unit_label or '',
            'price_location': variant.latest_location or '',
            'price_available': variant.latest_available,
            'price_is_usable': line['price_is_usable'],
            'price_state': line['price_state'],
            'tax_included': variant.latest_tax_included,
            'price_observed_at': _session_value(variant.latest_observed_at),
            'price_valid_until': _session_value(variant.latest_valid_until),
            'line_total': _session_value(line['line_total']),
            'stock_observation_id': variant.latest_stock_observation_id,
            'stock_quantity': _session_value(variant.latest_stock_quantity),
            'stock_unit': variant.latest_stock_unit or '',
            'stock_status': variant.stock_status,
            'stock_available': variant.latest_stock_available,
            'stock_location': variant.latest_stock_location or '',
            'stock_observed_at': _session_value(variant.latest_stock_observed_at),
            'stock_valid_until': _session_value(variant.latest_stock_valid_until),
            'stock_is_usable': line['stock_is_usable'],
        }
    return {'lines': lines}


def checkout_quote_changes(previous, current):
    previous_lines = (previous or {}).get('lines', {})
    current_lines = (current or {}).get('lines', {})
    price_fields = (
        'price_observation_id', 'unit_price', 'currency', 'price_basis', 'price_unit_label',
        'price_location', 'price_available', 'price_is_usable', 'tax_included',
        'price_observed_at', 'price_valid_until', 'line_total',
    )
    stock_fields = (
        'stock_observation_id', 'stock_quantity', 'stock_unit', 'stock_status',
        'stock_available', 'stock_location', 'stock_observed_at', 'stock_valid_until',
        'stock_is_usable',
    )
    changes = []
    line_ids = list(dict.fromkeys([*previous_lines, *current_lines]))
    for variant_id in line_ids:
        old = previous_lines.get(variant_id)
        new = current_lines.get(variant_id)
        if old is None or new is None:
            price_changed = stock_changed = True
            quantity_changed = True
        else:
            price_changed = any(old.get(field) != new.get(field) for field in price_fields)
            stock_changed = any(old.get(field) != new.get(field) for field in stock_fields)
            quantity_changed = old.get('quantity') != new.get('quantity')
        if not (price_changed or stock_changed or quantity_changed):
            continue

        old_total = old.get('line_total') if old else None
        new_total = new.get('line_total') if new else None
        difference = None
        if (
            old_total is not None and new_total is not None and old.get('currency') == new.get('currency')
        ):
            difference = format(Decimal(new_total) - Decimal(old_total), 'f')
        changes.append({
            'kind': 'added' if old is None else 'removed' if new is None else 'updated',
            'name': (new or old).get('product_name', ''),
            'variant_name': (new or old).get('variant_name', ''),
            'price_changed': price_changed,
            'stock_changed': stock_changed,
            'quantity_changed': quantity_changed,
            'old': old or {},
            'new': new or {},
            'line_total_difference': difference,
        })
    return changes


@transaction.atomic
def convert_preinvoice_to_order(preinvoice_id, actor=None):
    """Convert a confirmed quote only while its captured price and stock remain valid."""
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
        latest = PriceObservation.objects.select_for_update().filter(
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
            or (line.variant and line.variant.unit != line.quantity_unit)
        ):
            preinvoice.status = PreInvoice.Status.REVIEW
            preinvoice.admin_note = (preinvoice.admin_note + '\nرد خودکار تبدیل: قیمت یا موجودی تغییر کرده/منقضی شده است.').strip()[:5000]
            preinvoice.save(update_fields=('status', 'admin_note', 'updated_at'))
            return None

        latest_stock = StockObservation.objects.select_for_update().filter(
            variant_id=line.variant_id,
            status=StockObservation.Status.APPROVED,
        ).order_by('-observed_at', '-pk').first() if line.variant_id else None
        stock_quantity = _convert_stock_quantity(
            latest_stock.quantity, latest_stock.unit, line.variant,
        ) if latest_stock and line.variant else None
        if (
            not line.stock_is_usable
            or not latest_stock
            or latest_stock.pk != line.stock_observation_id
            or not latest_stock.is_available
            or not latest_stock.valid_until
            or latest_stock.valid_until <= now
            or stock_quantity is None
            or stock_quantity < line.quantity
        ):
            preinvoice.status = PreInvoice.Status.REVIEW
            preinvoice.admin_note = (preinvoice.admin_note + '\nرد خودکار تبدیل: موجودی تأییدشده تغییر کرده، ناکافی یا منقضی شده است.').strip()[:5000]
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
