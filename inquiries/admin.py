from django.contrib import admin
from django.urls import reverse

from accounts.models import CustomerNotification

from .models import CompanyContactDetails, Inquiry


@admin.register(CompanyContactDetails)
class CompanyContactDetailsAdmin(admin.ModelAdmin):
    fieldsets = (
        ('اطلاعات عمومی', {'fields': ('public_name', 'phone', 'alternate_phone', 'email')}),
        ('نشانی و پاسخ‌گویی', {'fields': ('address', 'office_hours', 'map_url')}),
        ('شبکه‌های اجتماعی', {'fields': ('whatsapp_url', 'telegram_url', 'instagram_url', 'linkedin_url')}),
    )
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        return not CompanyContactDetails.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'kind', 'customer_name', 'mobile', 'product_label',
        'requested_quantity', 'quantity_unit', 'status',
    )
    list_filter = ('kind', 'status', 'created_at')
    search_fields = ('customer_name', 'mobile', 'product_label', 'message')
    readonly_fields = ('public_id', 'profile', 'created_at', 'updated_at', 'product_label', 'source_path')
    list_per_page = 30
    date_hierarchy = 'created_at'
    ordering = ('status', '-created_at')

    def save_model(self, request, obj, form, change):
        old_status = type(obj).objects.filter(pk=obj.pk).values_list('status', flat=True).first() if change else None
        super().save_model(request, obj, form, change)
        if change and old_status != obj.status and obj.profile_id:
            CustomerNotification.objects.create(
                profile=obj.profile,
                kind=CustomerNotification.Kind.SYSTEM,
                title='وضعیت درخواست شما تغییر کرد',
                body=f'{obj.get_kind_display()}: {obj.get_status_display()}',
                target_url=reverse('inquiries:status', kwargs={'public_id': obj.public_id}),
            )

    fieldsets = (
        ('درخواست مشتری', {
            'fields': ('public_id', 'profile', 'kind', 'status', 'product_variant', 'product_label', 'requested_quantity', 'quantity_unit', 'message'),
        }),
        ('راه ارتباطی', {'fields': ('customer_name', 'mobile')}),
        ('پیگیری داخلی', {'fields': ('admin_note', 'source_path', 'created_at', 'updated_at')}),
    )
