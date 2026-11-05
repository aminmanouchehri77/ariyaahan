from decimal import Decimal

from django import forms

from pricing.models import PriceObservation
from .models import Manufacturer


class CategoryFilterForm(forms.Form):
    size = forms.CharField(label='سایز', max_length=80, required=False)
    manufacturer = forms.ModelChoiceField(label='کارخانه', queryset=Manufacturer.objects.none(), required=False)
    grade = forms.CharField(label='گرید', max_length=80, required=False)
    standard = forms.CharField(label='استاندارد', max_length=100, required=False)
    location = forms.CharField(label='محل تحویل', max_length=140, required=False)
    currency = forms.ChoiceField(
        label='ارز قیمت', required=False,
        choices=[('', 'همهٔ ارزها'), *PriceObservation.Currency.choices],
    )
    price_basis = forms.ChoiceField(
        label='واحد قیمت', required=False,
        choices=[('', 'همهٔ واحدها'), *PriceObservation.PriceBasis.choices],
    )
    tax_status = forms.ChoiceField(
        label='وضعیت مالیات', required=False,
        choices=(('', 'هر وضعیت مالیات'), ('included', 'شامل مالیات'), ('excluded', 'بدون مالیات'), ('unknown', 'نامشخص')),
    )
    min_price = forms.DecimalField(label='حداقل قیمت', min_value=Decimal('1'), max_digits=18, decimal_places=0, required=False)
    max_price = forms.DecimalField(label='حداکثر قیمت', min_value=Decimal('1'), max_digits=18, decimal_places=0, required=False)
    availability = forms.ChoiceField(
        label='موجودی تأییدشده', required=False,
        choices=(('', 'هر وضعیت'), ('available', 'موجودی تأییدشدهٔ موجود'), ('unavailable', 'موجودی تأییدشدهٔ ناموجود')),
    )
    ordering = forms.ChoiceField(
        label='مرتب‌سازی', required=False,
        choices=(
            ('recent', 'تازه‌ترین ثبت قیمت'),
            ('price_asc', 'ارزان‌ترین'),
            ('price_desc', 'گران‌ترین'),
            ('name', 'نام کالا'),
        ),
        initial='recent',
    )

    def __init__(self, *args, category, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['manufacturer'].queryset = Manufacturer.objects.filter(
            is_active=True,
            variants__is_active=True,
            variants__product__is_active=True,
            variants__product__category=category,
        ).distinct().order_by('name')
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
        for name in ('size', 'grade', 'standard', 'location'):
            self.fields[name].widget.attrs.update({'type': 'search'})

    def clean(self):
        cleaned = super().clean()
        minimum = cleaned.get('min_price')
        maximum = cleaned.get('max_price')
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error('max_price', 'حداکثر قیمت باید برابر یا بیشتر از حداقل قیمت باشد.')
        needs_comparable_price = minimum is not None or maximum is not None or cleaned.get('ordering') in {'price_asc', 'price_desc'}
        if needs_comparable_price and not cleaned.get('currency'):
            self.add_error('currency', 'برای فیلتر یا مرتب‌سازی قیمت، یک ارز مشخص انتخاب کنید.')
        if needs_comparable_price and not cleaned.get('price_basis'):
            self.add_error('price_basis', 'برای فیلتر یا مرتب‌سازی قیمت، واحد قیمت را مشخص کنید.')
        if needs_comparable_price and not cleaned.get('location'):
            self.add_error('location', 'برای فیلتر یا مرتب‌سازی قیمت، محل تحویل را مشخص کنید.')
        if needs_comparable_price and not cleaned.get('tax_status'):
            self.add_error('tax_status', 'برای فیلتر یا مرتب‌سازی قیمت، وضعیت مالیات را مشخص کنید.')
        return cleaned
