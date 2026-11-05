from decimal import Decimal
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models


class CompanyContactDetails(models.Model):
    singleton_key = models.CharField('شناسهٔ تنظیمات', max_length=20, default='main', unique=True, editable=False)
    public_name = models.CharField('نام نمایشی شرکت', max_length=160, blank=True)
    phone = models.CharField(
        'تلفن اصلی', max_length=30, blank=True,
        validators=[RegexValidator(r'^\+?[0-9 ()-]{7,24}$', 'شمارهٔ تلفن را با ارقام و نشانه‌های مجاز وارد کنید.')],
    )
    alternate_phone = models.CharField(
        'تلفن دوم', max_length=30, blank=True,
        validators=[RegexValidator(r'^\+?[0-9 ()-]{7,24}$', 'شمارهٔ تلفن را با ارقام و نشانه‌های مجاز وارد کنید.')],
    )
    email = models.EmailField('رایانامهٔ عمومی', blank=True)
    address = models.TextField('نشانی رسمی', blank=True)
    office_hours = models.CharField('ساعات پاسخ‌گویی', max_length=180, blank=True)
    map_url = models.URLField('پیوند نقشه', max_length=500, blank=True)
    whatsapp_url = models.URLField('پیوند واتس‌اپ', max_length=500, blank=True)
    telegram_url = models.URLField('پیوند تلگرام', max_length=500, blank=True)
    instagram_url = models.URLField('پیوند اینستاگرام', max_length=500, blank=True)
    linkedin_url = models.URLField('پیوند لینکدین', max_length=500, blank=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'اطلاعات تماس شرکت'
        verbose_name_plural = 'اطلاعات تماس شرکت'

    def __str__(self):
        return self.public_name or 'اطلاعات تماس آهن‌آلات آریا'

    @property
    def has_public_details(self):
        return any((
            self.phone, self.alternate_phone, self.email, self.address, self.office_hours,
            self.map_url, self.whatsapp_url, self.telegram_url, self.instagram_url, self.linkedin_url,
        ))

    @property
    def phone_uri(self):
        return ''.join(character for character in self.phone if character.isdigit() or character == '+')

    @property
    def alternate_phone_uri(self):
        return ''.join(character for character in self.alternate_phone if character.isdigit() or character == '+')

    def save(self, *args, **kwargs):
        self.singleton_key = 'main'
        super().save(*args, **kwargs)


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
