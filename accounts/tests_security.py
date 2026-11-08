"""Security tests for OTP login, session handling, IDOR, redirects and the SMS layer."""
import io
import logging
import os
import subprocess
import sys
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.phone import normalize_iran_mobile

from .forms import MobileLoginForm, OTPVerificationForm
from .models import CustomerAddress, CustomerNotification, CustomerProfile, OTPChallenge, OTPThrottle
from .services import OTPExpired, OTPInvalid, OTPRateLimited, issue_login_code, verify_login_code
from .sms import ConsoleSMSBackend, KavenegarVerifyLookupBackend, SMSDeliveryFailed
from .views import PENDING_MOBILE_SESSION_KEY


class RecordingSMSBackend:
    """Test backend: records codes instead of sending them."""

    sent = []

    def send_login_code(self, mobile, code):
        self.sent.append((mobile, code))

    def send_preinvoice_acceptance_code(self, mobile, code):
        self.sent.append((mobile, code))

    def send_price_alert(self, mobile, *, product, amount):
        self.sent.append((mobile, f'{product}:{amount}'))


class FailingSMSBackend:
    def send_login_code(self, mobile, code):
        raise SMSDeliveryFailed


RECORDING = 'accounts.tests_security.RecordingSMSBackend'
MOBILE = '09121234567'


@override_settings(
    SMS_BACKEND=RECORDING, OTP_EXPIRY_SECONDS=300, OTP_RESEND_SECONDS=60,
    OTP_MAX_SENDS_PER_HOUR=5, OTP_MAX_ATTEMPTS=5,
)
class OTPServiceTests(TestCase):
    def setUp(self):
        RecordingSMSBackend.sent = []

    def _last_code(self):
        return RecordingSMSBackend.sent[-1][1]

    def test_code_is_stored_hashed_not_plaintext(self):
        issue_login_code(MOBILE)
        code = self._last_code()
        challenge = OTPChallenge.objects.get()
        self.assertNotIn(code, challenge.code_hash)
        self.assertRegex(code, r'^\d{6}$')

    def test_code_single_use(self):
        issue_login_code(MOBILE)
        code = self._last_code()
        self.assertIsNotNone(verify_login_code(MOBILE, code))
        with self.assertRaises(OTPInvalid):
            verify_login_code(MOBILE, code)

    def test_code_expires(self):
        issue_login_code(MOBILE)
        code = self._last_code()
        OTPChallenge.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertRaises(OTPExpired):
            verify_login_code(MOBILE, code)
        # Expired challenge is consumed: the correct code never works again.
        with self.assertRaises(OTPInvalid):
            verify_login_code(MOBILE, code)

    def test_brute_force_locks_challenge_after_max_attempts(self):
        issue_login_code(MOBILE)
        code = self._last_code()
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(settings.OTP_MAX_ATTEMPTS):
            with self.assertRaises(OTPInvalid):
                verify_login_code(MOBILE, wrong)
        challenge = OTPChallenge.objects.get()
        self.assertIsNotNone(challenge.consumed_at)
        with self.assertRaises(OTPInvalid):
            verify_login_code(MOBILE, code)
        self.assertFalse(CustomerProfile.objects.exists())

    def test_resend_invalidates_previous_code(self):
        issue_login_code(MOBILE)
        old = self._last_code()
        OTPThrottle.objects.update(last_sent_at=timezone.now() - timedelta(seconds=61))
        issue_login_code(MOBILE)
        new = self._last_code()
        if old != new:
            with self.assertRaises(OTPInvalid):
                verify_login_code(MOBILE, old)
        self.assertIsNotNone(verify_login_code(MOBILE, new))

    def test_resend_cooldown(self):
        issue_login_code(MOBILE)
        with self.assertRaises(OTPRateLimited) as ctx:
            issue_login_code(MOBILE)
        self.assertGreater(ctx.exception.retry_after, 0)
        self.assertEqual(len(RecordingSMSBackend.sent), 1)

    def test_hourly_send_cap(self):
        for _ in range(settings.OTP_MAX_SENDS_PER_HOUR):
            issue_login_code(MOBILE)
            OTPThrottle.objects.update(last_sent_at=timezone.now() - timedelta(seconds=61))
        with self.assertRaises(OTPRateLimited):
            issue_login_code(MOBILE)
        self.assertEqual(len(RecordingSMSBackend.sent), settings.OTP_MAX_SENDS_PER_HOUR)

    def test_ip_cap_across_numbers(self):
        for index in range(10):
            issue_login_code(f'0912000{index:04d}', client_ip='203.0.113.9')
        with self.assertRaises(OTPRateLimited):
            issue_login_code('09129999999', client_ip='203.0.113.9')
        issue_login_code('09129999999', client_ip='203.0.113.10')

    def test_delivery_failure_consumes_challenge(self):
        with override_settings(SMS_BACKEND='accounts.tests_security.FailingSMSBackend'):
            with self.assertRaises(SMSDeliveryFailed):
                issue_login_code(MOBILE)
        self.assertIsNotNone(OTPChallenge.objects.get().consumed_at)

    def test_inactive_user_cannot_log_in(self):
        user = get_user_model().objects.create_user('inactive', is_active=False)
        CustomerProfile.objects.create(user=user, mobile=MOBILE)
        issue_login_code(MOBILE)
        from .services import AccountInactive
        with self.assertRaises(AccountInactive):
            verify_login_code(MOBILE, self._last_code())


@override_settings(SMS_BACKEND=RECORDING, OTP_RESEND_SECONDS=60, OTP_MAX_ATTEMPTS=5, OTP_MAX_SENDS_PER_HOUR=5)
class OTPLoginViewTests(TestCase):
    def setUp(self):
        RecordingSMSBackend.sent = []

    def _start(self, mobile=MOBILE, **extra):
        return self.client.post(reverse('accounts:login'), {'mobile': mobile, **extra})

    def _code(self):
        return RecordingSMSBackend.sent[-1][1]

    def test_full_login_creates_profile_and_rotates_session(self):
        self.client.get(reverse('accounts:login'))
        response = self._start()
        self.assertRedirects(response, reverse('accounts:verify'), fetch_redirect_response=False)
        pre_login_key = self.client.session.session_key
        response = self.client.post(reverse('accounts:verify'), {'code': self._code(), 'full_name': ' علی رضایی '})
        self.assertRedirects(response, reverse('accounts:profile'), fetch_redirect_response=False)
        self.assertNotEqual(self.client.session.session_key, pre_login_key)
        self.assertNotIn(PENDING_MOBILE_SESSION_KEY, self.client.session)
        profile = CustomerProfile.objects.get(mobile=MOBILE)
        self.assertEqual(profile.full_name, 'علی رضایی')
        self.assertEqual(str(profile.user.pk), self.client.session[SESSION_KEY])
        self.assertFalse(profile.user.has_usable_password())

    def test_full_name_not_overwritten_for_existing_profile(self):
        user = get_user_model().objects.create_user('existing')
        CustomerProfile.objects.create(user=user, mobile=MOBILE, full_name='قدیمی')
        self._start()
        self.client.post(reverse('accounts:verify'), {'code': self._code(), 'full_name': 'جدید'})
        self.assertEqual(CustomerProfile.objects.get().full_name, 'قدیمی')
        self.assertEqual(self.client.session[SESSION_KEY], str(user.pk))

    def test_known_and_unknown_numbers_get_identical_response(self):
        user = get_user_model().objects.create_user('known')
        CustomerProfile.objects.create(user=user, mobile='09120000001')
        known = Client().post(reverse('accounts:login'), {'mobile': '09120000001'}, follow=True)
        unknown = Client().post(reverse('accounts:login'), {'mobile': '09120000002'}, follow=True)
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.redirect_chain, unknown.redirect_chain)
        known_msgs = [str(m) for m in known.context['messages']]
        unknown_msgs = [str(m) for m in unknown.context['messages']]
        self.assertEqual(known_msgs, unknown_msgs)
        self.assertEqual(CustomerProfile.objects.count(), 1)

    def test_code_never_in_response_or_logs(self):
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger('accounts').debug('marker')
            response = self._start()
            followed = self.client.get(reverse('accounts:verify'))
        code = self._code()
        self.assertNotIn(code.encode(), response.content)
        self.assertNotIn(code.encode(), followed.content)
        self.assertNotIn(code, '\n'.join(logs.output))
        self.assertNotIn(MOBILE.encode(), followed.content)  # masked
        self.assertContains(followed, '0912*****67')

    def test_wrong_code_attempts_lock_out_then_right_code_fails(self):
        self._start()
        code = self._code()
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(5):
            response = self.client.post(reverse('accounts:verify'), {'code': wrong})
            self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('accounts:verify'), {'code': code})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_persian_digit_code_accepted(self):
        self._start()
        code = self._code().translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))
        response = self.client.post(reverse('accounts:verify'), {'code': code})
        self.assertEqual(response.status_code, 302)
        self.assertIn(SESSION_KEY, self.client.session)

    def test_resend_throttled_and_requires_post(self):
        self._start()
        self.assertEqual(self.client.get(reverse('accounts:resend')).status_code, 405)
        response = self.client.post(reverse('accounts:resend'), follow=True)
        self.assertEqual(len(RecordingSMSBackend.sent), 1)
        self.assertTrue(any('صبر' in str(m) for m in response.context['messages']))

    def test_resend_without_pending_mobile_redirects_to_login(self):
        response = self.client.post(reverse('accounts:resend'))
        self.assertRedirects(response, reverse('accounts:login'), fetch_redirect_response=False)
        self.assertEqual(RecordingSMSBackend.sent, [])

    def test_verify_without_pending_mobile(self):
        response = self.client.post(reverse('accounts:verify'), {'code': '123456'})
        self.assertRedirects(response, reverse('accounts:login'), fetch_redirect_response=False)

    def test_cannot_verify_other_number_by_posting_mobile(self):
        self._start('09121111111')
        victim_code = None
        Client().post(reverse('accounts:login'), {'mobile': '09122222222'})
        victim_code = self._code()
        response = self.client.post(reverse('accounts:verify'), {'code': victim_code, 'mobile': '09122222222'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CustomerProfile.objects.filter(mobile='09122222222').exists())

    def test_login_next_open_redirect_rejected(self):
        for evil in ('https://evil.example/', '//evil.example/x', '/\\evil.example', 'javascript:alert(1)'):
            client = Client()
            RecordingSMSBackend.sent = []
            client.post(reverse('accounts:login') + '?next=' + evil, {'mobile': MOBILE})
            OTPThrottle.objects.all().delete()
            response = client.post(reverse('accounts:verify'), {'code': self._code()})
            self.assertEqual(response['Location'], reverse('accounts:profile'), evil)
            OTPChallenge.objects.all().delete()

    def test_login_next_local_path_kept(self):
        self.client.post(reverse('accounts:login'), {'mobile': MOBILE, 'next': '/accounts/addresses/'})
        response = self.client.post(reverse('accounts:verify'), {'code': self._code()})
        self.assertEqual(response['Location'], '/accounts/addresses/')

    def test_authenticated_user_redirected_from_login(self):
        user = get_user_model().objects.create_user('logged')
        self.client.force_login(user)
        self.assertRedirects(self.client.get(reverse('accounts:login')), reverse('accounts:profile'),
                             fetch_redirect_response=False)

    def test_invalid_mobile_rerenders(self):
        response = self._start('12345')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(RecordingSMSBackend.sent, [])

    def test_change_number_clears_pending(self):
        self._start()
        response = self.client.get(reverse('accounts:login') + '?change=1')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(PENDING_MOBILE_SESSION_KEY, self.client.session)

    def test_sms_failure_shows_message_and_stays(self):
        with override_settings(SMS_BACKEND='accounts.tests_security.FailingSMSBackend'):
            response = self._start()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(PENDING_MOBILE_SESSION_KEY, self.client.session)

    def test_sms_not_configured(self):
        with override_settings(SMS_BACKEND='nope.Missing'):
            response = self._start()
        self.assertEqual(response.status_code, 200)

    def test_csrf_enforced_on_login_and_verify(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('accounts:login'), {'mobile': MOBILE}).status_code, 403)
        self.assertEqual(RecordingSMSBackend.sent, [])


class LogoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('u')

    def test_logout_get_not_allowed(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('accounts:logout')).status_code, 405)
        self.assertIn(SESSION_KEY, self.client.session)

    def test_logout_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(reverse('accounts:logout')).status_code, 403)
        self.assertIn(SESSION_KEY, client.session)

    def test_logout_post_keeps_cart_and_flushes_auth(self):
        self.client.force_login(self.user)
        from orders.cart import Cart
        session = self.client.session
        session[Cart.SESSION_KEY] = {'1': {'quantity': '2'}}
        session.save()
        old_key = session.session_key
        response = self.client.post(reverse('accounts:logout'))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertEqual(self.client.session[Cart.SESSION_KEY], {'1': {'quantity': '2'}})


class TwoUsersMixin:
    def setUp(self):
        users = get_user_model().objects
        self.user_a = users.create_user('a')
        self.user_b = users.create_user('b')
        self.profile_a = CustomerProfile.objects.create(user=self.user_a, mobile='09121111111')
        self.profile_b = CustomerProfile.objects.create(user=self.user_b, mobile='09122222222')
        self.client.force_login(self.user_a)


class IDORTests(TwoUsersMixin, TestCase):
    def _address(self, profile):
        return CustomerAddress.objects.create(
            profile=profile, recipient='ب', mobile='09123333333', province='تهران', city='تهران', address='خیابان',
        )

    def test_address_of_other_user_inaccessible(self):
        address = self._address(self.profile_b)
        self.assertEqual(self.client.get(reverse('accounts:address_edit', args=[address.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('accounts:address_edit', args=[address.pk]), {
            'title': 'x', 'recipient': 'x', 'mobile': '09124444444', 'province': 'x', 'city': 'x', 'address': 'x',
        }).status_code, 404)
        self.assertEqual(self.client.post(reverse('accounts:address_delete', args=[address.pk])).status_code, 404)
        address.refresh_from_db()
        self.assertEqual(address.recipient, 'ب')
        response = self.client.get(reverse('accounts:addresses'))
        self.assertNotContains(response, 'خیابان')

    def test_address_add_ignores_profile_field(self):
        self.client.post(reverse('accounts:address_add'), {
            'profile': self.profile_b.pk, 'title': 'x', 'recipient': 'x', 'mobile': '09124444444',
            'province': 'x', 'city': 'x', 'address': 'x',
        })
        self.assertEqual(CustomerAddress.objects.get().profile, self.profile_a)

    def test_notifications_of_other_user_inaccessible(self):
        note = CustomerNotification.objects.create(profile=self.profile_b, title='راز', body='b', target_url='/x/')
        self.assertEqual(self.client.post(reverse('accounts:notification_open', args=[note.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('accounts:notification_read', args=[note.pk])).status_code, 404)
        self.client.post(reverse('accounts:notifications_read'))
        note.refresh_from_db()
        self.assertFalse(note.is_read)
        self.assertNotContains(self.client.get(reverse('accounts:notifications')), 'راز')
        self.assertNotContains(self.client.get(reverse('accounts:profile')), 'راز')

    def test_profile_mass_assignment(self):
        self.client.post(reverse('accounts:profile'), {
            'full_name': 'نام', 'mobile': '09129999999', 'user': self.user_b.pk,
            'allow_price_notifications': 'on', 'is_staff': 'on',
        })
        self.profile_a.refresh_from_db()
        self.user_a.refresh_from_db()
        self.assertEqual(self.profile_a.full_name, 'نام')
        self.assertEqual(self.profile_a.mobile, '09121111111')
        self.assertEqual(self.profile_a.user, self.user_a)
        self.assertTrue(self.profile_a.allow_price_notifications)
        self.assertFalse(self.user_a.is_staff)

    def test_anonymous_redirected_to_login(self):
        client = Client()
        for name in ('profile', 'addresses', 'address_add', 'price_alerts', 'notifications', 'orders', 'requests'):
            response = client.get(reverse(f'accounts:{name}'))
            self.assertEqual(response.status_code, 302, name)
            self.assertTrue(response['Location'].startswith(reverse('accounts:login')), name)
        for name, args in (('address_delete', [1]), ('price_alert_delete', [1]), ('price_alert_toggle', [1]),
                           ('notification_open', [1]), ('notification_read', [1]), ('notifications_read', []),
                           ('push_subscribe', []), ('push_unsubscribe', [])):
            response = client.post(reverse(f'accounts:{name}', args=args))
            self.assertEqual(response.status_code, 302, name)


class NotificationRedirectTests(TwoUsersMixin, TestCase):
    def _note(self, url):
        return CustomerNotification.objects.create(profile=self.profile_a, title='t', body='b', target_url=url)

    def test_open_local_target(self):
        note = self._note('/catalog/x/')
        response = self.client.post(reverse('accounts:notification_open', args=[note.pk]))
        self.assertEqual(response['Location'], '/catalog/x/')
        note.refresh_from_db()
        self.assertTrue(note.is_read)

    def test_open_rejects_external_targets(self):
        for evil in ('https://evil.example/', '//evil.example', '/\\evil.example', 'javascript:alert(1)',
                     'http://testserver.evil.example/', '\\\\evil.example'):
            note = self._note(evil)
            response = self.client.post(reverse('accounts:notification_open', args=[note.pk]))
            self.assertEqual(response['Location'], reverse('accounts:notifications'), evil)

    def test_open_is_post_only(self):
        note = self._note('/x/')
        self.assertEqual(self.client.get(reverse('accounts:notification_open', args=[note.pk])).status_code, 405)

    def test_return_to_open_redirect(self):
        note = self._note('')
        for evil in ('https://evil.example/', '//evil.example'):
            response = self.client.post(reverse('accounts:notification_read', args=[note.pk]), {'return_to': evil})
            self.assertEqual(response['Location'], reverse('accounts:profile'))
            response = self.client.post(reverse('accounts:notifications_read'), {'return_to': evil})
            self.assertEqual(response['Location'], reverse('accounts:profile'))
        response = self.client.post(reverse('accounts:notifications_read'), {'return_to': '/accounts/notifications/?page=2'})
        self.assertEqual(response['Location'], '/accounts/notifications/?page=2')


class PhoneNormalisationTests(TestCase):
    def test_variants_normalise(self):
        for raw in ('09121234567', '۰۹۱۲۱۲۳۴۵۶۷', '٠٩١٢١٢٣٤٥٦٧', '+989121234567', '+۹۸۹۱۲۱۲۳۴۵۶۷',
                    '00989121234567', '989121234567', '9121234567', '0912 123 4567', '(0912) 123-4567'):
            self.assertEqual(normalize_iran_mobile(raw), MOBILE, raw)
            form = MobileLoginForm({'mobile': raw})
            self.assertTrue(form.is_valid(), raw)
            self.assertEqual(form.cleaned_data['mobile'], MOBILE)

    def test_invalid(self):
        for raw in ('', '0812345678', '091212345678', '+1 555 1234567', 'abc', '02112345678'):
            with self.assertRaises(ValidationError):
                normalize_iran_mobile(raw)
            self.assertFalse(MobileLoginForm({'mobile': raw}).is_valid(), raw)

    def test_otp_code_form(self):
        self.assertTrue(OTPVerificationForm({'code': '١٢٣٤٥٦'}).is_valid())
        for bad in ('12345', '1234567', 'abcdef', '12 456'):
            self.assertFalse(OTPVerificationForm({'code': bad}).is_valid(), bad)


class SMSBackendTests(TestCase):
    def _import_production_settings(self, extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('KAVENEGAR', 'SMS_BACKEND', 'DJANGO_'))}
        env.update({
            'DEBUG': '0', 'DJANGO_SECRET_KEY': 'prod-' + 'aB3$kL9#mN2@pQ7&' * 4,
            'ALLOWED_HOSTS': 'ariyaahan.example', 'PUBLIC_SITE_URL': 'https://ariyaahan.example',
            'DJANGO_SETTINGS_MODULE': 'config.settings', **extra,
        })
        return subprocess.run(
            [sys.executable, '-c', 'from django.conf import settings; print(f"SMS_BACKEND={settings.SMS_BACKEND!r}")'],
            cwd=Path(settings.BASE_DIR), env=env, capture_output=True, text=True, timeout=60,
        )

    def test_console_backend_refused_in_production_settings(self):
        root = Path(settings.BASE_DIR)
        result = self._import_production_settings({'SMS_BACKEND': 'accounts.sms.ConsoleSMSBackend'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('console SMS backend is development-only', result.stderr)

    def test_production_defaults_to_kavenegar_and_requires_credentials(self):
        result = self._import_production_settings({})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Configure these Kavenegar settings', result.stderr)
        result = self._import_production_settings({
            'KAVENEGAR_API_KEY': 'k', 'KAVENEGAR_OTP_TEMPLATE': 'login', 'KAVENEGAR_ACCEPT_TEMPLATE': 'accept',
        })
        self.assertNotIn('Kavenegar', result.stderr)
        self.assertNotIn('SMS backend', result.stderr)
        self.assertIn("SMS_BACKEND='accounts.sms.KavenegarVerifyLookupBackend'", result.stdout)

    def test_console_backend_prints(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            ConsoleSMSBackend().send_login_code(MOBILE, '123456')
        self.assertIn('123456', buffer.getvalue())

    @override_settings(KAVENEGAR_API_KEY='', KAVENEGAR_OTP_TEMPLATE='login')
    def test_kavenegar_requires_key(self):
        from .sms import SMSBackendNotConfigured
        with self.assertRaises(SMSBackendNotConfigured):
            KavenegarVerifyLookupBackend()

    @override_settings(KAVENEGAR_API_KEY='secret-key', KAVENEGAR_OTP_TEMPLATE='login', KAVENEGAR_TIMEOUT=1)
    def test_kavenegar_failure_logs_without_code_or_key(self):
        connection = mock.Mock()
        connection.getresponse.return_value = mock.Mock(status=200, read=mock.Mock(return_value=b'{"return":{"status":418}}'))
        with mock.patch('accounts.sms.http.client.HTTPSConnection', return_value=connection):
            with self.assertLogs('accounts.sms', level='WARNING') as logs:
                with self.assertRaises(SMSDeliveryFailed):
                    KavenegarVerifyLookupBackend().send_login_code(MOBILE, '654321')
        output = '\n'.join(logs.output)
        self.assertNotIn('654321', output)
        self.assertNotIn('secret-key', output)
        body = connection.request.call_args.kwargs['body'].decode()
        self.assertIn('token=654321', body)
        self.assertIn('template=login', body)

    @override_settings(KAVENEGAR_API_KEY='secret-key', KAVENEGAR_OTP_TEMPLATE='login', KAVENEGAR_TIMEOUT=1)
    def test_kavenegar_transport_error(self):
        connection = mock.Mock()
        connection.request.side_effect = OSError('down')
        with mock.patch('accounts.sms.http.client.HTTPSConnection', return_value=connection):
            with self.assertRaises(SMSDeliveryFailed):
                KavenegarVerifyLookupBackend().send_login_code(MOBILE, '654321')

    @override_settings(KAVENEGAR_API_KEY='k', KAVENEGAR_OTP_TEMPLATE='bad template!')
    def test_kavenegar_rejects_bad_template(self):
        from .sms import SMSBackendNotConfigured
        with self.assertRaises(SMSBackendNotConfigured):
            KavenegarVerifyLookupBackend()
