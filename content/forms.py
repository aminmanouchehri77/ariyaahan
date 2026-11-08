from django import forms

from core.phone import normalize_iran_mobile

from .models import ArticleComment, CompanyRequest, ProductQuestion, ProductReview


class CompanyRequestForm(forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = CompanyRequest
        fields = (
            'name', 'mobile', 'email', 'company_name', 'subject',
            'destination_country', 'product_interest', 'quantity_tonnes', 'delivery_terms',
            'experience_years', 'message', 'consent',
        )
        widgets = {
            'mobile': forms.TextInput(attrs={'autocomplete': 'tel', 'inputmode': 'tel', 'dir': 'ltr', 'placeholder': '۰۹۱۲۳۴۵۶۷۸۹'}),
            'message': forms.Textarea(attrs={'rows': 5, 'maxlength': 5000}),
            'experience_years': forms.NumberInput(attrs={'min': '0', 'max': '60', 'step': '1'}),
            'quantity_tonnes': forms.NumberInput(attrs={'min': '0.001', 'step': '0.001', 'inputmode': 'decimal'}),
        }

    def __init__(self, *args, kind, **kwargs):
        super().__init__(*args, **kwargs)
        self.kind = kind
        if kind in {CompanyRequest.Kind.COMPLAINT, CompanyRequest.Kind.FEEDBACK}:
            for name in ('company_name', 'subject', 'destination_country', 'product_interest',
                         'quantity_tonnes', 'delivery_terms', 'experience_years'):
                self.fields.pop(name)
        elif kind == CompanyRequest.Kind.CAREER:
            for name in ('destination_country', 'product_interest', 'company_name', 'quantity_tonnes', 'delivery_terms'):
                self.fields.pop(name)
            self.fields['subject'].required = True
            self.fields['experience_years'].required = False
        elif kind == CompanyRequest.Kind.EXPORT:
            self.fields.pop('experience_years')
            self.fields['destination_country'].required = True
            self.fields['product_interest'].required = True
            self.fields['quantity_tonnes'].required = True
            self.fields['delivery_terms'].required = True
        self.fields['consent'].required = True
        self.fields['name'].widget.attrs.update({'autocomplete': 'name'})
        self.fields['email'].widget.attrs.update({'autocomplete': 'email', 'dir': 'ltr'})
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean_mobile(self):
        return normalize_iran_mobile(self.cleaned_data['mobile'])

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('website'):
            raise forms.ValidationError('درخواست ثبت نشد.')
        return cleaned

    def save(self, commit=True):
        request = super().save(commit=False)
        request.kind = self.kind
        request.consent = True
        if commit:
            request.save()
        return request


class ProductQuestionForm(forms.ModelForm):
    consent = forms.BooleanField(label='موافقم پرسشم پس از بازبینی، همراه با نام نمایشی منتشر شود.', required=True)
    website = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = ProductQuestion
        fields = ('display_name', 'question')
        widgets = {'question': forms.Textarea(attrs={'rows': 4, 'maxlength': 2000})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['display_name'].required = False
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('website'):
            raise forms.ValidationError('پرسش ثبت نشد.')
        return cleaned


class ProductReviewForm(forms.ModelForm):
    consent = forms.BooleanField(
        label='موافقم دیدگاهم پس از بازبینی با نام نمایشی منتشر شود.', required=True,
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = ProductReview
        fields = ('rating', 'title', 'review')
        widgets = {
            'rating': forms.Select(choices=tuple((value, f'{value} از ۵') for value in range(1, 6))),
            'title': forms.TextInput(attrs={'maxlength': 140}),
            'review': forms.Textarea(attrs={'rows': 5, 'maxlength': 3000}),
        }
        labels = {'rating': 'امتیاز', 'title': 'عنوان (اختیاری)', 'review': 'دیدگاه شما'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('website'):
            raise forms.ValidationError('دیدگاه ثبت نشد.')
        return cleaned


class ArticleCommentForm(forms.ModelForm):
    consent = forms.BooleanField(
        label='موافقم دیدگاهم پس از بازبینی با نام نمایشی منتشر شود.', required=True,
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = ArticleComment
        fields = ('comment',)
        widgets = {'comment': forms.Textarea(attrs={'rows': 4, 'maxlength': 2000})}
        labels = {'comment': 'دیدگاه شما'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('website'):
            raise forms.ValidationError('دیدگاه ثبت نشد.')
        return cleaned
