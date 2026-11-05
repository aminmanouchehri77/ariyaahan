import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.urls import reverse


def _notify_customer_status(profile_id, title, body):
    if not profile_id:
        return

    target_url = reverse('accounts:orders')

    def create_notification():
        from accounts.models import CustomerNotification

        CustomerNotification.objects.create(
            profile_id=profile_id,
            kind=CustomerNotification.Kind.ORDER,
            title=title,
            body=body[:500],
            target_url=target_url,
        )

    transaction.on_commit(create_notification)


UNIT_CHOICES = (
    ('kg', 'کیلوگرم'),
    ('ton', 'تن'),
    ('piece', 'شاخه / عدد'),
    ('bundle', 'بندیل'),
    ('sheet', 'شیت'),
    ('meter', 'متر'),
)
CURRENCY_CHOICES = (
    ('IRR', 'ریال'),
    ('IRT', 'تومان'),
    ('USD', 'دلار آمریکا'),
)


class PreInvoice(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار بررسی قیمت و موجودی'
        REVIEW = 'review', 'نیازمند بررسی قیمت/واحد/موجودی'
        AWAITING_CUSTOMER = 'awaiting_customer', 'پیش‌فاکتور صادرشده؛ در انتظار پذیرش مشتری'
        CONFIRMED = 'confirmed', 'تأیید شده'
        CONVERTED = 'converted', 'تبدیل به سفارش'
        CANCELLED = 'cancelled', 'لغو شده'

    public_id = models.UUIDField('شناسهٔ امن', default=uuid.uuid4, unique=True, editable=False)
    customer = models.ForeignKey(
        'accounts.CustomerProfile', verbose_name='حساب مشتری', related_name='preinvoices',
        null=True, blank=True, on_delete=models.SET_NULL,
    )
    customer_name = models.CharField('نام و نام خانوادگی', max_length=120)
    mobile = models.CharField(
        'شمارهٔ همراه',
        max_length=11,
        validators=[RegexValidator(r'^09\d{9}$', 'شمارهٔ همراه باید با ۰۹ شروع شود و ۱۱ رقم باشد.')],
    )
    company_name = models.CharField('نام شرکت', max_length=160, blank=True)
    delivery_city = models.CharField('شهر مقصد', max_length=100, blank=True)
    delivery_recipient = models.CharField('تحویل‌گیرنده', max_length=120, blank=True)
    delivery_mobile = models.CharField('شمارهٔ تحویل‌گیرنده', max_length=11, blank=True)
    delivery_province = models.CharField('استان تحویل', max_length=100, blank=True)
    delivery_postal_code = models.CharField('کدپستی تحویل', max_length=10, blank=True)
    delivery_address = models.TextField('نشانی تحویل', blank=True)
    delivery_note = models.CharField('توضیح تحویل', max_length=300, blank=True)
    customer_note = models.TextField('توضیح خریدار', blank=True)
    status = models.CharField('وضعیت', max_length=24, choices=Status.choices, default=Status.PENDING)
    quote_issued_at = models.DateTimeField('زمان صدور پیش‌فاکتور', null=True, blank=True)
    quote_valid_until = models.DateTimeField('اعتبار پیش‌فاکتور تا', null=True, blank=True)
    customer_accepted_at = models.DateTimeField('زمان پذیرش مشتری', null=True, blank=True)
    customer_accepted_mobile = models.CharField('شمارهٔ همراه پذیرش‌کننده', max_length=11, blank=True)
    acceptance_otp = models.ForeignKey(
        'accounts.OTPChallenge', verbose_name='کد تأیید پذیرش', null=True, blank=True,
        related_name='accepted_preinvoices', on_delete=models.SET_NULL,
    )
    admin_note = models.TextField('یادداشت داخلی', blank=True)
    created_at = models.DateTimeField('زمان ثبت', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'درخواست پیش‌فاکتور'
        verbose_name_plural = 'درخواست‌های پیش‌فاکتور'
        ordering = ('-created_at', '-pk')
        indexes = [
            models.Index(fields=('status', 'created_at'), name='preinv_status_date_idx'),
        ]

    def __str__(self):
        return f'پیش‌فاکتور #{self.pk or "جدید"} — {self.customer_name}'

    def save(self, *args, **kwargs):
        status_persisted = kwargs.get('update_fields') is None or 'status' in kwargs['update_fields']
        previous_status = None
        if self.pk:
            previous_status = type(self).objects.filter(pk=self.pk).values_list('status', flat=True).first()
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if status_persisted and (is_new or previous_status != self.status):
            title = 'درخواست پیش‌فاکتور ثبت شد' if is_new else 'وضعیت پیش‌فاکتور تغییر کرد'
            _notify_customer_status(self.customer_id, title, self.get_status_display())


class PreInvoiceItem(models.Model):
    preinvoice = models.ForeignKey(
        PreInvoice,
        verbose_name='درخواست پیش‌فاکتور',
        related_name='items',
        on_delete=models.CASCADE,
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant',
        verbose_name='گونهٔ محصول',
        related_name='preinvoice_items',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    price_observation = models.ForeignKey(
        'pricing.PriceObservation',
        verbose_name='رکورد قیمت مبنا',
        related_name='preinvoice_items',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    product_name = models.CharField('نام محصول هنگام ثبت', max_length=180)
    variant_name = models.CharField('نام گونه هنگام ثبت', max_length=180)
    sku = models.CharField('کد کالا هنگام ثبت', max_length=80, blank=True)
    quantity = models.DecimalField(
        'مقدار درخواستی',
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
    )
    quantity_unit = models.CharField('واحد مقدار', max_length=12, choices=UNIT_CHOICES)
    unit_price = models.DecimalField('آخرین مبلغ ثبت‌شده', max_digits=18, decimal_places=0, null=True, blank=True)
    currency = models.CharField('ارز', max_length=3, choices=CURRENCY_CHOICES, blank=True)
    price_basis = models.CharField('واحد محاسباتی قیمت', max_length=12, choices=UNIT_CHOICES, blank=True)
    price_unit_label = models.CharField('شرح مبنای قیمت', max_length=40, blank=True)
    line_total = models.DecimalField('برآورد ردیف', max_digits=24, decimal_places=0, null=True, blank=True)
    price_is_usable = models.BooleanField('قابل محاسبه با قیمت معتبر', default=False)
    tax_included = models.BooleanField('مالیات در قیمت ثبت‌شده لحاظ شده', null=True, blank=True)
    availability = models.BooleanField('موجودی هنگام ثبت', null=True, blank=True)
    price_location = models.CharField('محل تحویل قیمت', max_length=140, blank=True)
    price_observed_at = models.DateTimeField('زمان مشاهدهٔ قیمت', null=True, blank=True)
    price_valid_until = models.DateTimeField('اعتبار قیمت تا', null=True, blank=True)
    stock_observation = models.ForeignKey(
        'pricing.StockObservation', verbose_name='ثبت موجودی مبنا', null=True, blank=True,
        related_name='preinvoice_items', on_delete=models.SET_NULL,
    )
    stock_quantity = models.DecimalField('موجودی هنگام ثبت', max_digits=14, decimal_places=3, null=True, blank=True)
    stock_unit = models.CharField('واحد موجودی', max_length=12, blank=True)
    stock_is_usable = models.BooleanField('موجودی برای مقدار درخواستی کافی و معتبر است', default=False)
    stock_available = models.BooleanField('موجودی هنگام ثبت قابل سفارش بود', null=True, blank=True)
    stock_location = models.CharField('محل موجودی هنگام ثبت', max_length=140, blank=True)
    stock_source = models.CharField('منبع ثبت موجودی', max_length=160, blank=True)
    stock_observed_at = models.DateTimeField('زمان ثبت موجودی', null=True, blank=True)
    stock_valid_until = models.DateTimeField('اعتبار موجودی تا', null=True, blank=True)
    created_at = models.DateTimeField('زمان ثبت ردیف', auto_now_add=True)

    class Meta:
        verbose_name = 'ردیف پیش‌فاکتور'
        verbose_name_plural = 'ردیف‌های پیش‌فاکتور'
        ordering = ('pk',)

    def __str__(self):
        return f'{self.product_name} — {self.quantity} {self.get_quantity_unit_display()}'


class Order(models.Model):
    class Status(models.TextChoices):
        AWAITING_PAYMENT = 'awaiting_payment', 'در انتظار پرداخت'
        PAID = 'paid', 'پرداخت‌شده'
        PROCESSING = 'processing', 'در حال آماده‌سازی'
        SHIPPED = 'shipped', 'ارسال‌شده'
        DELIVERED = 'delivered', 'تحویل‌شده'
        CANCELLED = 'cancelled', 'لغوشده'
        REFUNDED = 'refunded', 'مستردشده'

    public_id = models.UUIDField('شناسهٔ امن سفارش', default=uuid.uuid4, unique=True, editable=False)
    preinvoice = models.OneToOneField(
        PreInvoice, verbose_name='درخواست مبدأ', related_name='order', on_delete=models.PROTECT,
    )
    customer = models.ForeignKey(
        'accounts.CustomerProfile', verbose_name='حساب مشتری', related_name='orders',
        null=True, blank=True, on_delete=models.SET_NULL,
    )
    status = models.CharField('وضعیت سفارش', max_length=20, choices=Status.choices, default=Status.AWAITING_PAYMENT, db_index=True)
    currency = models.CharField('ارز سفارش', max_length=3, choices=CURRENCY_CHOICES, blank=True)
    shipping_amount = models.DecimalField('هزینهٔ حمل تأییدشده', max_digits=18, decimal_places=0, null=True, blank=True)
    delivery_recipient = models.CharField('تحویل‌گیرنده', max_length=120, blank=True)
    delivery_mobile = models.CharField('شمارهٔ تحویل‌گیرنده', max_length=11, blank=True)
    delivery_province = models.CharField('استان تحویل', max_length=100, blank=True)
    delivery_city = models.CharField('شهر تحویل', max_length=100, blank=True)
    delivery_postal_code = models.CharField('کدپستی تحویل', max_length=10, blank=True)
    delivery_address = models.TextField('نشانی تحویل', blank=True)
    delivery_note = models.CharField('توضیح تحویل', max_length=300, blank=True)
    customer_note = models.TextField('توضیح مشتری', blank=True)
    created_at = models.DateTimeField('زمان ایجاد', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'سفارش'
        verbose_name_plural = 'سفارش‌ها'
        ordering = ('-created_at', '-pk')
        indexes = [models.Index(fields=('customer', 'status', 'created_at'), name='order_customer_status_idx')]

    @property
    def order_number(self):
        return f'ARIA-{self.pk:08d}' if self.pk else 'جدید'

    def __str__(self):
        return f'{self.order_number} — {self.get_status_display()}'

    def save(self, *args, **kwargs):
        status_persisted = kwargs.get('update_fields') is None or 'status' in kwargs['update_fields']
        previous_status = None
        if self.pk:
            previous_status = type(self).objects.filter(pk=self.pk).values_list('status', flat=True).first()
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and status_persisted:
            OrderStatusEvent.objects.create(
                order=self, from_status='', to_status=self.status,
                actor=getattr(self, '_status_actor', None), note='ساخته‌شده از پیش‌فاکتور تأییدشده',
            )
        elif status_persisted and previous_status != self.status:
            OrderStatusEvent.objects.create(
                order=self, from_status=previous_status or '', to_status=self.status,
                actor=getattr(self, '_status_actor', None), note=getattr(self, '_status_note', ''),
            )

        if status_persisted and (is_new or previous_status != self.status):
            title = 'سفارش شما ثبت شد' if is_new else 'وضعیت سفارش تغییر کرد'
            _notify_customer_status(self.customer_id, title, self.get_status_display())

    @transaction.atomic
    def set_status(self, status, actor=None, note=''):
        if not self.pk:
            raise ValueError('برای تغییر وضعیت، سفارش باید ابتدا ذخیره شده باشد.')

        order = type(self).objects.select_for_update().get(pk=self.pk)
        transitions = {
            order.Status.AWAITING_PAYMENT: {order.Status.PAID, order.Status.CANCELLED},
            order.Status.PAID: {order.Status.PROCESSING, order.Status.CANCELLED, order.Status.REFUNDED},
            order.Status.PROCESSING: {order.Status.SHIPPED, order.Status.CANCELLED, order.Status.REFUNDED},
            order.Status.SHIPPED: {order.Status.DELIVERED, order.Status.REFUNDED},
            order.Status.DELIVERED: {order.Status.REFUNDED},
            order.Status.CANCELLED: set(),
            order.Status.REFUNDED: set(),
        }
        if status != order.status and status not in transitions.get(order.status, set()):
            raise ValueError('تغییر وضعیت انتخاب‌شده مجاز نیست.')
        order.status = status
        order._status_actor = actor
        order._status_note = note[:500]
        order.save(update_fields=('status', 'updated_at'))
        self.status = order.status
        self.updated_at = order.updated_at


class OrderItem(models.Model):
    order = models.ForeignKey(Order, verbose_name='سفارش', related_name='items', on_delete=models.CASCADE)
    variant = models.ForeignKey(
        'catalog.ProductVariant', verbose_name='گونهٔ جاری', null=True, blank=True,
        on_delete=models.SET_NULL,
    )
    product_name = models.CharField('نام محصول هنگام سفارش', max_length=180)
    variant_name = models.CharField('نام گونه هنگام سفارش', max_length=180)
    sku = models.CharField('کد کالا', max_length=80, blank=True)
    quantity = models.DecimalField('مقدار', max_digits=12, decimal_places=3)
    quantity_unit = models.CharField('واحد مقدار', max_length=12, choices=UNIT_CHOICES)
    unit_price = models.DecimalField('قیمت واحد', max_digits=18, decimal_places=0)
    currency = models.CharField('ارز', max_length=3, choices=CURRENCY_CHOICES)
    price_basis = models.CharField('مبنای قیمت', max_length=12, choices=UNIT_CHOICES)
    price_unit_label = models.CharField('شرح مبنای قیمت', max_length=40, blank=True)
    line_total = models.DecimalField('جمع ردیف', max_digits=24, decimal_places=0)
    tax_included = models.BooleanField('مالیات در مبلغ لحاظ شده', null=True, blank=True)
    created_at = models.DateTimeField('زمان ثبت ردیف', auto_now_add=True)

    class Meta:
        verbose_name = 'ردیف سفارش'
        verbose_name_plural = 'ردیف‌های سفارش'
        ordering = ('pk',)

    def __str__(self):
        return f'{self.product_name} — {self.quantity} {self.get_quantity_unit_display()}'


class OrderStatusEvent(models.Model):
    order = models.ForeignKey(Order, verbose_name='سفارش', related_name='status_events', on_delete=models.PROTECT)
    from_status = models.CharField('وضعیت پیشین', max_length=20, blank=True)
    to_status = models.CharField('وضعیت جدید', max_length=20, choices=Order.Status.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='تغییردهنده', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='order_status_events',
    )
    note = models.CharField('یادداشت', max_length=500, blank=True)
    created_at = models.DateTimeField('زمان تغییر', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'رویداد وضعیت سفارش'
        verbose_name_plural = 'رویدادهای وضعیت سفارش'
        ordering = ('-created_at', '-pk')

    def __str__(self):
        return f'{self.order.order_number} — {self.get_to_status_display()}'


class PaymentRecord(models.Model):
    class Status(models.TextChoices):
        INITIATED = 'initiated', 'شروع‌شده'
        SUCCEEDED = 'succeeded', 'موفق'
        FAILED = 'failed', 'ناموفق'
        REFUNDED = 'refunded', 'مستردشده'

    order = models.ForeignKey(Order, verbose_name='سفارش', related_name='payments', on_delete=models.PROTECT)
    amount = models.DecimalField('مبلغ', max_digits=18, decimal_places=0, validators=[MinValueValidator(1)])
    currency = models.CharField('ارز', max_length=3, choices=CURRENCY_CHOICES)
    provider = models.CharField('درگاه', max_length=40, blank=True)
    status = models.CharField('وضعیت پرداخت', max_length=12, choices=Status.choices, default=Status.INITIATED)
    reference = models.CharField('شناسهٔ پیگیری درگاه', max_length=120, blank=True)
    idempotency_key = models.UUIDField('کلید یکتای درخواست', default=uuid.uuid4, unique=True, editable=False)
    initiated_at = models.DateTimeField('زمان شروع', auto_now_add=True)
    completed_at = models.DateTimeField('زمان تکمیل', null=True, blank=True)

    class Meta:
        verbose_name = 'تراکنش پرداخت'
        verbose_name_plural = 'تراکنش‌های پرداخت'
        ordering = ('-initiated_at', '-pk')

    def __str__(self):
        return f'{self.order.order_number} — {self.amount} {self.currency} — {self.get_status_display()}'
