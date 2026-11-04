from django.db import models
from django.urls import reverse


class Category(models.Model):
    name = models.CharField('نام دسته', max_length=120)
    slug = models.SlugField('شناسهٔ نشانی', max_length=140, unique=True)
    parent = models.ForeignKey(
        'self',
        verbose_name='دستهٔ والد',
        related_name='children',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    description = models.CharField('توضیح کوتاه', max_length=240, blank=True)
    icon_key = models.CharField('کلید آیکون', max_length=32, blank=True)
    sort_order = models.PositiveSmallIntegerField('ترتیب نمایش', default=0)
    is_active = models.BooleanField('فعال', default=True)
    seo_title = models.CharField('عنوان سئو', max_length=180, blank=True)
    meta_description = models.CharField('توضیح متا', max_length=300, blank=True)
    created_at = models.DateTimeField('زمان ایجاد', auto_now_add=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'دستهٔ کالا'
        verbose_name_plural = 'دسته‌های کالا'
        ordering = ('sort_order', 'name')
        indexes = [
            models.Index(fields=('parent', 'is_active', 'sort_order'), name='cat_parent_active_idx'),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('catalog:category_detail', kwargs={'slug': self.slug})


class Manufacturer(models.Model):
    name = models.CharField('نام کارخانه', max_length=140, unique=True)
    slug = models.SlugField('شناسهٔ نشانی', max_length=160, unique=True)
    is_active = models.BooleanField('فعال', default=True)

    class Meta:
        verbose_name = 'کارخانه'
        verbose_name_plural = 'کارخانه‌ها'
        ordering = ('name',)

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        verbose_name='دسته',
        related_name='products',
        on_delete=models.PROTECT,
    )
    name = models.CharField('نام محصول', max_length=180)
    slug = models.SlugField('شناسهٔ نشانی', max_length=200, unique=True)
    summary = models.CharField('خلاصه', max_length=300, blank=True)
    description = models.TextField('توضیحات', blank=True)
    is_active = models.BooleanField('فعال', default=True)
    seo_title = models.CharField('عنوان سئو', max_length=180, blank=True)
    meta_description = models.CharField('توضیح متا', max_length=300, blank=True)
    created_at = models.DateTimeField('زمان ایجاد', auto_now_add=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'محصول'
        verbose_name_plural = 'محصولات'
        ordering = ('name',)
        indexes = [
            models.Index(fields=('category', 'is_active', 'name'), name='prod_category_active_idx'),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('catalog:product_detail', kwargs={'slug': self.slug})


class ProductVariant(models.Model):
    class Unit(models.TextChoices):
        KILOGRAM = 'kg', 'کیلوگرم'
        TONNE = 'ton', 'تن'
        PIECE = 'piece', 'شاخه / عدد'
        BUNDLE = 'bundle', 'بندیل'
        SHEET = 'sheet', 'شیت'
        METER = 'meter', 'متر'

    product = models.ForeignKey(
        Product,
        verbose_name='محصول',
        related_name='variants',
        on_delete=models.CASCADE,
    )
    manufacturer = models.ForeignKey(
        Manufacturer,
        verbose_name='کارخانه',
        related_name='variants',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    sku = models.CharField('کد کالا', max_length=80, unique=True, null=True, blank=True)
    name = models.CharField('عنوان گونه', max_length=180)
    size = models.CharField('سایز', max_length=80, blank=True)
    grade = models.CharField('گرید', max_length=80, blank=True)
    standard = models.CharField('استاندارد', max_length=100, blank=True)
    dimensions = models.CharField('ابعاد', max_length=120, blank=True)
    unit = models.CharField('واحد فروش', max_length=12, choices=Unit.choices, default=Unit.TONNE)
    weight_per_unit_kg = models.DecimalField(
        'وزن واحد (کیلوگرم)',
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
    )
    is_active = models.BooleanField('فعال', default=True)
    sort_order = models.PositiveSmallIntegerField('ترتیب نمایش', default=0)
    created_at = models.DateTimeField('زمان ایجاد', auto_now_add=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'گونهٔ محصول'
        verbose_name_plural = 'گونه‌های محصول'
        ordering = ('sort_order', 'name')
        indexes = [
            models.Index(fields=('product', 'is_active', 'sort_order'), name='variant_product_active_idx'),
            models.Index(fields=('manufacturer', 'size', 'grade'), name='variant_specs_idx'),
        ]

    def __str__(self):
        return f'{self.product.name} — {self.name}'
