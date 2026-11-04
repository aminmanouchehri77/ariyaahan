from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


ROLE_MODELS = {
    'مدیر کاتالوگ': {
        'catalog': ('category', 'manufacturer', 'product', 'productvariant'),
    },
    'اپراتور قیمت و حمل': {
        'pricing': ('priceobservation', 'pricereviewevent', 'inventorylocation', 'stockobservation', 'shippingrate'),
    },
    'تحریریه محتوا': {
        'content': ('companypage', 'article', 'articletag', 'mediaitem', 'faq', 'marketnews', 'productquestion'),
    },
    'پشتیبانی مشتری': {
        'inquiries': ('inquiry',),
        'content': ('companyrequest',),
        'marketplace': ('marketplacelisting',),
        'accounts': ('customerprofile', 'customeraddress', 'customernotification'),
    },
    'فروش و سفارش': {
        'orders': ('preinvoice', 'preinvoiceitem', 'order', 'orderitem', 'orderstatusevent', 'paymentrecord'),
    },
}


class Command(BaseCommand):
    help = 'Create/update standard Django staff groups and their model permissions.'

    def handle(self, *args, **options):
        for group_name, apps_models in ROLE_MODELS.items():
            group, _ = Group.objects.get_or_create(name=group_name)
            permissions = []
            for app_label, model_names in apps_models.items():
                for model_name in model_names:
                    model = apps.get_model(app_label, model_name)
                    codenames = [f'{action}_{model_name}' for action in ('view', 'add', 'change')]
                    model_permissions = Permission.objects.filter(
                        content_type__app_label=app_label,
                        content_type__model=model._meta.model_name,
                        codename__in=codenames,
                    )
                    if model_name in {'pricereviewevent', 'orderstatusevent', 'paymentrecord', 'customernotification', 'marketnews'}:
                        model_permissions = model_permissions.filter(codename__startswith='view_')
                    permissions.extend(model_permissions)
            group.permissions.set(permissions)
            self.stdout.write(f'Updated staff role group ({len(permissions)} permissions).')
        self.stdout.write(self.style.SUCCESS('Staff role groups are ready; assign staff accounts to groups in Django admin.'))
