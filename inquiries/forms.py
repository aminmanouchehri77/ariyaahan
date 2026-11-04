from django import forms
from catalog.models import ProductVariant
from core.phone import normalize_iran_mobile

from .models import Inquiry

class ActiveVariantField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        manufacturer = f'، {obj.manufacturer.name}' if obj.manufacturer else ''
        return f'{obj.product.name} — {obj.name}{manufacturer}'


class InquiryForm(forms.ModelForm):
    mobile = forms.CharField(
        label='شمارهٔ همراه',
        max_length=16,
        widget=forms.TextInput(),
    )
    product_variant = ActiveVariantField(
        queryset=ProductVariant.objects.none(),
        label='کالای موردنظر',
        empty_label='یک گونهٔ محصول انتخاب کنید',
        required=False,
    )

    class Meta:
        model = Inquiry
        fields = (
            'product_variant',
            'customer_name',
            'mobile',
            'requested_quantity',
            'quantity_unit',
            'message',
        )
        widgets = {
            'requested_quantity': forms.NumberInput(attrs={'min': '0.001', 'step': '0.001', 'inputmode': 'decimal'}),
            'quantity_unit': forms.TextInput(attrs={'placeholder': 'مثلاً تن، شاخه یا بندیل'}),
            'message': forms.Textarea(attrs={'rows': 4, 'placeholder': 'زمان تحویل، محل تخلیه یا نکتهٔ مهم دیگر (اختیاری)'}),
        }

    def __init__(self, *args, inquiry_kind=Inquiry.Kind.QUOTE, **kwargs):
        super().__init__(*args, **kwargs)
        self.inquiry_kind = inquiry_kind
        if inquiry_kind == Inquiry.Kind.CONTACT:
            self.fields.pop('product_variant')
        else:
            self.fields['product_variant'].queryset = ProductVariant.objects.filter(
                is_active=True,
                product__is_active=True,
                product__category__is_active=True,
            ).select_related('product', 'manufacturer').order_by('product__name', 'sort_order', 'name')
            self.fields['product_variant'].required = True
        self.fields['customer_name'].widget.attrs.update({'autocomplete': 'name'})
        self.fields['mobile'].widget.attrs.update({
            'autocomplete': 'tel',
            'inputmode': 'tel',
            'placeholder': '۰۹۱۲۳۴۵۶۷۸۹',
            'dir': 'ltr',
        })
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean_mobile(self):
        return normalize_iran_mobile(self.cleaned_data['mobile'])

    def clean(self):
        cleaned = super().clean()
        variant = cleaned.get('product_variant')
        if variant and not cleaned.get('quantity_unit'):
            cleaned['quantity_unit'] = variant.get_unit_display()
        return cleaned
