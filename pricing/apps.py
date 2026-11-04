from django.apps import AppConfig


class PricingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pricing'
    verbose_name = 'قیمت و موجودی'

    def ready(self):
        from . import signals  # noqa: F401
