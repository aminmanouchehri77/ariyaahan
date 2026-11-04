import json


def breadcrumb_schema(request, items):
    elements = []
    for position, (name, url) in enumerate(items, start=1):
        element = {'@type': 'ListItem', 'position': position, 'name': name}
        if url:
            element['item'] = request.build_absolute_uri(url)
        elements.append(element)
    data = {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': elements}
    return json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
