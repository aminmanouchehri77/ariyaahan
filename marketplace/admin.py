from django.contrib import admin
from django.utils import timezone

from .models import MarketplaceListing


@admin.register(MarketplaceListing)
class MarketplaceListingAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'kind', 'product_label', 'quantity', 'quantity_unit', 'city',
        'status', 'created_at', 'expires_at',
    )
    list_filter = ('kind', 'status', 'currency', 'created_at', 'expires_at')
    search_fields = ('product_label', 'city', 'contact_name', 'mobile', 'company_name')
    readonly_fields = ('created_at', 'updated_at', 'reviewed_by', 'reviewed_at')
    date_hierarchy = 'created_at'
    ordering = ('status', '-created_at')
    list_per_page = 30
    fieldsets = (
        ('اطلاعات آگهی', {
            'fields': (
                'kind', 'status', 'product_variant', 'product_label', 'quantity',
                'quantity_unit', 'price_amount', 'currency', 'city', 'details', 'expires_at',
            ),
        }),
        ('اطلاعات خصوصی ثبت‌کننده', {
            'fields': ('contact_name', 'mobile', 'company_name', 'show_company_name', 'contact_consent'),
        }),
        ('بررسی مدیر', {'fields': ('admin_note', 'reviewed_by', 'reviewed_at', 'created_at', 'updated_at')}),
    )

    def save_model(self, request, obj, form, change):
        if obj.status != MarketplaceListing.Status.PENDING and obj.reviewed_at is None:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)
