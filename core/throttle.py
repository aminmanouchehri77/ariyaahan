"""Small per-client submission throttle for public forms.

Uses Django's cache so it works with any configured backend. With the default
local-memory cache the limit is per process, which is still an effective brake
on scripted spam; configure a shared cache (Redis/Memcached) in production.
"""

import hashlib
import ipaddress

from django.conf import settings
from django.core.cache import cache


def _valid_ip(value):
    value = (value or '').strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return ''


def client_ip(request):
    """Return the client IP, trusting X-Forwarded-For only behind known proxies.

    With TRUSTED_PROXY_COUNT = N > 0, each trusted proxy appends the address it
    received the connection from, so the real client is the N-th entry from
    the right. Anything further left is client-controlled and ignored. With the
    default of 0 the header is never consulted, so it cannot be spoofed.
    """
    remote = _valid_ip(request.META.get('REMOTE_ADDR'))
    proxies = getattr(settings, 'TRUSTED_PROXY_COUNT', 0) or 0
    if proxies > 0:
        forwarded = [part.strip() for part in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if part.strip()]
        if len(forwarded) >= proxies:
            candidate = _valid_ip(forwarded[-proxies])
            if candidate:
                return candidate
    return remote


def _client_key(request, scope):
    address = client_ip(request) or 'unknown'
    digest = hashlib.sha256(f'{settings.SECRET_KEY}:{address}'.encode()).hexdigest()[:24]
    return f'form-throttle:{scope}:{digest}'


def submission_allowed(request, scope, *, limit=None, window=None):
    """Return False when the client exceeded `limit` submissions in `window` seconds."""
    limit = limit or getattr(settings, 'FORM_SUBMISSION_LIMIT', 6)
    window = window or getattr(settings, 'FORM_SUBMISSION_WINDOW', 600)
    key = _client_key(request, scope)
    added = cache.add(key, 1, timeout=window)
    if added:
        return True
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window)
        return True
    return count <= limit
