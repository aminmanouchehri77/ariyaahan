from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import ValidationError

from .models import Order, OrderItem, OrderStatusEvent, PaymentRecord, PreInvoice, PreInvoiceItem, ProjectList, ProjectListItem
from .payment_services import PaymentStateConflict, reverse_payment, verify_payment
from .sep import SEPError
from .services import convert_preinvoice_to_order, issue_preinvoice_quote


@admin.action(description='صدور پیش‌فاکتورهای انتخاب‌شده برای پذیرش مشتری با کد پیامکی')
def issue_preinvoice_quotes(modeladmin, request, queryset):
    issued = 0
    returned = 0
    failed = 0
    for preinvoice in queryset.filter(status__in=(PreInvoice.Status.PENDING, PreInvoice.Status.REVIEW)):
        try:
            was_issued = issue_preinvoice_quote(preinvoice.pk)
        except ValidationError as error:
            failed += 1
            modeladmin.message_user(request, f'درخواست #{preinvoice.pk}: {error}', level=messages.WARNING)
        else:
            if was_issued:
                issued += 1
            else:
                returned += 1
    modeladmin.message_user(request, f'{issued} پیش‌فاکتور برای پذیرش مشتری صادر شد؛ {returned} مورد به بررسی برگشت؛ {failed} مورد وضعیت قابل صدور نداشت.')


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
        'stock_observation', 'stock_quantity', 'stock_unit', 'stock_is_usable', 'stock_available',
        'stock_location', 'stock_source', 'stock_observed_at', 'stock_valid_until',
        'created_at',
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PreInvoice)
class PreInvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'customer_name', 'mobile', 'delivery_city', 'status')
    list_filter = ('status', 'created_at')
    search_fields = ('customer_name', 'mobile', 'company_name', 'delivery_city')
    readonly_fields = (
        'public_id', 'status', 'quote_issued_at', 'quote_valid_until',
        'customer_accepted_at', 'customer_accepted_mobile', 'acceptance_otp', 'created_at', 'updated_at',
    )
    date_hierarchy = 'created_at'
    ordering = ('status', '-created_at')
    inlines = (PreInvoiceItemInline,)
    actions = (issue_preinvoice_quotes, convert_preinvoices)
    fieldsets = (
        ('مشخصات درخواست', {
            'fields': (
                'public_id', 'customer', 'status', 'customer_name', 'mobile', 'company_name',
                'quote_issued_at', 'quote_valid_until', 'customer_accepted_at', 'customer_accepted_mobile', 'acceptance_otp',
                'delivery_city', 'delivery_recipient', 'delivery_mobile', 'delivery_province',
                'delivery_postal_code', 'delivery_address', 'delivery_note', 'customer_note',
            ),
        }),
        ('پیگیری داخلی', {'fields': ('admin_note', 'created_at', 'updated_at')}),
    )

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.status in (
            PreInvoice.Status.AWAITING_CUSTOMER,
            PreInvoice.Status.CONFIRMED,
            PreInvoice.Status.CONVERTED,
        ):
            fields.extend((
                'customer', 'customer_name', 'mobile', 'company_name', 'delivery_city',
                'delivery_recipient', 'delivery_mobile', 'delivery_province',
                'delivery_postal_code', 'delivery_address', 'delivery_note', 'customer_note',
            ))
        return tuple(dict.fromkeys(fields))


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
    list_display = ('order_label', 'created_at', 'customer', 'status', 'currency', 'shipping_amount')

    @admin.display(description='شمارهٔ سفارش', ordering='pk')
    def order_label(self, obj):
        return obj.order_number
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

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(self.readonly_fields)
        # The gateway amount is derived from shipping + lines. Freeze shipping as
        # soon as the order leaves awaiting_payment or a payment attempt exists.
        if obj is not None and (
            obj.status != Order.Status.AWAITING_PAYMENT
            or obj.payments.exclude(status__in=(PaymentRecord.Status.FAILED, PaymentRecord.Status.CANCELLED)).exists()
        ):
            fields += ('shipping_amount',)
        return fields
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


@admin.action(description='استعلام دوبارهٔ تراکنش از سپ (Verify) — حداکثر تا ۳۰ دقیقه پس از پرداخت')
def reverify_payments(modeladmin, request, queryset):
    done = 0
    for payment in queryset.filter(provider='sep', status=PaymentRecord.Status.REQUIRES_REVIEW).exclude(ref_num=None):
        try:
            result = verify_payment(payment.pk)
        except SEPError as error:
            modeladmin.message_user(request, f'تراکنش #{payment.pk}: {error}', level=messages.WARNING)
            continue
        done += 1
        modeladmin.message_user(request, f'تراکنش #{payment.pk}: {result.get_status_display()}')
    if not done:
        modeladmin.message_user(request, 'تراکنش «نیازمند بررسی» دارای RefNum انتخاب نشده بود.', level=messages.WARNING)


@admin.action(description='برگشت وجه (Reverse) تراکنش‌های تأییدنشده در سفارش')
def reverse_payments(modeladmin, request, queryset):
    for payment in queryset.filter(provider='sep').exclude(ref_num=None):
        try:
            result = reverse_payment(payment.pk, reason=f'Reversed by {request.user.get_username()}.')
        except (PaymentStateConflict, SEPError) as error:
            modeladmin.message_user(request, f'تراکنش #{payment.pk}: {error}', level=messages.WARNING)
        else:
            modeladmin.message_user(request, f'تراکنش #{payment.pk}: {result.get_status_display()}')


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = ('initiated_at', 'order', 'amount', 'currency', 'amount_rial', 'provider', 'status', 'ref_num', 'trace_no', 'verified_at')
    list_filter = ('status', 'provider', 'currency', 'initiated_at')
    search_fields = ('order__public_id', 'reference', 'ref_num', 'trace_no', 'rrn', 'idempotency_key')
    readonly_fields = tuple(field.name for field in PaymentRecord._meta.fields)
    actions = (reverify_payments, reverse_payments)

    def has_change_permission(self, request, obj=None):
        # Read-only detail view; actions use the change permission on the list.
        return obj is None and super().has_change_permission(request, obj)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ProjectListItemInline(admin.TabularInline):
    model = ProjectListItem
    extra = 0
    raw_id_fields = ('variant',)


@admin.register(ProjectList)
class ProjectListAdmin(admin.ModelAdmin):
    list_display = ('title', 'profile', 'is_shared', 'updated_at')
    search_fields = ('title', 'profile__mobile')
    readonly_fields = ('public_id', 'created_at', 'updated_at')
    inlines = (ProjectListItemInline,)
