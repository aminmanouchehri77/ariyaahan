"""Project bill-of-materials helpers: weight and price estimates."""

from decimal import Decimal

from pricing.selectors import latest_stock_observations, mark_price_state, mark_stock_state, with_latest_price

from .services import _line_total


def weight_kg(variant, quantity):
    unit = variant.unit
    if unit == 'kg':
        return quantity
    if unit == 'ton':
        return quantity * Decimal('1000')
    if variant.weight_per_unit_kg:
        return quantity * variant.weight_per_unit_kg
    return None


def project_lines(project):
    from catalog.models import ProductVariant

    items = list(project.items.all())
    variants = {
        v.pk: v for v in mark_stock_state(mark_price_state(list(latest_stock_observations(with_latest_price(
            ProductVariant.objects.filter(pk__in=[item.variant_id for item in items])
            .select_related('product', 'product__category', 'manufacturer')
        )))))
    }
    lines = []
    totals = {}
    total_weight = Decimal('0')
    weight_known = True
    for item in items:
        variant = variants.get(item.variant_id)
        if variant is None:
            continue
        line_total = None
        usable = (
            variant.latest_amount is not None and variant.latest_available
            and not variant.price_expired and not variant.price_validity_unknown
        )
        if usable:
            line_total = _line_total(variant, item.quantity)
            if line_total is not None:
                totals[variant.latest_currency] = totals.get(variant.latest_currency, Decimal('0')) + line_total
        weight = weight_kg(variant, item.quantity)
        if weight is None:
            weight_known = False
        else:
            total_weight += weight
        lines.append({'item': item, 'variant': variant, 'line_total': line_total, 'weight_kg': weight})
    return {
        'lines': lines,
        'currency_totals': totals,
        'total_weight_kg': total_weight.quantize(Decimal('0.01')),
        'total_weight_tonnes': (total_weight / Decimal('1000')).quantize(Decimal('0.001')),
        'weight_complete': weight_known,
    }
