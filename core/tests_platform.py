"""Admin platform tests: login protection, staff roles, audit log, dashboard."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings

from core.models import AuditLog, RedirectRule
from core.templatetags.admin_dashboard import admin_dashboard

User = get_user_model()


def staff_with_perms(username, *perms):
    user = User.objects.create_user(username=username, password='x-Strong-Pass-91', is_staff=True)
    for perm in perms:
        app_label, codename = perm.split('.')
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=codename))
    return User.objects.get(pk=user.pk)  # drop permission cache


class AdminAccessTests(TestCase):
    def test_admin_requires_staff_login(self):
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response['Location'])
        customer = User.objects.create_user(username='customer', password='x-Strong-Pass-91')
        self.client.force_login(customer)
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response['Location'])
        self.assertEqual(self.client.get('/admin/core/auditlog/').status_code, 302)

    def test_staff_without_permission_cannot_open_models(self):
        self.client.force_login(staff_with_perms('nobody'))
        self.assertEqual(self.client.get('/admin/').status_code, 200)
        self.assertEqual(self.client.get('/admin/core/auditlog/').status_code, 403)
        self.assertEqual(self.client.get('/admin/core/redirectrule/').status_code, 403)

    def test_admin_login_page_is_not_frameable(self):
        response = self.client.get('/admin/login/')
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", response['Content-Security-Policy'])


class StaffRoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('setup_staff_roles', stdout=open('/dev/null', 'w'))
        cls.groups = {group.name: set(
            f'{p.content_type.app_label}.{p.codename}' for p in group.permissions.select_related('content_type')
        ) for group in Group.objects.all()}

    def test_all_roles_created_and_idempotent(self):
        self.assertEqual(len(self.groups), 5)
        call_command('setup_staff_roles', stdout=open('/dev/null', 'w'))
        self.assertEqual(Group.objects.count(), 5)

    def test_no_role_can_delete_or_manage_users(self):
        for name, perms in self.groups.items():
            with self.subTest(role=name):
                self.assertTrue(perms)
                self.assertFalse([p for p in perms if '.delete_' in p], name)
                self.assertFalse([p for p in perms if p.startswith(('auth.', 'admin.', 'sessions.', 'contenttypes.'))])
                self.assertFalse([p for p in perms if p.startswith('core.')], 'audit/redirects stay superuser-only')
                self.assertFalse([p for p in perms if p.split('.')[1].startswith(('change_auditlog', 'add_auditlog'))])

    def test_price_operator_least_privilege(self):
        perms = self.groups['اپراتور قیمت و حمل']
        self.assertIn('pricing.add_priceobservation', perms)
        self.assertIn('pricing.change_shippingrate', perms)
        self.assertNotIn('pricing.add_pricereviewevent', perms)
        self.assertNotIn('pricing.change_pricereviewevent', perms)
        self.assertNotIn('pricing.add_priceobservationtask', perms)
        self.assertFalse([p for p in perms if not p.startswith('pricing.')])
        self.assertNotIn('orders.change_order', perms)

    def test_sales_cannot_forge_payments_or_status_history(self):
        perms = self.groups['فروش و سفارش']
        self.assertIn('orders.change_order', perms)
        self.assertIn('orders.view_paymentrecord', perms)
        for forbidden in ('orders.add_paymentrecord', 'orders.change_paymentrecord',
                          'orders.add_orderstatusevent', 'orders.change_orderstatusevent',
                          'pricing.add_priceobservation', 'catalog.change_product'):
            self.assertNotIn(forbidden, perms)

    def test_other_roles_stay_in_their_lane(self):
        self.assertFalse([p for p in self.groups['مدیر کاتالوگ'] if not p.startswith('catalog.')])
        content = self.groups['تحریریه محتوا']
        self.assertNotIn('content.add_marketnews', content)
        self.assertFalse([p for p in content if p.startswith(('orders.', 'pricing.', 'accounts.'))])
        support = self.groups['پشتیبانی مشتری']
        self.assertNotIn('accounts.add_customernotification', support)
        self.assertFalse([p for p in support if p.startswith(('orders.', 'pricing.', 'catalog.'))])

    def test_price_operator_blocked_from_orders_in_admin(self):
        user = User.objects.create_user(username='pricer', password='x-Strong-Pass-91', is_staff=True)
        user.groups.add(Group.objects.get(name='اپراتور قیمت و حمل'))
        self.client.force_login(user)
        self.assertEqual(self.client.get('/admin/orders/order/').status_code, 403)
        self.assertEqual(self.client.get('/admin/pricing/priceobservation/').status_code, 200)


class AuditLogTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='root', password='x-Strong-Pass-91')
        self.client.force_login(self.admin)

    def _add_rule(self, **extra):
        return self.client.post('/admin/core/redirectrule/add/', {
            'old_path': '/legacy-a/', 'destination': '/steel/', 'status_code': 301, 'is_active': 'on', 'note': '',
        }, **extra)

    def test_records_actor_and_ip(self):
        response = self._add_rule(REMOTE_ADDR='198.51.100.20', HTTP_X_FORWARDED_FOR='6.6.6.6')
        self.assertEqual(response.status_code, 302)
        log = AuditLog.objects.get(model_label='core.RedirectRule', action='create')
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.ip_address, '198.51.100.20')  # spoofed header ignored
        self.assertEqual(log.changes['destination'], '/steel/')

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_ip_from_trusted_proxy(self):
        self._add_rule(REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='6.6.6.6, 203.0.113.5')
        self.assertEqual(AuditLog.objects.get(model_label='core.RedirectRule').ip_address, '203.0.113.5')

    def test_admin_is_read_only_even_for_superuser(self):
        rule = RedirectRule.objects.create(old_path='/x-old/', destination='/steel/')
        log = AuditLog.objects.get(model_label='core.RedirectRule')
        self.assertEqual(self.client.get('/admin/core/auditlog/').status_code, 200)
        self.assertEqual(self.client.get('/admin/core/auditlog/add/').status_code, 403)
        self.assertEqual(self.client.get(f'/admin/core/auditlog/{log.pk}/delete/').status_code, 403)
        response = self.client.post(f'/admin/core/auditlog/{log.pk}/change/', {'object_repr': 'tampered'})
        self.assertEqual(response.status_code, 403)
        log.refresh_from_db()
        self.assertNotEqual(log.object_repr, 'tampered')
        response = self.client.post('/admin/core/auditlog/', {
            'action': 'delete_selected', '_selected_action': [log.pk], 'post': 'yes',
        })
        self.assertTrue(AuditLog.objects.filter(pk=log.pk).exists())
        self.assertTrue(rule.pk)

    def test_delete_and_secret_fields_not_stored(self):
        rule = RedirectRule.objects.create(old_path='/to-delete/', destination='/steel/')
        rule.delete()
        self.assertTrue(AuditLog.objects.filter(model_label='core.RedirectRule', action='delete').exists())
        for log in AuditLog.objects.all():
            self.assertNotIn('password', log.changes)


class AdminDashboardTests(TestCase):
    def dashboard(self, user):
        request = RequestFactory().get('/admin/')
        request.user = user
        return admin_dashboard({'request': request})

    def labels(self, data):
        return {item['label'] for key in ('kpis', 'tasks', 'quick') for item in data[key]}

    def test_no_permissions_no_numbers(self):
        data = self.dashboard(staff_with_perms('bare'))
        self.assertEqual(data['kpis'], [])
        self.assertEqual(data['tasks'], [])
        self.assertEqual(data['quick'], [])
        self.assertEqual(data['audit'], [])
        self.assertEqual(data['recent_orders'], [])
        self.assertIsNone(data['freshness'])

    def test_order_viewer_does_not_see_payment_revenue(self):
        data = self.dashboard(staff_with_perms('ordersonly', 'orders.view_order'))
        labels = self.labels(data)
        self.assertIn('سفارش در انتظار پرداخت', labels)
        self.assertNotIn('دریافتی امروز (ریال)', labels)
        data = self.dashboard(staff_with_perms('payments', 'orders.view_order', 'orders.view_paymentrecord'))
        self.assertIn('دریافتی امروز (ریال)', self.labels(data))

    def test_price_viewer_gets_no_add_shortcuts_without_add_perm(self):
        data = self.dashboard(staff_with_perms('priceview', 'pricing.view_priceobservation'))
        self.assertEqual(data['quick'], [])
        data = self.dashboard(staff_with_perms(
            'priceadd', 'pricing.view_priceobservation', 'pricing.add_priceobservation',
        ))
        self.assertEqual([item['label'] for item in data['quick']], ['ثبت قیمت تازه'])

    def test_audit_feed_requires_permission(self):
        RedirectRule.objects.create(old_path='/feed/', destination='/steel/')
        self.assertEqual(self.dashboard(staff_with_perms('a1'))['audit'], [])
        self.assertTrue(self.dashboard(staff_with_perms('a2', 'core.view_auditlog'))['audit'])

    def test_dashboard_renders_for_superuser(self):
        self.client.force_login(User.objects.create_superuser(username='boss', password='x-Strong-Pass-91'))
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'داشبورد مدیریت')
