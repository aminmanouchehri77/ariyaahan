"""Show dates in the Django admin in the Jalali calendar.

Django renders list/readonly values through admin.utils.display_for_field
(also imported by admin_list and helpers). We wrap it so date/datetime
fields come out as «۱۴۰۵/۰۸/۱۷ ۱۱:۵۴» while everything else is unchanged.
Form inputs stay Gregorian ISO so editing remains unambiguous.
"""

import datetime

from django.contrib.admin import helpers, utils
from django.contrib.admin.templatetags import admin_list
from django.db import models
from django.utils import timezone

PERSIAN_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def to_jalali(value, with_time=True):
    import jdatetime

    if isinstance(value, datetime.datetime):
        local = timezone.localtime(value) if timezone.is_aware(value) else value
        fmt = '%Y/%m/%d %H:%M' if with_time else '%Y/%m/%d'
        return jdatetime.datetime.fromgregorian(datetime=local).strftime(fmt).translate(PERSIAN_DIGITS)
    if isinstance(value, datetime.date):
        return jdatetime.date.fromgregorian(date=value).strftime('%Y/%m/%d').translate(PERSIAN_DIGITS)
    return value


def patch():
    original = utils.display_for_field
    if getattr(original, '_jalali', False):
        return

    def display_for_field(value, field, empty_value_display, *args, **kwargs):
        if value is not None and isinstance(field, (models.DateTimeField, models.DateField)):
            return to_jalali(value, with_time=isinstance(field, models.DateTimeField))
        return original(value, field, empty_value_display, *args, **kwargs)

    display_for_field._jalali = True
    utils.display_for_field = display_for_field
    admin_list.display_for_field = display_for_field
    helpers.display_for_field = display_for_field
