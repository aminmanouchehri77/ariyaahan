"""Security response headers not covered by Django's own middleware."""

from django.conf import settings


class PermissionsPolicyMiddleware:
    """Add a restrictive Permissions-Policy header (browser feature gating)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        policy = getattr(settings, 'PERMISSIONS_POLICY', '')
        if policy and 'Permissions-Policy' not in response:
            response['Permissions-Policy'] = policy
        return response
