"""Lightweight audit trail for business-critical models.

A middleware stores the current user/IP in a context variable; model signals
record create/update/delete with the changed field values. Secrets and long
text bodies are never stored verbatim.
"""

import contextvars
import json
from decimal import Decimal

from django.apps import apps
from django.db.models.signals import post_delete, post_save, pre_save

_current = contextvars.ContextVar('ariaa_audit_actor', default=(None, None))

AUDITED_MODELS = (
    'catalog.Category', 'catalog.Manufacturer', 'catalog.Product', 'catalog.ProductVariant',
    'pricing.PriceObservation', 'pricing.StockObservation', 'pricing.ShippingRate', 'pricing.InventoryLocation',
    'content.Article', 'content.CompanyPage', 'content.FAQ', 'content.MarketNews',
    'orders.PreInvoice', 'orders.Order', 'orders.PaymentRecord',
    'marketplace.MarketplaceListing', 'inquiries.CompanyContactDetails', 'core.RedirectRule',
)
SKIP_FIELDS = {'updated_at', 'created_at', 'last_login', 'password'}
LONG_TEXT = 160


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .throttle import client_ip

        user = getattr(request, 'user', None)
        token = _current.set((
            user if user is not None and user.is_authenticated else None,
            client_ip(request) or None,
        ))
        try:
            return self.get_response(request)
        finally:
            _current.reset(token)


def _plain(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    text = str(value)
    return text if len(text) <= LONG_TEXT else f'{text[:LONG_TEXT]}… ({len(text)} نویسه)'


def _snapshot(instance):
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in SKIP_FIELDS:
            continue
        data[field.attname] = _plain(getattr(instance, field.attname))
    return data


def _write(instance, action, changes):
    from .models import AuditLog

    actor, ip = _current.get()
    try:
        json.dumps(changes)
    except (TypeError, ValueError):
        changes = {key: str(value) for key, value in changes.items()}
    AuditLog.objects.create(
        actor=actor, action=action, model_label=instance._meta.label,
        object_id=str(instance.pk)[:64], object_repr=str(instance)[:200], changes=changes, ip_address=ip,
    )


def _pre_save(sender, instance, **kwargs):
    if instance.pk:
        old = sender.objects.filter(pk=instance.pk).first()
        instance._audit_before = _snapshot(old) if old else None


def _post_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    after = _snapshot(instance)
    if created:
        _write(instance, 'create', after)
        return
    before = getattr(instance, '_audit_before', None) or {}
    diff = {key: [before.get(key), value] for key, value in after.items() if before.get(key) != value}
    if diff:
        _write(instance, 'update', diff)


def _post_delete(sender, instance, **kwargs):
    _write(instance, 'delete', _snapshot(instance))


def connect():
    for label in AUDITED_MODELS:
        model = apps.get_model(label)
        uid = f'ariaa-audit-{label}'
        pre_save.connect(_pre_save, sender=model, dispatch_uid=f'{uid}-pre')
        post_save.connect(_post_save, sender=model, dispatch_uid=f'{uid}-post')
        post_delete.connect(_post_delete, sender=model, dispatch_uid=f'{uid}-del')
