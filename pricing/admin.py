from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import InventoryLocation, PriceObservation, PriceReviewEvent, StockObservation


@admin.action(description='تأیید قیمت‌های انتخاب‌شده')
def approve_prices(modeladmin, request, queryset):
    changed = 0
    for observation in queryset.filter(status=PriceObservation.Status.PENDING):
        try:
            observation.approve(request.user)
            changed += 1
        except ValidationError as error:
            modeladmin.message_user(request, str(error), level=messages.ERROR)
    modeladmin.message_user(request, f'{changed} ثبت قیمت تأیید شد.')


@admin.action(description='رد قیمت‌های انتخاب‌شده')
def reject_prices(modeladmin, request, queryset):
    changed = 0
    for observation in queryset.filter(status=PriceObservation.Status.PENDING):
        observation.reject(request.user, 'رد از پنل مدیریت')
        changed += 1
    modeladmin.message_user(request, f'{changed} ثبت قیمت رد شد.')


@admin.register(PriceObservation)
class PriceObservationAdmin(admin.ModelAdmin):
    list_display = (
        'variant', 'amount', 'currency', 'price_basis', 'delivery_location',
        'is_available', 'status', 'observed_at', 'valid_until', 'created_by', 'approved_by',
    )
    list_filter = ('status', 'currency', 'price_basis', 'is_available', 'observed_at', 'delivery_location')
    search_fields = ('variant__name', 'variant__product__name', 'source', 'delivery_location')
    date_hierarchy = 'observed_at'
    readonly_fields = ('created_at', 'approved_by', 'approved_at', 'status')
    actions = (approve_prices, reject_prices)
    fields = (
        'variant', 'amount', 'currency', 'unit_label', 'price_basis', 'delivery_location',
        'source', 'is_available', 'tax_included', 'observed_at', 'valid_until', 'created_by',
        'status', 'approved_by', 'approved_at', 'created_at',
    )

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            fields.extend((
                'variant', 'amount', 'currency', 'unit_label', 'price_basis',
                'delivery_location', 'source', 'is_available', 'tax_included',
                'observed_at', 'valid_until', 'created_by',
            ))
        return tuple(fields)


@admin.register(PriceReviewEvent)
class PriceReviewEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'observation', 'action', 'from_status', 'to_status', 'actor')
    list_filter = ('action', 'to_status', 'created_at')
    search_fields = ('observation__variant__product__name', 'note', 'actor__username')
    readonly_fields = ('observation', 'action', 'from_status', 'to_status', 'actor', 'note', 'created_at')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InventoryLocation)
class InventoryLocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'is_active')
    list_filter = ('is_active', 'city')
    search_fields = ('name', 'city', 'address')


@admin.action(description='تأیید موجودی‌های انتخاب‌شده')
def approve_stock(modeladmin, request, queryset):
    changed = 0
    for observation in queryset.filter(status=StockObservation.Status.PENDING):
        observation.approve(request.user)
        changed += 1
    modeladmin.message_user(request, f'{changed} ثبت موجودی تأیید شد.')


@admin.register(StockObservation)
class StockObservationAdmin(admin.ModelAdmin):
    list_display = ('variant', 'location', 'quantity', 'unit', 'is_available', 'status', 'observed_at', 'valid_until')
    list_filter = ('status', 'is_available', 'location', 'observed_at')
    search_fields = ('variant__product__name', 'variant__name', 'location__name', 'source')
    readonly_fields = ('created_at', 'approved_by', 'approved_at', 'status')
    actions = (approve_stock,)
    date_hierarchy = 'observed_at'
