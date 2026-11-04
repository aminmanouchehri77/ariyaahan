from decimal import Decimal

from django import forms

from accounts.models import CustomerAddress
from core.phone import normalize_iran_mobile


class CartQuantityForm(forms.Form):
    quantity = forms.DecimalField(
        label='مقدار',
        min_value=Decimal('0.001'),
        max_value=Decimal('1000000'),
        max_digits=12,
        decimal_places=3,
        initial=Decimal('1'),
    )


class PreInvoiceForm(forms.Form):
    customer_name = forms.CharField(label='نام و نام خانوادگی', max_length=120)
    mobile = forms.CharField(label='شمارهٔ همراه', max_length=16, widget=forms.TextInput())
    company_name = forms.CharField(label='نام شرکت (اختیاری)', max_length=160, required=False)
    saved_address = forms.ModelChoiceField(
        label='نشانی ذخیره‌شده', queryset=CustomerAddress.objects.none(), required=False,
        empty_label='انتخاب نشانی (اختیاری)',
    )
    delivery_city = forms.CharField(label='شهر مقصد (اختیاری)', max_length=100, required=False)
    customer_note = forms.CharField(
        label='توضیحات (اختیاری)',
        max_length=1500,
        required=False,
        widget=forms.Textarea(attrs={'rows': 4, 'placeholder': 'زمان تحویل یا نکتهٔ موردنیاز برای برآورد'}),
    )

    def __init__(self, *args, addresses=None, **kwargs):
        super().__init__(*args, **kwargs)
        if addresses is not None:
            self.fields['saved_address'].queryset = addresses
        self.fields['customer_name'].widget.attrs.update({'autocomplete': 'name'})
        self.fields['mobile'].widget.attrs.update({
            'autocomplete': 'tel', 'inputmode': 'tel',
            'placeholder': '۰۹۱۲۳۴۵۶۷۸۹', 'dir': 'ltr',
        })
        self.fields['company_name'].widget.attrs.update({'autocomplete': 'organization'})
        for name in ('delivery_recipient', 'delivery_mobile', 'delivery_province', 'delivery_postal_code', 'delivery_address', 'delivery_note'):
            self.fields[name] = forms.CharField(required=False, max_length=700, label=name)
        self.fields['delivery_recipient'].label = 'نام تحویل‌گیرنده (اختیاری)'
        self.fields['delivery_mobile'].label = 'شمارهٔ تحویل‌گیرنده (اختیاری)'
        self.fields['delivery_province'].label = 'استان (اختیاری)'
        self.fields['delivery_postal_code'].label = 'کدپستی (اختیاری)'
        self.fields['delivery_address'].label = 'نشانی کامل (اختیاری)'
        self.fields['delivery_note'].label = 'توضیح تحویل (اختیاری)'
        self.fields['delivery_address'].widget = forms.Textarea(attrs={'rows': 3})
        self.fields['delivery_mobile'].widget.attrs.update({'inputmode': 'tel', 'autocomplete': 'tel', 'dir': 'ltr'})
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean_mobile(self):
        return normalize_iran_mobile(self.cleaned_data['mobile'])

    def clean_delivery_mobile(self):
        value = self.cleaned_data.get('delivery_mobile', '').strip()
        return normalize_iran_mobile(value) if value else ''
