"""HTTP client for the SEP (Saman Electronic Payment) internet payment gateway.

Flow implemented against SEP's IPG technical document:

1. ``request_token``  - POST JSON ``{"action": "token", ...}`` to the token URL.
2. The customer's browser is sent with an auto-submitting POST form carrying
   ``Token`` to the payment URL (see ``payment_form_fields``).
3. SEP posts the result back to our callback (``State``, ``RefNum``, ``ResNum``...).
   Callback values are *not* proof of payment.
4. ``verify`` - POST JSON ``{"RefNum", "TerminalNumber"}`` to VerifyTransaction.
   Only ``ResultCode == 0`` with ``Success == true`` and a matching amount is a
   successful payment. Verification must happen within 30 minutes.
5. ``reverse`` - refund a verified transaction (for example a duplicate payment
   or amount mismatch) within the same window.

All amounts are integers in Rial. Secrets are never logged; only status codes.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 65536

VERIFY_RESULT_MESSAGES = {
    0: 'موفق',
    2: 'درخواست تکراری است.',
    -2: 'تراکنش یافت نشد.',
    -6: 'بیش از ۳۰ دقیقه از تراکنش گذشته است.',
    -104: 'پایانه غیرفعال است.',
    -105: 'پایانه یافت نشد.',
    -106: 'نشانی IP سرور برای پایانه مجاز نیست.',
    5: 'تراکنش قبلاً برگشت خورده است.',
}

# Customer-facing meaning of the callback ``Status`` / ``State`` values.
CALLBACK_STATE_MESSAGES = {
    'OK': 'پرداخت در درگاه انجام شد و در حال تأیید است.',
    'CanceledByUser': 'پرداخت توسط شما لغو شد.',
    'Failed': 'پرداخت ناموفق بود.',
    'SessionIsNull': 'مهلت پرداخت در درگاه به پایان رسید.',
    'InvalidParameters': 'اطلاعات ارسالی به درگاه معتبر نبود.',
    'MerchantIpAddressIsInvalid': 'نشانی سرور پذیرنده در درگاه ثبت نشده است.',
    'TokenNotFound': 'توکن پرداخت یافت نشد یا منقضی شده است.',
    'TokenRequired': 'توکن پرداخت ارسال نشده است.',
    'TerminalNotFound': 'پایانهٔ پرداخت یافت نشد.',
}


class SEPError(Exception):
    """The gateway refused the request or returned an unusable response."""

    def __init__(self, message, *, code=''):
        super().__init__(message)
        self.code = str(code)[:40]


class SEPTransportError(SEPError):
    """No usable response arrived (timeout, DNS, TLS or connection failure)."""


@dataclass(frozen=True)
class VerifyResult:
    success: bool
    result_code: int
    original_amount: Decimal | None
    affective_amount: Decimal | None
    ref_num: str
    trace_no: str
    rrn: str
    masked_pan: str
    terminal_number: str

    @property
    def message(self):
        return VERIFY_RESULT_MESSAGES.get(self.result_code, f'کد پاسخ {self.result_code}')


def _post_json(url, payload, *, timeout=None):
    """POST JSON and return the decoded body. Separated for testability."""
    body = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=body,
        method='POST',
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout or settings.SEP_TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
    except urllib.error.HTTPError as error:
        logger.warning('SEP returned HTTP %s for %s.', error.code, url.rsplit('/', 1)[-1])
        raise SEPError('درگاه پرداخت درخواست را نپذیرفت.', code=f'HTTP{error.code}') from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        logger.warning('SEP transport failed (%s).', type(error).__name__)
        raise SEPTransportError('ارتباط با درگاه پرداخت برقرار نشد.') from None

    if status < 200 or status >= 300 or len(raw) > MAX_RESPONSE_BYTES:
        raise SEPError('پاسخ درگاه پرداخت معتبر نبود.', code=f'HTTP{status}')
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SEPError('پاسخ درگاه پرداخت قابل خواندن نبود.') from None


def _decimal_or_none(value):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal('1'))
    except Exception:
        return None


class SEPClient:
    def __init__(self, *, transport=None):
        self.terminal_id = settings.SEP_TERMINAL_ID
        self.transport = transport or _post_json
        if not self.terminal_id:
            raise SEPError('شناسهٔ پایانهٔ سپ تنظیم نشده است.')

    # 1. Token -----------------------------------------------------------------
    def request_token(self, *, amount_rial, res_num, redirect_url, cell_number=''):
        amount = int(amount_rial)
        if amount <= 0:
            raise SEPError('مبلغ پرداخت باید مثبت باشد.')
        payload = {
            'action': 'token',
            'TerminalId': self.terminal_id,
            'Amount': amount,
            'ResNum': str(res_num)[:50],
            'RedirectUrl': redirect_url,
            'TokenExpiryInMin': settings.SEP_TOKEN_EXPIRY_MINUTES,
        }
        if cell_number:
            payload['CellNumber'] = cell_number
        data = self.transport(settings.SEP_TOKEN_URL, payload)
        if not isinstance(data, dict):
            raise SEPError('پاسخ دریافت توکن معتبر نبود.')
        if str(data.get('status')) == '1' and data.get('token'):
            return str(data['token'])
        code = data.get('errorCode', '')
        logger.warning('SEP token request rejected with code %s.', code)
        raise SEPError('درگاه پرداخت توکن صادر نکرد.', code=code)

    # 2. Redirect ----------------------------------------------------------------
    @staticmethod
    def payment_form_fields(token):
        return {'Token': token}

    # 4. Verify ------------------------------------------------------------------
    def verify(self, ref_num):
        return self._verify_like(settings.SEP_VERIFY_URL, ref_num, retries=settings.SEP_VERIFY_RETRIES)

    # 5. Reverse -----------------------------------------------------------------
    def reverse(self, ref_num):
        return self._verify_like(settings.SEP_REVERSE_URL, ref_num, retries=settings.SEP_VERIFY_RETRIES)

    def _verify_like(self, url, ref_num, *, retries=0):
        payload = {'RefNum': str(ref_num), 'TerminalNumber': int(self.terminal_id)}
        attempt = 0
        while True:
            try:
                data = self.transport(url, payload)
                break
            except SEPTransportError:
                # Retry only when no answer arrived; a definite answer is final.
                if attempt >= retries:
                    raise
                attempt += 1
                time.sleep(min(2, attempt))
        if not isinstance(data, dict):
            raise SEPError('پاسخ تأیید تراکنش معتبر نبود.')
        detail = data.get('TransactionDetail') or {}
        if not isinstance(detail, dict):
            detail = {}
        try:
            result_code = int(data.get('ResultCode'))
        except (TypeError, ValueError):
            raise SEPError('کد نتیجهٔ تأیید تراکنش معتبر نبود.') from None
        return VerifyResult(
            success=data.get('Success') is True and result_code == 0,
            result_code=result_code,
            # SEP spells the field "OrginalAmount"; accept the corrected spelling too.
            original_amount=_decimal_or_none(detail.get('OrginalAmount', detail.get('OriginalAmount'))),
            affective_amount=_decimal_or_none(detail.get('AffectiveAmount')),
            ref_num=str(detail.get('RefNum') or ref_num)[:120],
            trace_no=str(detail.get('StraceNo') or detail.get('TraceNo') or '')[:40],
            rrn=str(detail.get('RRN') or detail.get('Rrn') or '')[:40],
            masked_pan=str(detail.get('MaskedPan') or '')[:40],
            terminal_number=str(detail.get('TerminalNumber') or ''),
        )
