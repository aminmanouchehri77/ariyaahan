from django.contrib import admin

from .models import Category, Manufacturer, Product, ProductVariant


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'sort_order', 'is_active')
    list_filter = ('is_active', 'parent')
    search_fields = ('name', 'slug')
    fields = ('name', 'slug', 'parent', 'description', 'icon_key', 'sort_order', 'is_active', 'seo_title', 'meta_description')
    ordering = ('sort_order', 'name')


@admin.register(Manufacturer)
class ManufacturerAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug')
    fields = ('name', 'slug', 'is_active')


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = ('name', 'manufacturer', 'size', 'grade', 'standard', 'unit', 'is_active')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'is_active', 'updated_at')
    list_filter = ('is_active', 'category')
    search_fields = ('name', 'slug', 'summary', 'variants__size', 'variants__grade')
    fields = ('category', 'name', 'slug', 'summary', 'description', 'is_active', 'seo_title', 'meta_description')
    inlines = (ProductVariantInline,)


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('name', 'product', 'manufacturer', 'size', 'grade', 'unit', 'is_active')
    list_filter = ('is_active', 'product__category', 'manufacturer', 'unit')
    search_fields = ('name', 'sku', 'product__name', 'size', 'grade', 'standard')
