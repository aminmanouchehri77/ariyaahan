from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone


class PriceObservation(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار تأیید'
        APPROVED = 'approved', 'تأیید شده'
        REJECTED = 'rejected', 'رد شده'

    class Currency(models.TextChoices):
        IRR = 'IRR', 'ریال'
        IRT = 'IRT', 'تومان'
        USD = 'USD', 'دلار آمریکا'

    class PriceBasis(models.TextChoices):
        KILOGRAM = 'kg', 'کیلوگرم'
        TONNE = 'ton', 'تن'
        PIECE = 'piece', 'شاخه / عدد'
        BUNDLE = 'bundle', 'بندیل'
        SHEET = 'sheet', 'شیت'
        METER = 'meter', 'متر'

    variant = models.ForeignKey(
        'catalog.ProductVariant',
        verbose_name='گونهٔ محصول',
        related_name='price_observations',
        on_delete=models.PROTECT,
    )
    amount = models.DecimalField(
        'مبلغ',
        max_digits=18,
        decimal_places=0,
        validators=[MinValueValidator(1)],
    )
    currency = models.CharField('ارز', max_length=3, choices=Currency.choices, default=Currency.IRR)
    unit_label = models.CharField('مبنای قیمت', max_length=40, blank=True)
    price_basis = models.CharField('واحد محاسباتی قیمت', max_length=12, choices=PriceBasis.choices, blank=True)
    delivery_location = models.CharField('محل تحویل', max_length=140, blank=True)
    source = models.CharField('منبع قیمت', max_length=160, blank=True)
    is_available = models.BooleanField('موجود است', default=True)
    tax_included = models.BooleanField('مالیات در مبلغ لحاظ شده', null=True, blank=True)
    status = models.CharField('وضعیت بررسی', max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    observed_at = models.DateTimeField('زمان ثبت/به‌روزرسانی', default=timezone.now, db_index=True)
    valid_until = models.DateTimeField('اعتبار تا', null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='ثبت‌کننده',
        related_name='price_observations',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='تأییدکننده',
        related_name='approved_price_observations',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    approved_at = models.DateTimeField('زمان تأیید', null=True, blank=True)
    created_at = models.DateTimeField('زمان ایجاد رکورد', auto_now_add=True)

    class Meta:
        verbose_name = 'ثبت قیمت'
        verbose_name_plural = 'تاریخچهٔ قیمت‌ها'
        ordering = ('-observed_at', '-pk')
        indexes = [
            models.Index(fields=('variant', 'status', '-observed_at'), name='price_variant_latest_idx'),
            models.Index(fields=('currency', 'observed_at'), name='price_currency_date_idx'),
        ]

    def __str__(self):
        return f'{self.variant} — {self.amount} {self.get_currency_display()}'

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values(
                'variant_id', 'amount', 'currency', 'unit_label', 'price_basis',
                'delivery_location', 'source', 'is_available', 'tax_included',
                'observed_at', 'valid_until',
            ).first()
            if old:
                changed = [key for key, value in old.items() if getattr(self, key) != value]
                if changed:
                    raise ValidationError('مشخصات یک ثبت قیمت پس از ایجاد قابل ویرایش نیست؛ ثبت تازه بسازید.')
        is_new = self._state.adding
        previous_status = None
        if not is_new:
            previous_status = type(self).objects.filter(pk=self.pk).values_list('status', flat=True).first()
        if self.status == self.Status.APPROVED and (not self.approved_at or not self.approved_by_id):
            raise ValidationError('برای تأیید قیمت باید مدیر تأییدکننده و زمان تأیید ثبت شود.')
        super().save(*args, **kwargs)
        if is_new:
            PriceReviewEvent.objects.create(
                observation=self, action=PriceReviewEvent.Action.CREATED,
                to_status=self.status, actor=self.created_by,
            )
        elif previous_status != self.status:
            PriceReviewEvent.objects.create(
                observation=self, action=PriceReviewEvent.Action.STATUS_CHANGED,
                from_status=previous_status or '', to_status=self.status,
                actor=self.approved_by, note=getattr(self, '_review_note', ''),
            )

    @transaction.atomic
    def approve(self, actor):
        type(self)._meta.get_field('variant').remote_field.model.objects.select_for_update().get(
            pk=self.variant_id,
        )
        observation = type(self).objects.select_for_update().get(pk=self.pk)
        if observation.status == self.Status.REJECTED:
            raise ValidationError('ثبت قیمت ردشده را نمی‌توان تأیید کرد؛ ثبت تازه ایجاد کنید.')
        observation.status = self.Status.APPROVED
        observation.approved_by = actor
        observation.approved_at = timezone.now()
        observation.save(update_fields=('status', 'approved_by', 'approved_at'))
        self.status = observation.status
        self.approved_by = actor
        self.approved_at = observation.approved_at

    @transaction.atomic
    def reject(self, actor, note=''):
        observation = type(self).objects.select_for_update().get(pk=self.pk)
        if observation.status != self.Status.PENDING:
            raise ValidationError('فقط ثبت قیمت در انتظار تأیید قابل رد است.')
        observation.status = self.Status.REJECTED
        observation.approved_by = actor
        observation.approved_at = timezone.now()
        observation._review_note = note[:500]
        observation.save(update_fields=('status', 'approved_by', 'approved_at'))
        self.status = observation.status
        self.approved_by = actor
        self.approved_at = observation.approved_at


class PriceReviewEvent(models.Model):
    class Action(models.TextChoices):
        CREATED = 'created', 'ثبت'
        STATUS_CHANGED = 'status', 'تغییر وضعیت'

    observation = models.ForeignKey(
        PriceObservation, verbose_name='ثبت قیمت', related_name='review_events', on_delete=models.PROTECT,
    )
    action = models.CharField('رویداد', max_length=12, choices=Action.choices)
    from_status = models.CharField('وضعیت پیشین', max_length=12, blank=True)
    to_status = models.CharField('وضعیت جدید', max_length=12, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='کاربر', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='price_review_events',
    )
    note = models.CharField('یادداشت', max_length=500, blank=True)
    created_at = models.DateTimeField('زمان رویداد', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'رویداد بررسی قیمت'
        verbose_name_plural = 'رویدادهای بررسی قیمت'
        ordering = ('-created_at', '-pk')

    def __str__(self):
        return f'{self.observation_id} — {self.get_action_display()} — {self.created_at:%Y-%m-%d %H:%M}'


class PriceObservationTask(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'در صف پردازش'
        COMPLETE = 'complete', 'پردازش‌شده'
        FAILED = 'failed', 'نیازمند بازبینی'

    observation = models.OneToOneField(
        PriceObservation, verbose_name='ثبت قیمت', related_name='processing_task',
        on_delete=models.PROTECT,
    )
    status = models.CharField('وضعیت پردازش', max_length=12, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField('تعداد تلاش', default=0)
    available_at = models.DateTimeField('زمان تلاش بعدی', default=timezone.now, db_index=True)
    completed_at = models.DateTimeField('زمان پایان', null=True, blank=True)
    last_error = models.CharField('نوع آخرین خطا', max_length=80, blank=True)
    created_at = models.DateTimeField('زمان ایجاد', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('آخرین تغییر', auto_now=True)

    class Meta:
        verbose_name = 'کار پردازش قیمت'
        verbose_name_plural = 'صف پردازش قیمت‌ها'
        ordering = ('available_at', 'pk')
        indexes = [
            models.Index(fields=('status', 'available_at'), name='price_task_due_idx'),
        ]

    def __str__(self):
        return f'{self.observation_id} — {self.get_status_display()}'


class InventoryLocation(models.Model):
    name = models.CharField('نام انبار / محل تحویل', max_length=140, unique=True)
    city = models.CharField('شهر', max_length=100, blank=True)
    address = models.CharField('نشانی', max_length=300, blank=True)
    is_active = models.BooleanField('فعال', default=True)

    class Meta:
        verbose_name = 'محل موجودی'
        verbose_name_plural = 'محل‌های موجودی'
        ordering = ('city', 'name')

    def __str__(self):
        return f'{self.name} — {self.city}' if self.city else self.name


class StockObservation(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار تأیید'
        APPROVED = 'approved', 'تأیید شده'
        REJECTED = 'rejected', 'رد شده'

    variant = models.ForeignKey(
        'catalog.ProductVariant', verbose_name='گونهٔ محصول', related_name='stock_observations',
        on_delete=models.PROTECT,
    )
    location = models.ForeignKey(
        InventoryLocation, verbose_name='انبار / محل تحویل', related_name='stock_observations',
        on_delete=models.PROTECT,
    )
    quantity = models.DecimalField('موجودی', max_digits=14, decimal_places=3, validators=[MinValueValidator(0)])
    unit = models.CharField('واحد', max_length=12, choices=PriceObservation.PriceBasis.choices)
    is_available = models.BooleanField('قابل سفارش است', default=True)
    source = models.CharField('منبع داده', max_length=160, blank=True)
    status = models.CharField('وضعیت بررسی', max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    observed_at = models.DateTimeField('زمان مشاهده', default=timezone.now, db_index=True)
    valid_until = models.DateTimeField('اعتبار تا', null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='ثبت‌کننده', related_name='stock_observations',
        null=True, blank=True, on_delete=models.SET_NULL,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='تأییدکننده', related_name='approved_stock_observations',
        null=True, blank=True, on_delete=models.SET_NULL,
    )
    approved_at = models.DateTimeField('زمان تأیید', null=True, blank=True)
    created_at = models.DateTimeField('زمان ایجاد', auto_now_add=True)

    class Meta:
        verbose_name = 'ثبت موجودی'
        verbose_name_plural = 'ثبت‌های موجودی'
        ordering = ('-observed_at', '-pk')
        indexes = [
            models.Index(fields=('variant', 'location', 'status', '-observed_at'), name='stock_latest_idx'),
        ]

    def __str__(self):
        return f'{self.variant} — {self.location} — {self.quantity} {self.get_unit_display()}'

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values(
                'variant_id', 'location_id', 'quantity', 'unit', 'is_available',
                'source', 'observed_at', 'valid_until',
            ).first()
            if old and any(getattr(self, key) != value for key, value in old.items()):
                raise ValidationError('مشخصات یک ثبت موجودی پس از ایجاد قابل ویرایش نیست؛ ثبت تازه بسازید.')
        if self.status == self.Status.APPROVED and (not self.approved_at or not self.approved_by_id):
            raise ValidationError('برای تأیید موجودی باید مدیر تأییدکننده و زمان تأیید ثبت شود.')
        super().save(*args, **kwargs)

    @transaction.atomic
    def approve(self, actor):
        type(self)._meta.get_field('variant').remote_field.model.objects.select_for_update().get(
            pk=self.variant_id,
        )
        observation = type(self).objects.select_for_update().get(pk=self.pk)
        if observation.status == self.Status.REJECTED:
            raise ValidationError('ثبت موجودی ردشده را نمی‌توان تأیید کرد؛ ثبت تازه ایجاد کنید.')
        observation.status = self.Status.APPROVED
        observation.approved_by = actor
        observation.approved_at = timezone.now()
        observation.save(update_fields=('status', 'approved_by', 'approved_at'))
        self.status = observation.status
        self.approved_by = actor
        self.approved_at = observation.approved_at

    @transaction.atomic
    def reject(self, actor):
        observation = type(self).objects.select_for_update().get(pk=self.pk)
        if observation.status != self.Status.PENDING:
            raise ValidationError('فقط ثبت موجودی در انتظار تأیید قابل رد است.')
        observation.status = self.Status.REJECTED
        observation.approved_by = actor
        observation.approved_at = timezone.now()
        observation.save(update_fields=('status', 'approved_by', 'approved_at'))
        self.status = observation.status
        self.approved_by = actor
        self.approved_at = observation.approved_at


class ShippingRate(models.Model):
    class Method(models.TextChoices):
        ANY = '', 'همهٔ روش‌ها (بدون تفکیک)'
        TRAILER = 'trailer', 'تریلی'
        TRUCK = 'truck', 'کامیون ده‌چرخ'
        LIGHT = 'light', 'خاور / کامیونت'

    origin_city = models.CharField('مبدأ', max_length=100, db_index=True)
    destination_city = models.CharField('مقصد', max_length=100, db_index=True)
    method = models.CharField(
        'روش ارسال', max_length=12, choices=Method.choices, blank=True, default='', db_index=True,
        help_text='خالی یعنی نرخ برای هر روش ارسال معتبر است.',
    )
    minimum_tonnes = models.DecimalField('حداقل وزن (تن)', max_digits=10, decimal_places=3, default=0)
    maximum_tonnes = models.DecimalField('حداکثر وزن (تن)', max_digits=10, decimal_places=3, null=True, blank=True)
    base_fee = models.DecimalField('هزینهٔ ثابت', max_digits=18, decimal_places=0, default=0, validators=[MinValueValidator(0)])
    per_tonne = models.DecimalField('هزینه به‌ازای هر تن', max_digits=18, decimal_places=0, validators=[MinValueValidator(1)])
    currency = models.CharField('ارز', max_length=3, choices=PriceObservation.Currency.choices, default=PriceObservation.Currency.IRT)
    tax_included = models.BooleanField('مالیات در مبلغ لحاظ شده', null=True, blank=True)
    source = models.CharField('منبع نرخ', max_length=160, blank=True)
    valid_until = models.DateTimeField('اعتبار نرخ تا')
    is_active = models.BooleanField('فعال', default=True, db_index=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'نرخ حمل'
        verbose_name_plural = 'نرخ‌های حمل'
        ordering = ('origin_city', 'destination_city', 'minimum_tonnes')
        indexes = [
            models.Index(fields=('origin_city', 'destination_city', 'is_active'), name='shipping_route_active_idx'),
        ]

    def __str__(self):
        method = f' ({self.get_method_display()})' if self.method else ''
        return f'{self.origin_city} ← {self.destination_city}{method} — {self.per_tonne} / تن'
