from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from catalog.models import ProductVariant
from accounts.models import CustomerProfile

from .cart import Cart, CartError
from .forms import CartQuantityForm, PreInvoiceForm
from .models import PreInvoice, PreInvoiceItem
from .services import build_cart_context, snapshot_line


@never_cache
@require_GET
def cart_detail(request):
    return render(request, 'orders/cart.html', build_cart_context(request))


@never_cache
@require_POST
def cart_add(request, variant_id):
    variant = get_object_or_404(
        ProductVariant,
        pk=variant_id,
        is_active=True,
        product__is_active=True,
        product__category__is_active=True,
    )
    form = CartQuantityForm(request.POST)
    if form.is_valid():
        try:
            Cart(request).add(variant.pk, form.cleaned_data['quantity'])
            messages.success(request, f'«{variant.product.name} — {variant.name}» به سبد اضافه شد.')
        except CartError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, 'مقدار کالا را بررسی و دوباره تلاش کنید.')
    return redirect('orders:cart')


@never_cache
@require_POST
def cart_update(request, variant_id):
    form = CartQuantityForm(request.POST)
    if form.is_valid():
        try:
            Cart(request).update(variant_id, form.cleaned_data['quantity'])
            messages.success(request, 'مقدار کالا در سبد به‌روز شد.')
        except (CartError, ValueError) as exc:
            messages.error(request, str(exc) or 'به‌روزرسانی سبد انجام نشد.')
    else:
        messages.error(request, 'مقدار واردشده معتبر نیست.')
    return redirect('orders:cart')


@never_cache
@require_POST
def cart_remove(request, variant_id):
    Cart(request).remove(variant_id)
    messages.info(request, 'کالا از سبد حذف شد.')
    return redirect('orders:cart')


@never_cache
@require_GET
def checkout(request):
    context = build_cart_context(request)
    if context['cart_is_empty']:
        messages.warning(request, 'برای ثبت پیش‌فاکتور ابتدا کالایی به سبد اضافه کنید.')
        return redirect('orders:cart')
    profile = CustomerProfile.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    context['form'] = PreInvoiceForm(initial={
        'customer_name': profile.full_name if profile else '',
        'mobile': profile.mobile if profile else '',
    }, addresses=profile.addresses.all() if profile else None)
    return render(request, 'orders/checkout.html', context)


@never_cache
@require_POST
def submit_preinvoice(request):
    context = build_cart_context(request)
    if context['cart_is_empty']:
        messages.warning(request, 'سبد خالی است؛ کالاها را دوباره انتخاب کنید.')
        return redirect('orders:cart')

    profile = CustomerProfile.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    addresses = profile.addresses.all() if profile else None
    form = PreInvoiceForm(request.POST, addresses=addresses)
    if not form.is_valid():
        context['form'] = form
        return render(request, 'orders/checkout.html', context)

    selected_address = form.cleaned_data['saved_address']
    address_values = {
        'delivery_recipient': selected_address.recipient if selected_address else form.cleaned_data['delivery_recipient'],
        'delivery_mobile': selected_address.mobile if selected_address else form.cleaned_data['delivery_mobile'],
        'delivery_province': selected_address.province if selected_address else form.cleaned_data['delivery_province'],
        'delivery_postal_code': selected_address.postal_code if selected_address else form.cleaned_data['delivery_postal_code'],
        'delivery_address': selected_address.address if selected_address else form.cleaned_data['delivery_address'],
        'delivery_note': selected_address.delivery_note if selected_address else form.cleaned_data['delivery_note'],
        'delivery_city': selected_address.city if selected_address else form.cleaned_data['delivery_city'],
    }

    with transaction.atomic():
        preinvoice = PreInvoice.objects.create(
            customer=profile,
            customer_name=form.cleaned_data['customer_name'],
            mobile=form.cleaned_data['mobile'],
            company_name=form.cleaned_data['company_name'],
            **address_values,
            customer_note=form.cleaned_data['customer_note'],
            status=(
                PreInvoice.Status.PENDING
                if all(line['price_is_usable'] for line in context['cart_lines'])
                else PreInvoice.Status.REVIEW
            ),
        )
        for line in context['cart_lines']:
            snapshot = snapshot_line(line)
            price_observation_id = snapshot.pop('price_observation_id')
            PreInvoiceItem.objects.create(
                preinvoice=preinvoice,
                price_observation_id=price_observation_id,
                **snapshot,
            )

    Cart(request).clear()
    messages.success(request, 'درخواست پیش‌فاکتور شما ثبت شد.')
    return redirect('orders:preinvoice_detail', public_id=preinvoice.public_id)


@require_GET
def preinvoice_detail(request, public_id):
    preinvoice = get_object_or_404(
        PreInvoice.objects.prefetch_related('items'),
        public_id=public_id,
    )
    lines = list(preinvoice.items.all())
    totals = {}
    for line in lines:
        if line.price_is_usable and line.line_total is not None:
            totals[line.currency] = totals.get(line.currency, 0) + line.line_total
    response = render(request, 'orders/preinvoice_detail.html', {
        'preinvoice': preinvoice,
        'preinvoice_items': lines,
        'currency_totals': totals,
    })
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    response['Referrer-Policy'] = 'no-referrer'
    return response
