from django.conf import settings
from decimal import Decimal
from hashlib import sha256

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.utils import timezone


class CustomerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='customer_profile',
        verbose_name='حساب کاربری',
    )
    mobile = models.CharField('شمارهٔ همراه تأییدشده', max_length=11, unique=True)
    full_name = models.CharField('نام و نام خانوادگی', max_length=120, blank=True)
    allow_price_notifications = models.BooleanField('اجازهٔ اعلان قیمت', default=False)
    created_at = models.DateTimeField('زمان ایجاد', auto_now_add=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'پروفایل مشتری'
        verbose_name_plural = 'پروفایل مشتریان'
        ordering = ('-created_at',)

    def __str__(self):
        return self.full_name or self.mobile


class CustomerAddress(models.Model):
    profile = models.ForeignKey(
        CustomerProfile, verbose_name='پروفایل مشتری', related_name='addresses', on_delete=models.CASCADE,
    )
    title = models.CharField('عنوان نشانی', max_length=60, default='نشانی اصلی')
    recipient = models.CharField('تحویل‌گیرنده', max_length=120)
    mobile = models.CharField(
        'شمارهٔ همراه تحویل‌گیرنده', max_length=11,
        validators=[RegexValidator(r'^09\d{9}$', 'شمارهٔ همراه باید با ۰۹ شروع شود و ۱۱ رقم باشد.')],
    )
    province = models.CharField('استان', max_length=100)
    city = models.CharField('شهر', max_length=100)
    postal_code = models.CharField(
        'کدپستی', max_length=10, blank=True,
        validators=[RegexValidator(r'^\d{10}$', 'کدپستی باید ۱۰ رقم باشد.')],
    )
    address = models.TextField('نشانی کامل', max_length=700)
    delivery_note = models.CharField('توضیح تحویل', max_length=300, blank=True)
    is_default = models.BooleanField('نشانی پیش‌فرض', default=False)
    created_at = models.DateTimeField('زمان ایجاد', auto_now_add=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'نشانی مشتری'
        verbose_name_plural = 'نشانی‌های مشتریان'
        ordering = ('-is_default', '-updated_at')
        constraints = []

    def save(self, *args, **kwargs):
        if self.is_default:
            with transaction.atomic():
                CustomerProfile.objects.select_for_update().get(pk=self.profile_id)
                CustomerAddress.objects.filter(profile_id=self.profile_id, is_default=True).exclude(pk=self.pk).update(is_default=False)
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.title} — {self.city} — {self.recipient}'


class PriceAlert(models.Model):
    class Direction(models.TextChoices):
        BELOW = 'below', 'وقتی قیمت به این مبلغ یا کمتر رسید'
        ABOVE = 'above', 'وقتی قیمت به این مبلغ یا بیشتر رسید'

    CURRENCY_CHOICES = (('IRR', 'ریال'), ('IRT', 'تومان'), ('USD', 'دلار آمریکا'))
    BASIS_CHOICES = (('kg', 'کیلوگرم'), ('ton', 'تن'), ('piece', 'شاخه / عدد'), ('bundle', 'بندیل'), ('sheet', 'شیت'), ('meter', 'متر'))

    profile = models.ForeignKey(
        CustomerProfile, verbose_name='مشتری', related_name='price_alerts', on_delete=models.CASCADE,
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant', verbose_name='گونهٔ محصول', related_name='price_alerts', on_delete=models.CASCADE,
    )
    direction = models.CharField('شرط اعلان', max_length=8, choices=Direction.choices)
    target_amount = models.DecimalField(
        'مبلغ هدف', max_digits=18, decimal_places=0, validators=[MinValueValidator(Decimal('1'))],
    )
    currency = models.CharField('ارز', max_length=3, choices=CURRENCY_CHOICES, default='IRT')
    price_basis = models.CharField('مبنای قیمت', max_length=12, choices=BASIS_CHOICES)
    is_active = models.BooleanField('فعال', default=True)
    last_notified_at = models.DateTimeField('آخرین اعلان', null=True, blank=True)
    created_at = models.DateTimeField('زمان ایجاد', auto_now_add=True)

    class Meta:
        verbose_name = 'هشدار قیمت'
        verbose_name_plural = 'هشدارهای قیمت'
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(
                fields=('profile', 'variant', 'direction', 'target_amount', 'currency', 'price_basis'),
                name='unique_customer_price_alert',
            ),
        ]
        indexes = [models.Index(fields=('variant', 'is_active'), name='alert_variant_active_idx')]

    def __str__(self):
        return f'{self.profile} — {self.variant} — {self.get_direction_display()}'


class CustomerNotification(models.Model):
    class Kind(models.TextChoices):
        PRICE = 'price', 'اعلان قیمت'
        ORDER = 'order', 'تغییر سفارش'
        SYSTEM = 'system', 'پیام سامانه'

    profile = models.ForeignKey(
        CustomerProfile, verbose_name='مشتری', related_name='notifications', on_delete=models.CASCADE,
    )
    kind = models.CharField('نوع', max_length=12, choices=Kind.choices, default=Kind.SYSTEM)
    title = models.CharField('عنوان', max_length=160)
    body = models.CharField('متن', max_length=500)
    target_url = models.CharField('نشانی مقصد', max_length=300, blank=True)
    price_alert = models.ForeignKey(PriceAlert, null=True, blank=True, on_delete=models.SET_NULL, related_name='notifications')
    price_observation = models.ForeignKey(
        'pricing.PriceObservation', null=True, blank=True, on_delete=models.SET_NULL, related_name='customer_notifications',
    )
    is_read = models.BooleanField('خوانده شده', default=False, db_index=True)
    created_at = models.DateTimeField('زمان ایجاد', default=timezone.now, db_index=True)

    class Meta:
        verbose_name = 'اعلان مشتری'
        verbose_name_plural = 'اعلان‌های مشتریان'
        ordering = ('-created_at', '-pk')
        constraints = [
            models.UniqueConstraint(
                fields=('price_alert', 'price_observation'),
                name='unique_price_notification_event',
            ),
        ]

    def __str__(self):
        return f'{self.title} — {self.profile}'


class PushSubscription(models.Model):
    profile = models.ForeignKey(
        CustomerProfile, verbose_name='مشتری', related_name='push_subscriptions', on_delete=models.CASCADE,
    )
    endpoint = models.URLField('نشانی پوش', max_length=2048)
    endpoint_hash = models.CharField('هش نشانی پوش', max_length=64, unique=True, editable=False)
    p256dh = models.CharField('کلید عمومی مرورگر', max_length=200)
    auth = models.CharField('کلید احراز', max_length=100)
    created_at = models.DateTimeField('زمان ثبت', auto_now_add=True)
    updated_at = models.DateTimeField('آخرین به‌روزرسانی', auto_now=True)

    class Meta:
        verbose_name = 'اشتراک اعلان مرورگر'
        verbose_name_plural = 'اشتراک‌های اعلان مرورگر'

    def save(self, *args, **kwargs):
        self.endpoint_hash = sha256(self.endpoint.encode('utf-8')).hexdigest()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.profile} — {self.endpoint[:70]}'


class OTPThrottle(models.Model):
    mobile = models.CharField('شمارهٔ همراه', max_length=11, unique=True)
    window_started_at = models.DateTimeField('آغاز بازهٔ محدودیت', null=True, blank=True)
    last_sent_at = models.DateTimeField('آخرین زمان ارسال', null=True, blank=True)
    sends_in_window = models.PositiveSmallIntegerField('تعداد ارسال در بازه', default=0)

    class Meta:
        verbose_name = 'محدودیت ارسال کد'
        verbose_name_plural = 'محدودیت‌های ارسال کد'

    def __str__(self):
        return self.mobile


class OTPChallenge(models.Model):
    mobile = models.CharField('شمارهٔ همراه', max_length=11, db_index=True)
    code_hash = models.CharField('هش کد یک‌بارمصرف', max_length=128)
    client_ip = models.CharField('نشانی IP درخواست‌کننده', max_length=45, blank=True, db_index=True)
    created_at = models.DateTimeField('زمان ایجاد', auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField('زمان انقضا', db_index=True)
    attempt_count = models.PositiveSmallIntegerField('تعداد تلاش', default=0)
    consumed_at = models.DateTimeField('زمان مصرف یا ابطال', null=True, blank=True)

    class Meta:
        verbose_name = 'درخواست تأیید شماره'
        verbose_name_plural = 'درخواست‌های تأیید شماره'
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=('mobile', 'created_at'), name='otp_mobile_created_idx'),
            models.Index(fields=('client_ip', 'created_at'), name='otp_ip_created_idx'),
        ]

    def __str__(self):
        return f'{self.mobile} — {self.created_at:%Y-%m-%d %H:%M}'
