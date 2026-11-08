"""Small per-client submission throttle for public forms.

Uses Django's cache so it works with any configured backend. With the default
local-memory cache the limit is per process, which is still an effective brake
on scripted spam; configure a shared cache (Redis/Memcached) in production.
"""

import hashlib

from django.conf import settings
from django.core.cache import cache


def _client_key(request, scope):
    address = request.META.get('REMOTE_ADDR', '') or 'unknown'
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
