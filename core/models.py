from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import models


def is_safe_internal_path(value):
    """True for a same-site path such as '/steel/rebar/?a=1'.

    Rejects scheme/host URLs, protocol-relative '//host', backslashes (which
    browsers treat as '/'), and control/whitespace characters (browsers strip
    tab/newline, turning '/\t/evil.example' into '//evil.example').
    """
    from django.utils.http import url_has_allowed_host_and_scheme

    if not value or not value.startswith('/') or value.startswith('//'):
        return False
    if '\\' in value or any(ord(char) < 33 or ord(char) == 127 for char in value):
        return False
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return False
    return url_has_allowed_host_and_scheme(value, allowed_hosts=None)


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
            if not is_safe_internal_path(destination):
                raise ValidationError({'destination': 'مقصد باید مسیر داخلی سایت باشد؛ نشانی خارجی مجاز نیست.'})
            if destination.rstrip('/') == old.rstrip('/'):
                raise ValidationError({'destination': 'مسیر مقصد نمی‌تواند همان مسیر قدیمی باشد.'})
            if '\\' in destination:
                raise ValidationError({'destination': 'مقصد نمی‌تواند شامل بک‌اسلش باشد.'})
            if self.is_active:
                seen = {old.rstrip('/')}
                cursor = destination
                for _ in range(20):
                    cursor_path = urlsplit(cursor).path.rstrip('/')
                    if cursor_path in seen:
                        raise ValidationError({'destination': 'این مسیر به یک حلقهٔ تغییرمسیر می‌رسد.'})
                    seen.add(cursor_path)
                    next_rule = type(self).objects.filter(old_path=urlsplit(cursor).path, is_active=True).exclude(pk=self.pk).first()
                    if not next_rule or next_rule.status_code == self.StatusCode.GONE:
                        break
                    cursor = next_rule.destination
                else:
                    raise ValidationError({'destination': 'زنجیرهٔ تغییرمسیر بیش از حد طولانی است.'})

    def save(self, *args, **kwargs):
        self.old_path = (self.old_path or '').strip()
        self.destination = (self.destination or '').strip()
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.old_path} → {self.destination or self.get_status_code_display()}'


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = 'create', 'ایجاد'
        UPDATE = 'update', 'ویرایش'
        DELETE = 'delete', 'حذف'

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='کاربر', null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_logs',
    )
    action = models.CharField('عملیات', max_length=8, choices=Action.choices)
    model_label = models.CharField('موجودیت', max_length=80, db_index=True)
    object_id = models.CharField('شناسه', max_length=64, db_index=True)
    object_repr = models.CharField('عنوان', max_length=200)
    changes = models.JSONField('تغییرات', default=dict, blank=True)
    ip_address = models.GenericIPAddressField('IP', null=True, blank=True)
    created_at = models.DateTimeField('زمان', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'رویداد ممیزی'
        verbose_name_plural = 'گزارش ممیزی تغییرات'
        ordering = ('-created_at', '-pk')
        indexes = [models.Index(fields=('model_label', 'object_id', '-created_at'), name='audit_object_idx')]

    def __str__(self):
        return f'{self.get_action_display()} {self.model_label}#{self.object_id}'
