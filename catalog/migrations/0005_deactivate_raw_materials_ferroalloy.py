"""Retire the «مواد اولیه» and «فروآلیاژ» groups from the public site.

The categories (and their sub-categories) are deactivated, not deleted, so
products, prices and history stay intact and they can be re-enabled from
the admin panel. Inactive categories disappear from the menu, home page,
catalogue, search and sitemap, and their pages return 404.
"""
from django.db import migrations

RETIRED = ('raw-materials', 'ferroalloy')


def _tree_ids(Category, slugs):
    ids = set(Category.objects.filter(slug__in=slugs).values_list('pk', flat=True))
    frontier = set(ids)
    while frontier:
        frontier = set(Category.objects.filter(parent_id__in=frontier).values_list('pk', flat=True)) - ids
        ids |= frontier
    return ids


def deactivate(apps, schema_editor):
    Category = apps.get_model('catalog', 'Category')
    Category.objects.filter(pk__in=_tree_ids(Category, RETIRED)).update(is_active=False)


def reactivate(apps, schema_editor):
    Category = apps.get_model('catalog', 'Category')
    Category.objects.filter(pk__in=_tree_ids(Category, RETIRED)).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [('catalog', '0004_seed_subcategories')]
    operations = [migrations.RunPython(deactivate, reactivate)]
