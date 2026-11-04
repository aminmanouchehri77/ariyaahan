from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


def default_listing_expiry():
    return timezone.now() + timedelta(days=30)


class MarketplaceListing(models.Model):
    class Kind(models.TextChoices):
        OFFER = 'offer', 'عرضه'
        REQUEST = 'request', 'تقاضا'

    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار بررسی'
        APPROVED = 'approved', 'تأیید و منتشر شد'
        REJECTED = 'rejected', 'رد شده'
        CLOSED = 'closed', 'بسته شد'

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

    kind = models.CharField('نوع آگهی', max_length=8, choices=Kind.choices, db_index=True)
    product_variant = models.ForeignKey(
        'catalog.ProductVariant',
        verbose_name='گونهٔ محصول کاتالوگ',
        related_name='marketplace_listings',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    product_label = models.CharField('نام کالا هنگام ثبت', max_length=180)
    quantity = models.DecimalField(
        'مقدار',
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
    )
    quantity_unit = models.CharField('واحد مقدار', max_length=12, choices=UNIT_CHOICES)
    price_amount = models.DecimalField(
        'مبلغ پیشنهادی برای هر واحد',
        max_digits=18,
        decimal_places=0,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('1'))],
    )
    currency = models.CharField('ارز', max_length=3, choices=CURRENCY_CHOICES, default='IRT')
    city = models.CharField('شهر / محل تحویل', max_length=100)
    details = models.TextField('شرایط و توضیحات', max_length=1200, blank=True)

    contact_name = models.CharField('نام تماس', max_length=120)
    mobile = models.CharField(
        'شمارهٔ همراه (خصوصی)',
        max_length=11,
        validators=[RegexValidator(r'^09\d{9}$', 'شمارهٔ همراه باید با ۰۹ شروع شود و ۱۱ رقم باشد.')],
    )
    company_name = models.CharField('نام شرکت', max_length=160, blank=True)
    show_company_name = models.BooleanField('نمایش عمومی نام شرکت با اجازهٔ ثبت‌کننده', default=False)
    contact_consent = models.BooleanField('اجازهٔ تماس برای بررسی آگهی', default=False)

    status = models.CharField('وضعیت انتشار', max_length=12, choices=Status.choices, default=Status.PENDING)
    admin_note = models.TextField('یادداشت داخلی', blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='بررسی‌کننده',
        related_name='reviewed_marketplace_listings',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    reviewed_at = models.DateTimeField('زمان بررسی', null=True, blank=True)
    expires_at = models.DateTimeField('اعتبار آگهی تا', default=default_listing_expiry, db_index=True)
    created_at = models.DateTimeField('زمان ثبت', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'آگهی تالار'
        verbose_name_plural = 'آگهی‌های تالار'
        ordering = ('-created_at', '-pk')
        indexes = [
            models.Index(fields=('kind', 'status', 'expires_at'), name='market_public_idx'),
            models.Index(fields=('status', 'created_at'), name='market_status_date_idx'),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} — {self.product_label} — {self.get_status_display()}'
