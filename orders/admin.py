from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import ValidationError

from .models import Order, OrderItem, OrderStatusEvent, PaymentRecord, PreInvoice, PreInvoiceItem
from .services import convert_preinvoice_to_order


@admin.action(description='تأیید درخواست‌های انتخاب‌شده برای بررسی نهایی قیمت')
def confirm_preinvoices(modeladmin, request, queryset):
    changed = 0
    for preinvoice in queryset.filter(status__in=(PreInvoice.Status.PENDING, PreInvoice.Status.REVIEW)):
        preinvoice.status = PreInvoice.Status.CONFIRMED
        preinvoice.save(update_fields=('status', 'updated_at'))
        changed += 1
    modeladmin.message_user(request, f'{changed} درخواست برای بررسی نهایی قیمت تأیید شد.')


@admin.action(description='ساخت سفارش از پیش‌فاکتورهای تأییدشده')
def convert_preinvoices(modeladmin, request, queryset):
    created = 0
    returned = 0
    failed = 0
    for preinvoice in queryset:
        try:
            order = convert_preinvoice_to_order(preinvoice.pk, actor=request.user)
        except ValidationError as error:
            failed += 1
            modeladmin.message_user(request, f'پیش‌فاکتور #{preinvoice.pk}: {error}', level=messages.WARNING)
        else:
            if order:
                created += 1
            else:
                returned += 1
    modeladmin.message_user(request, f'{created} سفارش ساخته شد؛ {returned} درخواست به بررسی قیمت برگشت؛ {failed} مورد به‌دلیل وضعیت نامعتبر ساخته نشد.')


class PreInvoiceItemInline(admin.TabularInline):
    model = PreInvoiceItem
    extra = 0
    can_delete = False
    show_change_link = False
    readonly_fields = (
        'variant', 'price_observation',
        'product_name', 'variant_name', 'sku', 'quantity', 'quantity_unit',
        'unit_price', 'currency', 'price_basis', 'price_unit_label', 'line_total',
        'price_is_usable', 'tax_included', 'availability', 'price_location', 'price_observed_at', 'price_valid_until',
        'created_at',
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PreInvoice)
class PreInvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'customer_name', 'mobile', 'delivery_city', 'status')
    list_filter = ('status', 'created_at')
    search_fields = ('customer_name', 'mobile', 'company_name', 'delivery_city')
    readonly_fields = ('public_id', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    ordering = ('status', '-created_at')
    inlines = (PreInvoiceItemInline,)
    actions = (confirm_preinvoices, convert_preinvoices)
    fieldsets = (
        ('مشخصات درخواست', {
            'fields': (
                'public_id', 'customer', 'status', 'customer_name', 'mobile', 'company_name',
                'delivery_city', 'delivery_recipient', 'delivery_mobile', 'delivery_province',
                'delivery_postal_code', 'delivery_address', 'delivery_note', 'customer_note',
            ),
        }),
        ('پیگیری داخلی', {'fields': ('admin_note', 'created_at', 'updated_at')}),
    )


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = tuple(field.name for field in OrderItem._meta.fields if field.name != 'id')

    def has_add_permission(self, request, obj=None):
        return False


def _transition_action(status, label):
    @admin.action(description=label)
    def action(modeladmin, request, queryset):
        changed = 0
        for order in queryset:
            try:
                order.set_status(status, actor=request.user, note='تغییر وضعیت از پنل مدیریت')
            except ValueError:
                continue
            changed += 1
        modeladmin.message_user(request, f'وضعیت {changed} سفارش تغییر کرد؛ گذارهای نامعتبر نادیده گرفته شدند.')
    action.__name__ = f'set_order_{status}'
    return action


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'created_at', 'customer', 'status', 'currency', 'shipping_amount')
    list_filter = ('status', 'currency', 'created_at')
    search_fields = ('public_id', 'customer__mobile', 'preinvoice__customer_name', 'preinvoice__mobile')
    readonly_fields = (
        'public_id', 'preinvoice', 'customer', 'status', 'currency',
        'delivery_recipient', 'delivery_mobile', 'delivery_province', 'delivery_city',
        'delivery_postal_code', 'delivery_address', 'delivery_note', 'customer_note',
        'created_at', 'updated_at',
    )
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    inlines = (OrderItemInline,)
    actions = (
        _transition_action(Order.Status.PROCESSING, 'شروع آماده‌سازی سفارش‌های پرداخت‌شده'),
        _transition_action(Order.Status.SHIPPED, 'ثبت ارسال سفارش‌های آماده'),
        _transition_action(Order.Status.DELIVERED, 'ثبت تحویل سفارش‌های ارسال‌شده'),
        _transition_action(Order.Status.CANCELLED, 'لغو سفارش‌های قابل لغو'),
    )

    def has_add_permission(self, request):
        return False


@admin.register(OrderStatusEvent)
class OrderStatusEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'order', 'from_status', 'to_status', 'actor')
    list_filter = ('to_status', 'created_at')
    search_fields = ('order__public_id', 'order__customer__mobile', 'note', 'actor__username')
    readonly_fields = ('order', 'from_status', 'to_status', 'actor', 'note', 'created_at')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = ('initiated_at', 'order', 'amount', 'currency', 'provider', 'status', 'reference')
    list_filter = ('status', 'provider', 'currency', 'initiated_at')
    search_fields = ('order__public_id', 'reference')
    readonly_fields = tuple(field.name for field in PaymentRecord._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
