from django.db import transaction

from accounts.models import CustomerProfile

from .models import ProductVariant, SavedComparison, SavedComparisonItem


COMPARE_SESSION_KEY = 'ariaa_compare_variants'
COMPARE_LIMIT = 4


def profile_for_request(request):
    if not request.user.is_authenticated:
        return None
    return CustomerProfile.objects.filter(user=request.user).first()


def get_variant_ids(request):
    profile = profile_for_request(request)
    if profile:
        comparison = SavedComparison.objects.filter(profile=profile).first()
        if comparison:
            return list(comparison.items.values_list('variant_id', flat=True)[:COMPARE_LIMIT])
    raw_ids = request.session.get(COMPARE_SESSION_KEY, [])
    return [int(value) for value in raw_ids if str(value).isdigit()][:COMPARE_LIMIT]


def add_variant(request, variant):
    profile = profile_for_request(request)
    if not profile:
        ids = [str(value) for value in request.session.get(COMPARE_SESSION_KEY, []) if str(value).isdigit()]
        key = str(variant.pk)
        if key in ids:
            return 'exists'
        if len(ids) >= COMPARE_LIMIT:
            return 'full'
        request.session[COMPARE_SESSION_KEY] = ids + [key]
        return 'added'

    with transaction.atomic():
        comparison, _ = SavedComparison.objects.get_or_create(profile=profile)
        comparison = SavedComparison.objects.select_for_update().get(pk=comparison.pk)
        items = comparison.items.all()
        if items.filter(variant=variant).exists():
            return 'exists'
        count = items.count()
        if count >= COMPARE_LIMIT:
            return 'full'
        SavedComparisonItem.objects.create(comparison=comparison, variant=variant, position=count)
        return 'added'


def remove_variant(request, variant_id):
    profile = profile_for_request(request)
    if profile:
        comparison = SavedComparison.objects.filter(profile=profile).first()
        if comparison:
            with transaction.atomic():
                comparison = SavedComparison.objects.select_for_update().get(pk=comparison.pk)
                comparison.items.filter(variant_id=variant_id).delete()
                for position, item in enumerate(comparison.items.order_by('position', 'added_at', 'pk')):
                    if item.position != position:
                        SavedComparisonItem.objects.filter(pk=item.pk).update(position=position)
            return
    ids = [str(value) for value in request.session.get(COMPARE_SESSION_KEY, []) if str(value).isdigit()]
    request.session[COMPARE_SESSION_KEY] = [value for value in ids if value != str(variant_id)]


def merge_session_comparison(profile, session):
    raw_ids = session.get(COMPARE_SESSION_KEY, [])
    valid_ids = [int(value) for value in raw_ids if str(value).isdigit()]
    if not valid_ids:
        return
    variant_ids = list(ProductVariant.objects.filter(
        pk__in=valid_ids,
        is_active=True,
        product__is_active=True,
        product__category__is_active=True,
    ).values_list('pk', flat=True))
    ordered_ids = [variant_id for variant_id in valid_ids if variant_id in set(variant_ids)]
    with transaction.atomic():
        comparison, _ = SavedComparison.objects.get_or_create(profile=profile)
        comparison = SavedComparison.objects.select_for_update().get(pk=comparison.pk)
        existing_ids = set(comparison.items.values_list('variant_id', flat=True))
        count = len(existing_ids)
        for variant_id in ordered_ids:
            if variant_id in existing_ids or count >= COMPARE_LIMIT:
                continue
            SavedComparisonItem.objects.create(
                comparison=comparison,
                variant_id=variant_id,
                position=count,
            )
            existing_ids.add(variant_id)
            count += 1
    session.pop(COMPARE_SESSION_KEY, None)
