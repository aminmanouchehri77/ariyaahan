import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.models import CustomerProfile
from catalog.models import ProductVariant

from .cart import Cart, CartError
from .models import ProjectList, ProjectListItem
from .projects import project_lines

MAX_PROJECTS = 30
MAX_ITEMS = 80


def _profile_or_404(request):
    profile = CustomerProfile.objects.filter(user=request.user).first()
    if profile is None:
        raise Http404
    return profile


def _quantity(raw):
    try:
        return Cart.parse_quantity(raw)
    except CartError as error:
        raise ValueError(str(error)) from None


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def project_list(request):
    profile = _profile_or_404(request)
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()[:120]
        if not title:
            messages.error(request, 'نام پروژه را وارد کنید.')
        elif profile.projects.count() >= MAX_PROJECTS:
            messages.error(request, 'حداکثر تعداد پروژه‌های قابل ذخیره پر شده است.')
        else:
            project = ProjectList.objects.create(profile=profile, title=title, note=request.POST.get('note', '').strip()[:300])
            messages.success(request, f'پروژهٔ «{project.title}» ساخته شد.')
            return redirect('orders:project_detail', public_id=project.public_id)
        return redirect('orders:project_list')
    projects = profile.projects.prefetch_related('items').all()
    return render(request, 'orders/project_list.html', {'projects': projects})


@login_required
@never_cache
@require_GET
def project_detail(request, public_id):
    profile = _profile_or_404(request)
    project = get_object_or_404(ProjectList, public_id=public_id, profile=profile)
    return render(request, 'orders/project_detail.html', {'project': project, 'owner': True, **project_lines(project)})


@never_cache
@require_GET
def project_shared(request, public_id):
    """Read-only view of a project shared by its owner (e.g. with a site engineer)."""
    project = get_object_or_404(ProjectList, public_id=public_id, is_shared=True)
    response = render(request, 'orders/project_detail.html', {'project': project, 'owner': False, **project_lines(project)})
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@login_required
@require_POST
def project_update(request, public_id):
    profile = _profile_or_404(request)
    project = get_object_or_404(ProjectList, public_id=public_id, profile=profile)
    action = request.POST.get('action')
    if action == 'delete':
        project.delete()
        messages.info(request, 'پروژه حذف شد.')
        return redirect('orders:project_list')
    if action == 'share':
        project.is_shared = not project.is_shared
        project.save(update_fields=('is_shared', 'updated_at'))
        messages.success(request, 'پیوند اشتراک فعال شد.' if project.is_shared else 'اشتراک پروژه غیرفعال شد.')
    elif action == 'rename':
        title = request.POST.get('title', '').strip()[:120]
        if title:
            project.title = title
            project.note = request.POST.get('note', '').strip()[:300]
            project.save(update_fields=('title', 'note', 'updated_at'))
            messages.success(request, 'مشخصات پروژه ذخیره شد.')
    elif action == 'to_cart':
        cart = Cart(request)
        added = 0
        for item in project.items.select_related('variant'):
            if not item.variant.is_active:
                continue
            try:
                cart.add(item.variant_id, item.quantity)
                added += 1
            except CartError as error:
                messages.warning(request, f'{item.variant}: {error}')
        messages.success(request, f'{added} قلم از پروژه به سبد پیش‌فاکتور اضافه شد.')
        return redirect('orders:cart')
    return redirect('orders:project_detail', public_id=project.public_id)


@login_required
@require_POST
def project_add_item(request, variant_id):
    profile = _profile_or_404(request)
    variant = get_object_or_404(
        ProductVariant, pk=variant_id, is_active=True, product__is_active=True, product__category__is_active=True,
    )
    try:
        quantity = _quantity(request.POST.get('quantity', '1'))
    except ValueError as error:
        messages.error(request, str(error))
        return redirect(variant.product.get_absolute_url())
    project_id = request.POST.get('project', '')
    if project_id and project_id != 'new':
        try:
            project_uuid = uuid.UUID(project_id)
        except ValueError:
            raise Http404 from None
        project = get_object_or_404(ProjectList, public_id=project_uuid, profile=profile)
    else:
        if profile.projects.count() >= MAX_PROJECTS:
            messages.error(request, 'حداکثر تعداد پروژه‌ها پر شده است.')
            return redirect(variant.product.get_absolute_url())
        title = request.POST.get('title', '').strip()[:120] or 'پروژهٔ جدید'
        project = ProjectList.objects.create(profile=profile, title=title)
    if project.items.count() >= MAX_ITEMS and not project.items.filter(variant=variant).exists():
        messages.error(request, 'ظرفیت اقلام این پروژه پر شده است.')
        return redirect(variant.product.get_absolute_url())
    item, created = ProjectListItem.objects.get_or_create(project=project, variant=variant, defaults={'quantity': quantity})
    if not created:
        item.quantity = quantity
        item.save(update_fields=('quantity',))
    project.save(update_fields=('updated_at',))
    messages.success(request, f'«{variant.product.name} — {variant.name}» در پروژهٔ «{project.title}» ذخیره شد.')
    return redirect('orders:project_detail', public_id=project.public_id)


@login_required
@require_POST
def project_item_update(request, public_id, item_id):
    profile = _profile_or_404(request)
    item = get_object_or_404(ProjectListItem, pk=item_id, project__public_id=public_id, project__profile=profile)
    if request.POST.get('action') == 'remove':
        item.delete()
        messages.info(request, 'قلم از پروژه حذف شد.')
    else:
        try:
            item.quantity = _quantity(request.POST.get('quantity'))
        except ValueError as error:
            messages.error(request, str(error))
        else:
            item.note = request.POST.get('note', item.note).strip()[:160]
            item.save(update_fields=('quantity', 'note'))
            messages.success(request, 'مقدار به‌روز شد.')
    return redirect('orders:project_detail', public_id=public_id)
