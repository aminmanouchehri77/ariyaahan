from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'هستهٔ سایت'

    def ready(self):
        from . import admin_jalali, audit

        audit.connect()
        admin_jalali.patch()
