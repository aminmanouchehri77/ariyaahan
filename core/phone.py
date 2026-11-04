import re

from django.core.exceptions import ValidationError


PHONE_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def normalize_iran_mobile(value):
    mobile = value.translate(PHONE_DIGITS)
    mobile = re.sub(r'[\s().-]', '', mobile)
    if mobile.startswith('+98'):
        mobile = '0' + mobile[3:]
    elif mobile.startswith('0098'):
        mobile = '0' + mobile[4:]
    elif mobile.startswith('98') and len(mobile) == 12:
        mobile = '0' + mobile[2:]
    elif mobile.startswith('9') and len(mobile) == 10:
        mobile = '0' + mobile
    if not re.fullmatch(r'09\d{9}', mobile):
        raise ValidationError('شمارهٔ همراه معتبر وارد کنید؛ مانند ۰۹۱۲۳۴۵۶۷۸۹.')
    return mobile
