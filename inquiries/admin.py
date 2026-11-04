from django.contrib import admin

from .models import Inquiry


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'kind', 'customer_name', 'mobile', 'product_label',
        'requested_quantity', 'quantity_unit', 'status',
    )
    list_filter = ('kind', 'status', 'created_at')
    search_fields = ('customer_name', 'mobile', 'product_label', 'message')
    readonly_fields = ('created_at', 'updated_at', 'product_label', 'source_path')
    list_per_page = 30
    date_hierarchy = 'created_at'
    ordering = ('status', '-created_at')
    fieldsets = (
        ('درخواست مشتری', {
            'fields': ('kind', 'status', 'product_variant', 'product_label', 'requested_quantity', 'quantity_unit', 'message'),
        }),
        ('راه ارتباطی', {'fields': ('customer_name', 'mobile')}),
        ('پیگیری داخلی', {'fields': ('admin_note', 'source_path', 'created_at', 'updated_at')}),
    )
