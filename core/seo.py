import json

from django.conf import settings


def canonical_origin(request):
    if settings.PUBLIC_SITE_URL:
        return settings.PUBLIC_SITE_URL.rstrip('/')
    return f'{request.scheme}://{request.get_host()}'


def canonical_url(request, path=None):
    path = path or request.path
    normalized_path = path.lstrip('/')
    return f'{canonical_origin(request)}/{normalized_path}'


def json_ld(data):
    return json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def breadcrumb_schema(request, items):
    elements = []
    for position, (name, url) in enumerate(items, start=1):
        element = {'@type': 'ListItem', 'position': position, 'name': name}
        if url:
            element['item'] = canonical_url(request, url)
        elements.append(element)
    data = {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': elements}
    return json_ld(data)
