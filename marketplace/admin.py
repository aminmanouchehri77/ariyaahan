from django.contrib import admin
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomerNotification
from .models import MarketplaceListing


@admin.register(MarketplaceListing)
class MarketplaceListingAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'kind', 'product_label', 'quantity', 'quantity_unit', 'city',
        'status', 'created_at', 'expires_at',
    )
    list_filter = ('kind', 'status', 'currency', 'created_at', 'expires_at')
    search_fields = ('product_label', 'city', 'contact_name', 'mobile', 'company_name')
    readonly_fields = ('public_id', 'profile', 'created_at', 'updated_at', 'reviewed_by', 'reviewed_at')
    date_hierarchy = 'created_at'
    ordering = ('status', '-created_at')
    list_per_page = 30
    fieldsets = (
        ('اطلاعات آگهی', {
            'fields': (
                'public_id', 'profile', 'kind', 'status', 'product_variant', 'product_label', 'quantity',
                'quantity_unit', 'price_amount', 'currency', 'city', 'details', 'expires_at',
            ),
        }),
        ('اطلاعات خصوصی ثبت‌کننده', {
            'fields': ('contact_name', 'mobile', 'company_name', 'show_company_name', 'contact_consent'),
        }),
        ('بررسی مدیر', {'fields': ('admin_note', 'reviewed_by', 'reviewed_at', 'created_at', 'updated_at')}),
    )

    def save_model(self, request, obj, form, change):
        old_status = type(obj).objects.filter(pk=obj.pk).values_list('status', flat=True).first() if change else None
        if change and old_status != obj.status:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)
        if change and old_status != obj.status and obj.profile_id:
            CustomerNotification.objects.create(
                profile=obj.profile,
                kind=CustomerNotification.Kind.SYSTEM,
                title='وضعیت آگهی شما تغییر کرد',
                body=f'{obj.get_kind_display()}: {obj.get_status_display()}',
                target_url=reverse('marketplace:listing_status', kwargs={'public_id': obj.public_id}),
            )
