from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    InventoryLocation, PriceObservation, PriceObservationTask, PriceReviewEvent,
    ShippingRate, StockObservation,
)


@admin.action(description='تأیید قیمت‌های انتخاب‌شده', permissions=('change',))
def approve_prices(modeladmin, request, queryset):
    changed = 0
    for observation in queryset.filter(status=PriceObservation.Status.PENDING):
        try:
            observation.approve(request.user)
            changed += 1
        except ValidationError as error:
            modeladmin.message_user(request, str(error), level=messages.ERROR)
    modeladmin.message_user(request, f'{changed} ثبت قیمت تأیید شد.')


@admin.action(description='رد قیمت‌های انتخاب‌شده', permissions=('change',))
def reject_prices(modeladmin, request, queryset):
    changed = 0
    for observation in queryset.filter(status=PriceObservation.Status.PENDING):
        try:
            observation.reject(request.user, 'رد از پنل مدیریت')
            changed += 1
        except ValidationError as error:
            modeladmin.message_user(request, str(error), level=messages.ERROR)
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


@admin.action(description='بازگرداندن کارهای ناموفق به صف پردازش', permissions=('change',))
def retry_price_tasks(modeladmin, request, queryset):
    retried = queryset.filter(status=PriceObservationTask.Status.FAILED).update(
        status=PriceObservationTask.Status.PENDING,
        attempts=0,
        available_at=timezone.now(),
        completed_at=None,
        last_error='',
    )
    modeladmin.message_user(request, f'{retried} کار دوباره در صف قرار گرفت.')


@admin.register(PriceObservationTask)
class PriceObservationTaskAdmin(admin.ModelAdmin):
    list_display = ('observation', 'status', 'attempts', 'available_at', 'completed_at', 'last_error')
    list_filter = ('status', 'available_at', 'completed_at')
    search_fields = ('observation__variant__product__name', 'observation__variant__name', 'last_error')
    readonly_fields = tuple(field.name for field in PriceObservationTask._meta.fields)
    actions = (retry_price_tasks,)
    ordering = ('status', 'available_at', 'pk')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InventoryLocation)
class InventoryLocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'is_active')
    list_filter = ('is_active', 'city')
    search_fields = ('name', 'city', 'address')


@admin.action(description='تأیید موجودی‌های انتخاب‌شده', permissions=('change',))
def approve_stock(modeladmin, request, queryset):
    changed = 0
    for observation in queryset.filter(status=StockObservation.Status.PENDING):
        try:
            observation.approve(request.user)
            changed += 1
        except ValidationError as error:
            modeladmin.message_user(request, str(error), level=messages.ERROR)
    modeladmin.message_user(request, f'{changed} ثبت موجودی تأیید شد.')


@admin.action(description='رد موجودی‌های انتخاب‌شده', permissions=('change',))
def reject_stock(modeladmin, request, queryset):
    changed = 0
    for observation in queryset.filter(status=StockObservation.Status.PENDING):
        try:
            observation.reject(request.user)
            changed += 1
        except ValidationError as error:
            modeladmin.message_user(request, str(error), level=messages.ERROR)
    modeladmin.message_user(request, f'{changed} ثبت موجودی رد شد.')


@admin.register(StockObservation)
class StockObservationAdmin(admin.ModelAdmin):
    list_display = ('variant', 'location', 'quantity', 'unit', 'is_available', 'status', 'observed_at', 'valid_until')
    list_filter = ('status', 'is_available', 'location', 'observed_at')
    search_fields = ('variant__product__name', 'variant__name', 'location__name', 'source')
    readonly_fields = ('created_at', 'approved_by', 'approved_at', 'status')
    actions = (approve_stock, reject_stock)
    date_hierarchy = 'observed_at'

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj:
            fields.extend((
                'variant', 'location', 'quantity', 'unit', 'is_available',
                'source', 'observed_at', 'valid_until',
            ))
        return tuple(fields)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ShippingRate)
class ShippingRateAdmin(admin.ModelAdmin):
    list_display = (
        'origin_city', 'destination_city', 'method', 'minimum_tonnes', 'maximum_tonnes',
        'base_fee', 'per_tonne', 'currency', 'valid_until', 'is_active',
    )
    list_filter = ('is_active', 'method', 'currency', 'origin_city', 'destination_city', 'valid_until')
    search_fields = ('origin_city', 'destination_city', 'source')
    ordering = ('origin_city', 'destination_city', 'minimum_tonnes')
