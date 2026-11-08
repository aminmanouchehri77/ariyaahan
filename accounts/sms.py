import http.client
import json
import logging
import re
from urllib.parse import quote, urlencode

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class SMSBackendNotConfigured(Exception):
    pass


class SMSDeliveryFailed(Exception):
    pass


def get_sms_backend():
    backend_path = getattr(settings, 'SMS_BACKEND', '')
    if not backend_path:
        raise SMSBackendNotConfigured
    try:
        backend_class = import_string(backend_path)
        return backend_class()
    except Exception as error:
        raise SMSBackendNotConfigured from error


class ConsoleSMSBackend:
    """Development-only delivery: prints the code in the runserver console."""

    def send_login_code(self, mobile, code):
        print(f'[LOCAL SMS to {mobile}] کد ورود آهن‌آلات آریا: {code}', flush=True)

    def send_preinvoice_acceptance_code(self, mobile, code):
        print(f'[LOCAL SMS to {mobile}] کد تأیید پذیرش پیش‌فاکتور آهن‌آلات آریا: {code}', flush=True)

    def send_price_alert(self, mobile, *, product, amount):
        print(f'[LOCAL SMS to {mobile}] هشدار قیمت آریا: {product} — {amount}', flush=True)


class KavenegarVerifyLookupBackend:
    """Send purpose-specific codes through Kavenegar's Verify Lookup endpoint."""

    host = 'api.kavenegar.com'

    def __init__(self):
        self.api_key = settings.KAVENEGAR_API_KEY
        self.template = settings.KAVENEGAR_OTP_TEMPLATE
        self.acceptance_template = settings.KAVENEGAR_ACCEPT_TEMPLATE
        if not self.api_key or not self.template:
            raise SMSBackendNotConfigured
        if not re.fullmatch(r'[A-Za-z0-9-]+', self.template):
            raise SMSBackendNotConfigured

    def send_login_code(self, mobile, code):
        self._send_verify_lookup(mobile, code, self.template)

    def send_preinvoice_acceptance_code(self, mobile, code):
        self.validate_send_preinvoice_acceptance_code()
        self._send_verify_lookup(mobile, code, self.acceptance_template)

    def send_price_alert(self, mobile, *, product, amount):
        """Price-alert SMS via a dedicated Verify Lookup template.

        Template example: «قیمت %token10 به %token رسید. آهن‌آلات آریا».
        token must not contain spaces; token10 allows up to five spaces.
        """
        template = getattr(settings, 'KAVENEGAR_ALERT_TEMPLATE', '')
        if not template or not re.fullmatch(r'[A-Za-z0-9-]+', template):
            raise SMSBackendNotConfigured
        words = str(product).split()[:6]
        self._send_verify_lookup(
            mobile, re.sub(r'\s+', '', str(amount))[:90], template, extra={'token10': ' '.join(words)[:90]},
        )

    def validate_send_preinvoice_acceptance_code(self):
        if not self.acceptance_template or not re.fullmatch(r'[A-Za-z0-9-]+', self.acceptance_template):
            raise SMSBackendNotConfigured

    def _send_verify_lookup(self, mobile, code, template, extra=None):
        path = f'/v1/{quote(self.api_key, safe="")}/verify/lookup.json'
        fields = {
            'receptor': mobile,
            'token': code,
            'template': template,
            'type': 'sms',
        }
        fields.update(extra or {})
        body = urlencode(fields).encode('utf-8')
        connection = http.client.HTTPSConnection(self.host, timeout=settings.KAVENEGAR_TIMEOUT)
        try:
            connection.request(
                'POST',
                path,
                body=body,
                headers={
                    'Accept': 'application/json',
                    'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
                },
            )
            response = connection.getresponse()
            response_body = response.read(65537)
        except (OSError, http.client.HTTPException, TimeoutError) as error:
            logger.warning('Kavenegar Verify Lookup transport failed (%s).', type(error).__name__)
            raise SMSDeliveryFailed('Kavenegar connection failed.') from None
        finally:
            connection.close()

        if response.status < 200 or response.status >= 300:
            logger.warning('Kavenegar Verify Lookup returned HTTP %s.', response.status)
            raise SMSDeliveryFailed('Kavenegar rejected the request.')
        if len(response_body) > 65536:
            logger.warning('Kavenegar Verify Lookup response exceeded the size limit.')
            raise SMSDeliveryFailed('Kavenegar returned an invalid response.')
        try:
            payload = json.loads(response_body.decode('utf-8'))
            api_status = payload.get('return', {}).get('status')
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError):
            logger.warning('Kavenegar Verify Lookup returned malformed JSON.')
            raise SMSDeliveryFailed('Kavenegar returned an invalid response.') from None

        if str(api_status) != '200':
            logger.warning('Kavenegar Verify Lookup returned API status %s.', api_status)
            raise SMSDeliveryFailed('Kavenegar could not accept the verification message.')
