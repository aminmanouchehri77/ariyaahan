from decimal import Decimal
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models


class Inquiry(models.Model):
    class Kind(models.TextChoices):
        QUOTE = 'quote', 'درخواست قیمت'
        CONTACT = 'contact', 'پیام تماس'

    class Status(models.TextChoices):
        NEW = 'new', 'جدید'
        IN_PROGRESS = 'in_progress', 'در حال پیگیری'
        ANSWERED = 'answered', 'پاسخ داده شد'
        CLOSED = 'closed', 'بسته شد'

    public_id = models.UUIDField('شناسهٔ پیگیری', default=uuid.uuid4, unique=True, editable=False)
    profile = models.ForeignKey(
        'accounts.CustomerProfile', verbose_name='حساب مشتری', related_name='inquiries',
        null=True, blank=True, on_delete=models.SET_NULL,
    )
    kind = models.CharField('نوع درخواست', max_length=12, choices=Kind.choices)
    product_variant = models.ForeignKey(
        'catalog.ProductVariant',
        verbose_name='گونهٔ محصول',
        related_name='inquiries',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    product_label = models.CharField('نام محصول هنگام ثبت', max_length=300, blank=True)
    customer_name = models.CharField('نام و نام خانوادگی', max_length=120)
    mobile = models.CharField(
        'شمارهٔ همراه',
        max_length=11,
        validators=[RegexValidator(r'^09\d{9}$', 'شمارهٔ همراه باید با ۰۹ شروع شود و ۱۱ رقم باشد.')],
    )
    requested_quantity = models.DecimalField(
        'مقدار درخواستی',
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(Decimal('0.001'))],
        null=True,
        blank=True,
    )
    quantity_unit = models.CharField('واحد مقدار', max_length=40, blank=True)
    message = models.TextField('توضیحات', blank=True)
    status = models.CharField('وضعیت پیگیری', max_length=16, choices=Status.choices, default=Status.NEW)
    source_path = models.CharField('صفحهٔ مبدأ', max_length=255, blank=True)
    admin_note = models.TextField('یادداشت داخلی', blank=True)
    created_at = models.DateTimeField('زمان ثبت', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='مدیر ثبت‌کننده',
        related_name='managed_inquiries',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        verbose_name = 'درخواست مشتری'
        verbose_name_plural = 'درخواست‌های مشتریان'
        ordering = ('-created_at', '-pk')
        indexes = [
            models.Index(fields=('status', 'created_at'), name='inquiry_status_date_idx'),
            models.Index(fields=('kind', 'created_at'), name='inquiry_kind_date_idx'),
            models.Index(fields=('profile', 'status', 'created_at'), name='inquiry_profile_status_idx'),
        ]

    def __str__(self):
        created = self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else 'جدید'
        return f'{self.get_kind_display()} — {self.customer_name} — {created}'

    def save(self, *args, **kwargs):
        if self.product_variant and not self.product_label:
            variant = self.product_variant
            self.product_label = f'{variant.product.name} — {variant.name}'
        super().save(*args, **kwargs)
