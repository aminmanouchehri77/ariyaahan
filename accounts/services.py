import secrets
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from .models import CustomerProfile, OTPChallenge, OTPThrottle
from .sms import SMSBackendNotConfigured, SMSDeliveryFailed, get_sms_backend


class OTPRateLimited(Exception):
    def __init__(self, retry_after):
        self.retry_after = max(1, int(retry_after))
        super().__init__('OTP requests are temporarily rate limited.')


class OTPInvalid(Exception):
    pass


class OTPExpired(Exception):
    pass


class AccountInactive(Exception):
    pass


def _retry_after(when, now):
    return max(1, int((when - now).total_seconds()) + 1)


def issue_login_code(mobile, client_ip=''):
    backend = get_sms_backend()
    now = timezone.now()
    resend_seconds = settings.OTP_RESEND_SECONDS
    hour = timedelta(hours=1)
    expires_at = now + timedelta(seconds=settings.OTP_EXPIRY_SECONDS)
    code = f'{secrets.randbelow(1_000_000):06d}'

    with transaction.atomic():
        throttle, _ = OTPThrottle.objects.get_or_create(mobile=mobile)
        throttle = OTPThrottle.objects.select_for_update().get(pk=throttle.pk)

        if throttle.last_sent_at and now < throttle.last_sent_at + timedelta(seconds=resend_seconds):
            raise OTPRateLimited(_retry_after(throttle.last_sent_at + timedelta(seconds=resend_seconds), now))

        if not throttle.window_started_at or now >= throttle.window_started_at + hour:
            throttle.window_started_at = now
            throttle.sends_in_window = 0
        if throttle.sends_in_window >= settings.OTP_MAX_SENDS_PER_HOUR:
            raise OTPRateLimited(_retry_after(throttle.window_started_at + hour, now))

        if client_ip:
            ip_window_start = now - timedelta(minutes=10)
            ip_requests = OTPChallenge.objects.filter(
                client_ip=client_ip,
                created_at__gte=ip_window_start,
            ).count()
            if ip_requests >= 10:
                oldest_recent_request = OTPChallenge.objects.filter(
                    client_ip=client_ip,
                    created_at__gte=ip_window_start,
                ).order_by('created_at').values_list('created_at', flat=True).first()
                raise OTPRateLimited(_retry_after(oldest_recent_request + timedelta(minutes=10), now))

        OTPChallenge.objects.filter(
            mobile=mobile,
            consumed_at__isnull=True,
        ).update(consumed_at=now)
        challenge = OTPChallenge.objects.create(
            mobile=mobile,
            code_hash=make_password(code),
            client_ip=client_ip,
            expires_at=expires_at,
        )
        throttle.last_sent_at = now
        throttle.sends_in_window += 1
        throttle.save(update_fields=('window_started_at', 'last_sent_at', 'sends_in_window'))

    try:
        backend.send_login_code(mobile, code)
    except Exception as error:
        OTPChallenge.objects.filter(pk=challenge.pk, consumed_at__isnull=True).update(consumed_at=timezone.now())
        if isinstance(error, (SMSBackendNotConfigured, SMSDeliveryFailed)):
            raise
        raise SMSDeliveryFailed from error


def verify_login_code(mobile, code, full_name=''):
    now = timezone.now()
    error = None
    user = None

    with transaction.atomic():
        challenge = OTPChallenge.objects.select_for_update().filter(
            mobile=mobile,
        ).order_by('-created_at', '-pk').first()

        if not challenge or challenge.consumed_at:
            error = OTPInvalid
        elif challenge.expires_at <= now:
            challenge.consumed_at = now
            challenge.save(update_fields=('consumed_at',))
            error = OTPExpired
        elif challenge.attempt_count >= settings.OTP_MAX_ATTEMPTS:
            challenge.consumed_at = now
            challenge.save(update_fields=('consumed_at',))
            error = OTPInvalid
        else:
            challenge.attempt_count += 1
            if not check_password(code, challenge.code_hash):
                if challenge.attempt_count >= settings.OTP_MAX_ATTEMPTS:
                    challenge.consumed_at = now
                challenge.save(update_fields=('attempt_count', 'consumed_at'))
                error = OTPInvalid
            else:
                challenge.consumed_at = now
                challenge.save(update_fields=('attempt_count', 'consumed_at'))

                profile = CustomerProfile.objects.select_for_update().select_related('user').filter(
                    mobile=mobile,
                ).first()
                if profile:
                    user = profile.user
                else:
                    user_model = get_user_model()
                    user = user_model.objects.create_user(
                        username=f'customer-{uuid.uuid4().hex}',
                        password=None,
                    )
                    profile = CustomerProfile.objects.create(user=user, mobile=mobile)

                if not user.is_active:
                    user = None
                    error = AccountInactive
                elif full_name and not profile.full_name:
                    profile.full_name = full_name.strip()
                    profile.save(update_fields=('full_name', 'updated_at'))

    if error is OTPExpired:
        raise OTPExpired
    if error is AccountInactive:
        raise AccountInactive
    if error:
        raise OTPInvalid
    return user
