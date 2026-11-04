from decimal import Decimal

from django import forms
from django.utils import timezone

from catalog.models import ProductVariant
from pricing.models import ShippingRate


class SteelWeightForm(forms.Form):
    CALCULATION_CHOICES = (
        ('round_bar', 'میلگرد یا میلهٔ گرد'),
        ('pipe', 'لولهٔ فولادی'),
        ('plate', 'ورق مستطیلی'),
        ('catalog', 'گونهٔ ثبت‌شده در کاتالوگ'),
    )
    calculation_type = forms.ChoiceField(label='نوع محاسبه', choices=CALCULATION_CHOICES)
    diameter_mm = forms.DecimalField(label='قطر بیرونی (میلی‌متر)', min_value=Decimal('0.1'), max_value=Decimal('10000'), required=False)
    thickness_mm = forms.DecimalField(label='ضخامت (میلی‌متر)', min_value=Decimal('0.1'), max_value=Decimal('10000'), required=False)
    width_mm = forms.DecimalField(label='عرض ورق (میلی‌متر)', min_value=Decimal('0.1'), max_value=Decimal('100000'), required=False)
    length_mm = forms.DecimalField(label='طول ورق (میلی‌متر)', min_value=Decimal('0.1'), max_value=Decimal('1000000'), required=False)
    length_m = forms.DecimalField(label='طول هر شاخه (متر)', min_value=Decimal('0.001'), max_value=Decimal('10000'), required=False)
    count = forms.DecimalField(label='تعداد شاخه / ورق', min_value=Decimal('1'), max_value=Decimal('1000000'), decimal_places=0, required=False, initial=1)
    variant = forms.ModelChoiceField(
        label='گونهٔ کاتالوگ',
        queryset=ProductVariant.objects.none(),
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['variant'].queryset = ProductVariant.objects.filter(
            is_active=True,
            product__is_active=True,
            product__category__is_active=True,
            weight_per_unit_kg__isnull=False,
        ).select_related('product', 'manufacturer').order_by('product__name', 'name')
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
        for name in ('diameter_mm', 'thickness_mm', 'width_mm', 'length_mm', 'length_m', 'count'):
            self.fields[name].widget.attrs.update({'step': 'any', 'inputmode': 'decimal'})

    def clean(self):
        cleaned = super().clean()
        calculation_type = cleaned.get('calculation_type')
        required_fields = {
            'round_bar': ('diameter_mm', 'length_m', 'count'),
            'pipe': ('diameter_mm', 'thickness_mm', 'length_m', 'count'),
            'plate': ('thickness_mm', 'width_mm', 'length_mm', 'count'),
            'catalog': ('variant', 'count'),
        }
        for name in required_fields.get(calculation_type, ()):
            if not cleaned.get(name):
                self.add_error(name, 'این مقدار برای نوع محاسبهٔ انتخاب‌شده لازم است.')
        diameter = cleaned.get('diameter_mm')
        thickness = cleaned.get('thickness_mm')
        if calculation_type == 'pipe' and diameter and thickness and thickness * 2 >= diameter:
            self.add_error('thickness_mm', 'ضخامت باید کمتر از نصف قطر بیرونی باشد.')
        return cleaned


class ShippingEstimateForm(forms.Form):
    origin_city = forms.ChoiceField(label='مبدأ')
    destination_city = forms.ChoiceField(label='مقصد')
    weight_tonnes = forms.DecimalField(
        label='وزن بار (تن)', min_value=Decimal('0.001'), max_value=Decimal('1000000'),
        max_digits=12, decimal_places=3, widget=forms.NumberInput(attrs={'step': '0.001', 'inputmode': 'decimal'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        routes = ShippingRate.objects.filter(is_active=True, valid_until__gt=timezone.now())
        origins = sorted(set(routes.values_list('origin_city', flat=True)))
        destinations = sorted(set(routes.values_list('destination_city', flat=True)))
        self.fields['origin_city'].choices = [('', 'انتخاب مبدأ')] + [(value, value) for value in origins]
        self.fields['destination_city'].choices = [('', 'انتخاب مقصد')] + [(value, value) for value in destinations]
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
