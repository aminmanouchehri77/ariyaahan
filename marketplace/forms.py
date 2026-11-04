from decimal import Decimal

from django import forms

from catalog.models import ProductVariant
from core.phone import normalize_iran_mobile

from .models import MarketplaceListing


class ActiveVariantField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        manufacturer = f'، {obj.manufacturer.name}' if obj.manufacturer else ''
        return f'{obj.product.name} — {obj.name}{manufacturer}'


class MarketplaceListingForm(forms.ModelForm):
    product_variant = ActiveVariantField(
        queryset=ProductVariant.objects.none(),
        label='انتخاب از کاتالوگ (اختیاری)',
        empty_label='اگر کالا در کاتالوگ است انتخاب کنید',
        required=False,
    )
    mobile = forms.CharField(label='شمارهٔ همراه', max_length=16, widget=forms.TextInput())
    contact_consent = forms.BooleanField(
        label='با تماس کارشناسان آریا برای بررسی این آگهی موافقم.',
        required=True,
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = MarketplaceListing
        fields = (
            'product_variant', 'product_label', 'quantity', 'quantity_unit',
            'price_amount', 'currency', 'city', 'details', 'contact_name',
            'mobile', 'company_name', 'show_company_name', 'contact_consent',
        )
        widgets = {
            'quantity': forms.NumberInput(attrs={'min': '0.001', 'max': '1000000', 'step': '0.001', 'inputmode': 'decimal'}),
            'price_amount': forms.NumberInput(attrs={'min': '1', 'step': '1', 'inputmode': 'numeric'}),
            'details': forms.Textarea(attrs={'rows': 4, 'placeholder': 'کیفیت، زمان تحویل یا شرایط معامله (اختیاری)'}),
        }

    def __init__(self, *args, kind=MarketplaceListing.Kind.OFFER, **kwargs):
        super().__init__(*args, **kwargs)
        self.kind = kind
        self.fields['product_variant'].queryset = ProductVariant.objects.filter(
            is_active=True,
            product__is_active=True,
            product__category__is_active=True,
        ).select_related('product', 'manufacturer').order_by('product__name', 'sort_order', 'name')
        self.fields['product_label'].required = False
        self.fields['product_label'].label = 'نام کالا / مشخصات'
        self.fields['quantity'].min_value = Decimal('0.001')
        self.fields['quantity'].max_value = Decimal('1000000')
        self.fields['price_amount'].required = False
        self.fields['price_amount'].label = 'مبلغ برای هر واحد (اختیاری)'
        self.fields['city'].label = 'شهر / محل تحویل'
        self.fields['company_name'].required = False
        self.fields['show_company_name'].label = 'با اجازهٔ خودم، نام شرکت در آگهی عمومی نمایش داده شود.'
        self.fields['mobile'].widget.attrs.update({
            'autocomplete': 'tel', 'inputmode': 'tel', 'placeholder': '۰۹۱۲۳۴۵۶۷۸۹', 'dir': 'ltr',
        })
        self.fields['contact_name'].widget.attrs.update({'autocomplete': 'name'})
        self.fields['company_name'].widget.attrs.update({'autocomplete': 'organization'})
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean_mobile(self):
        return normalize_iran_mobile(self.cleaned_data['mobile'])

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('website'):
            raise forms.ValidationError('درخواست ثبت نشد.')
        variant = cleaned.get('product_variant')
        if variant:
            manufacturer = f'، {variant.manufacturer.name}' if variant.manufacturer else ''
            cleaned['product_label'] = f'{variant.product.name} — {variant.name}{manufacturer}'
        elif not cleaned.get('product_label'):
            self.add_error('product_label', 'نام کالا را وارد کنید یا از کاتالوگ انتخاب کنید.')
        if not cleaned.get('company_name'):
            cleaned['show_company_name'] = False
        return cleaned

    def save(self, commit=True):
        listing = super().save(commit=False)
        listing.kind = self.kind
        listing.contact_consent = True
        if commit:
            listing.save()
        return listing
