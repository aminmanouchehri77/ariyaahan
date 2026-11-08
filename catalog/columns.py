"""Product-family specific specification columns for price tables.

Each root category gets the columns buyers actually compare for that family,
mapped onto the generic ProductVariant fields.
"""

FIELD_SIZE = 'size'
FIELD_GRADE = 'grade'
FIELD_STANDARD = 'standard'
FIELD_DIMENSIONS = 'dimensions'
FIELD_WEIGHT = 'weight_per_unit_kg'

FAMILY_COLUMNS = {
    'rebar': (('سایز (mm)', FIELD_SIZE), ('گرید', FIELD_GRADE), ('استاندارد', FIELD_STANDARD), ('وزن شاخه (kg)', FIELD_WEIGHT)),
    'beam': (('نمره', FIELD_SIZE), ('طول / ابعاد', FIELD_DIMENSIONS), ('آنالیز', FIELD_GRADE), ('وزن شاخه (kg)', FIELD_WEIGHT)),
    'steel-sheet': (('ضخامت', FIELD_SIZE), ('عرض × طول', FIELD_DIMENSIONS), ('گرید', FIELD_GRADE), ('استاندارد', FIELD_STANDARD)),
    'pipe': (('قطر', FIELD_SIZE), ('ضخامت / ابعاد', FIELD_DIMENSIONS), ('استاندارد', FIELD_STANDARD), ('وزن شاخه (kg)', FIELD_WEIGHT)),
    'profiles': (('ابعاد مقطع', FIELD_SIZE), ('ضخامت', FIELD_DIMENSIONS), ('گرید', FIELD_GRADE), ('وزن شاخه (kg)', FIELD_WEIGHT)),
    'angles-channels': (('نمره', FIELD_SIZE), ('ضخامت / ابعاد', FIELD_DIMENSIONS), ('استاندارد', FIELD_STANDARD), ('وزن شاخه (kg)', FIELD_WEIGHT)),
    'wire-products': (('قطر / نوع', FIELD_SIZE), ('ابعاد چشمه', FIELD_DIMENSIONS), ('گرید', FIELD_GRADE)),
    'billets': (('مقطع', FIELD_SIZE), ('آنالیز', FIELD_GRADE), ('ابعاد', FIELD_DIMENSIONS)),
    'raw-materials': (('نوع', FIELD_SIZE), ('آنالیز / عیار', FIELD_GRADE), ('دانه‌بندی', FIELD_DIMENSIONS)),
    'ferroalloy': (('نوع', FIELD_SIZE), ('آنالیز / عیار', FIELD_GRADE), ('دانه‌بندی', FIELD_DIMENSIONS)),
}
DEFAULT_COLUMNS = (('سایز', FIELD_SIZE), ('گرید', FIELD_GRADE), ('استاندارد', FIELD_STANDARD))


def root_slug(category):
    cursor, guard = category, 0
    while cursor.parent_id and guard < 10:
        cursor, guard = cursor.parent, guard + 1
    return cursor.slug


def columns_for(category):
    return FAMILY_COLUMNS.get(root_slug(category), DEFAULT_COLUMNS)


def spec_cells(variant, columns):
    cells = []
    for label, field in columns:
        value = getattr(variant, field, '')
        if field == FIELD_WEIGHT and value is not None and value != '':
            value = format(value.normalize(), 'f')
        cells.append({'label': label, 'value': value if value not in (None, '') else '—'})
    return cells
