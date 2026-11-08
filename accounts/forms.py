import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from catalog.models import ProductVariant
from core.phone import normalize_iran_mobile
from pricing.models import PriceObservation
from .models import CustomerAddress, CustomerProfile, PriceAlert


class MobileLoginForm(forms.Form):
    mobile = forms.CharField(
        label='شمارهٔ همراه',
        max_length=32,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'type': 'tel',
            'inputmode': 'tel',
            'autocomplete': 'tel',
            'placeholder': '۰۹۱۲۳۴۵۶۷۸۹',
            'dir': 'ltr',
            'autofocus': True,
        }),
    )

    def clean_mobile(self):
        try:
            return normalize_iran_mobile(self.cleaned_data['mobile'])
        except ValidationError as error:
            raise forms.ValidationError(error.messages) from error


class OTPVerificationForm(forms.Form):
    code = forms.CharField(
        label='کد پیامک‌شده',
        min_length=6,
        max_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control otp-input',
            'inputmode': 'numeric',
            'autocomplete': 'one-time-code',
            'placeholder': '------',
            'dir': 'ltr',
            'autofocus': True,
        }),
    )
    full_name = forms.CharField(
        label='نام و نام خانوادگی (اختیاری)',
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'autocomplete': 'name',
            'placeholder': 'برای تکمیل پروفایل',
        }),
    )

    def clean_code(self):
        code = self.cleaned_data['code'].translate(
            str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
        ).strip()
        if not re.fullmatch(r'\d{6}', code):
            raise forms.ValidationError('کد باید دقیقاً ۶ رقم باشد.')
        return code


class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ('full_name', 'allow_price_notifications')
        labels = {
            'full_name': 'نام و نام خانوادگی',
            'allow_price_notifications': 'اجازهٔ دریافت اعلان هشدارهای قیمتی در حساب کاربری',
        }
        widgets = {'full_name': forms.TextInput(attrs={'autocomplete': 'name'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')


class CustomerAddressForm(forms.ModelForm):
    class Meta:
        model = CustomerAddress
        fields = (
            'title', 'recipient', 'mobile', 'province', 'city', 'postal_code',
            'address', 'delivery_note', 'is_default',
        )
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3, 'autocomplete': 'street-address'}),
            'delivery_note': forms.TextInput(attrs={'placeholder': 'نشانی تخلیه، ساعت تحویل یا توضیح لازم'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['mobile'].widget.attrs.update({'inputmode': 'tel', 'autocomplete': 'tel', 'dir': 'ltr'})
        self.fields['postal_code'].widget.attrs.update({'inputmode': 'numeric', 'dir': 'ltr', 'maxlength': 10})
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean_mobile(self):
        return normalize_iran_mobile(self.cleaned_data['mobile'])


class ActiveVariantField(forms.ModelChoiceField):
    def label_from_instance(self, variant):
        manufacturer = f'، {variant.manufacturer.name}' if variant.manufacturer else ''
        return f'{variant.product.name} — {variant.name}{manufacturer}'


class PriceAlertForm(forms.ModelForm):
    consent = forms.BooleanField(
        label='موافقم اعلان هشدار قیمت در حساب کاربری‌ام ثبت شود.', required=True,
    )
    variant = ActiveVariantField(queryset=ProductVariant.objects.none(), label='کالا', empty_label='انتخاب کالا')
    target_amount = forms.DecimalField(
        label='مبلغ هدف', required=False, min_value=1, max_digits=18, decimal_places=0,
        widget=forms.NumberInput(attrs={'min': '1', 'step': '1', 'inputmode': 'numeric'}),
    )
    percent_change = forms.DecimalField(
        label='درصد تغییر از قیمت مبنا', required=False, min_value='0.01', max_value='100',
        max_digits=5, decimal_places=2,
        widget=forms.NumberInput(attrs={'min': '0.01', 'max': '100', 'step': '0.01', 'inputmode': 'decimal'}),
    )

    class Meta:
        model = PriceAlert
        fields = ('variant', 'condition_type', 'direction', 'target_amount', 'percent_change', 'currency', 'price_basis', 'notify_sms')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields.pop('consent', None)
        self.fields['variant'].queryset = ProductVariant.objects.filter(
            is_active=True, product__is_active=True, product__category__is_active=True,
        ).select_related('product', 'manufacturer').order_by('product__name', 'sort_order', 'name')
        self.fields['notify_sms'].label = 'علاوه بر اعلان حساب، پیامک هم دریافت کنم'
        self.fields['notify_sms'].help_text = 'حداکثر چند پیامک در روز برای هر حساب؛ قابل لغو با ویرایش هشدار.'
        for name, field in self.fields.items():
            if name != 'notify_sms':
                field.widget.attrs.setdefault('class', 'form-control')

    def clean(self):
        cleaned = super().clean()
        variant = cleaned.get('variant')
        condition_type = cleaned.get('condition_type')
        if variant and cleaned.get('price_basis') and cleaned['price_basis'] != variant.unit:
            self.add_error('price_basis', 'واحد مبنای هشدار باید با واحد فروش گونهٔ انتخاب‌شده یکسان باشد.')
        if condition_type == PriceAlert.ConditionType.TARGET:
            if not cleaned.get('target_amount'):
                self.add_error('target_amount', 'مبلغ هدف را وارد کنید.')
            self._errors.pop('percent_change', None)
            cleaned['percent_change'] = 0
        elif condition_type == PriceAlert.ConditionType.PERCENT_CHANGE:
            if not cleaned.get('percent_change'):
                self.add_error('percent_change', 'درصد تغییر را بین ۰٫۰۱ تا ۱۰۰ وارد کنید.')
            self._errors.pop('target_amount', None)
            cleaned['target_amount'] = 0
            keeping_baseline = (
                self.instance.pk
                and self.instance.condition_type == PriceAlert.ConditionType.PERCENT_CHANGE
                and variant is not None
                and variant.pk == self.instance.variant_id
                and cleaned.get('currency') == self.instance.currency
                and cleaned.get('price_basis') == self.instance.price_basis
            )
            if not keeping_baseline and variant and cleaned.get('currency') and cleaned.get('price_basis') == variant.unit:
                self.baseline_observation = PriceObservation.objects.filter(
                    variant=variant,
                    currency=cleaned['currency'],
                    price_basis=cleaned['price_basis'],
                    status=PriceObservation.Status.APPROVED,
                    is_available=True,
                ).filter(
                    valid_until__gt=timezone.now(),
                ).order_by('-observed_at', '-pk').first()
                if not self.baseline_observation:
                    self.add_error(
                        'variant',
                        'برای هشدار درصدی، قیمت تأییدشده و معتبر با همین ارز و واحد باید موجود باشد.',
                    )
        return cleaned
