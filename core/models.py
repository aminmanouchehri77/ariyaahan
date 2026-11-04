from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.db import models


class RedirectRule(models.Model):
    class StatusCode(models.IntegerChoices):
        PERMANENT = 301, 'دائمی (301)'
        TEMPORARY = 302, 'موقت (302)'
        GONE = 410, 'حذف‌شده (410)'

    old_path = models.CharField('مسیر قدیمی', max_length=255, unique=True)
    destination = models.CharField('مسیر مقصد داخلی', max_length=500, blank=True)
    status_code = models.PositiveSmallIntegerField('کد پاسخ', choices=StatusCode.choices, default=StatusCode.PERMANENT)
    is_active = models.BooleanField('فعال', default=True)
    note = models.CharField('یادداشت', max_length=240, blank=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'قاعدهٔ تغییر مسیر'
        verbose_name_plural = 'قواعد تغییر مسیر'
        ordering = ('old_path',)

    def clean(self):
        old = (self.old_path or '').strip()
        destination = (self.destination or '').strip()
        if not old.startswith('/') or '?' in old or '#' in old or old.startswith('//'):
            raise ValidationError({'old_path': 'مسیر قدیمی باید یک مسیر داخلی باشد و query نداشته باشد.'})
        if '\\' in old:
            raise ValidationError({'old_path': 'مسیر نمی‌تواند شامل بک‌اسلش باشد.'})
        if self.status_code == self.StatusCode.GONE:
            if destination:
                raise ValidationError({'destination': 'برای پاسخ 410 مقصد وارد نکنید.'})
        else:
            parts = urlsplit(destination)
            if not destination.startswith('/') or destination.startswith('//') or parts.scheme or parts.netloc:
                raise ValidationError({'destination': 'مقصد باید مسیر داخلی سایت باشد؛ نشانی خارجی مجاز نیست.'})
            if destination.rstrip('/') == old.rstrip('/'):
                raise ValidationError({'destination': 'مسیر مقصد نمی‌تواند همان مسیر قدیمی باشد.'})
            if '\\' in destination:
                raise ValidationError({'destination': 'مقصد نمی‌تواند شامل بک‌اسلش باشد.'})

    def save(self, *args, **kwargs):
        self.old_path = (self.old_path or '').strip()
        self.destination = (self.destination or '').strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.old_path} → {self.destination or self.get_status_code_display()}'
