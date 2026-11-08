import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


class CompanyPage(models.Model):
    class Kind(models.TextChoices):
        ABOUT = 'about', 'دربارهٔ ما'
        EXPORT = 'export', 'صادرات'
        CAREERS = 'careers', 'فرصت‌های شغلی'
        SHIPPING = 'shipping', 'راهنمای تحویل'
        PRIVACY = 'privacy', 'حریم خصوصی'
        TERMS = 'terms', 'شرایط استفاده'

    kind = models.CharField('نوع صفحه', max_length=16, choices=Kind.choices, unique=True)
    slug = models.SlugField('شناسهٔ نشانی', max_length=100, unique=True)
    title = models.CharField('عنوان', max_length=180)
    summary = models.CharField('خلاصه', max_length=300, blank=True)
    body = models.TextField('متن صفحه', blank=True)
    seo_title = models.CharField('عنوان SEO', max_length=180, blank=True)
    meta_description = models.CharField('توضیح متا', max_length=300, blank=True)
    is_published = models.BooleanField('منتشرشده', default=False)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'صفحهٔ شرکت'
        verbose_name_plural = 'صفحه‌های شرکت'
        ordering = ('kind',)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        route_names = {
            self.Kind.ABOUT: 'content:about',
            self.Kind.SHIPPING: 'content:shipping',
            self.Kind.PRIVACY: 'content:privacy',
            self.Kind.TERMS: 'content:terms',
        }
        route_name = route_names.get(self.kind)
        if route_name:
            return reverse(route_name)
        return reverse('content:page', kwargs={'slug': self.slug})


class ArticleTag(models.Model):
    name = models.CharField('نام برچسب', max_length=60, unique=True)
    slug = models.SlugField('شناسهٔ نشانی', max_length=80, unique=True)

    class Meta:
        verbose_name = 'برچسب مقاله'
        verbose_name_plural = 'برچسب‌های مقاله'
        ordering = ('name',)

    def __str__(self):
        return self.name


class Article(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'پیش‌نویس'
        PUBLISHED = 'published', 'منتشرشده'
        ARCHIVED = 'archived', 'بایگانی'

    title = models.CharField('عنوان', max_length=200)
    slug = models.SlugField('شناسهٔ نشانی', max_length=220, unique=True)
    excerpt = models.CharField('خلاصه', max_length=360)
    body = models.TextField('متن مقاله')
    category = models.CharField('دستهٔ محتوا', max_length=80, blank=True, db_index=True)
    tags = models.ManyToManyField(ArticleTag, verbose_name='برچسب‌ها', blank=True, related_name='articles')
    related_products = models.ManyToManyField(
        'catalog.Product', verbose_name='محصولات مرتبط', blank=True, related_name='related_articles',
    )
    author_name = models.CharField('نام نویسنده', max_length=120, blank=True)
    cover_image_url = models.URLField('نشانی تصویر شاخص', max_length=500, blank=True)
    status = models.CharField('وضعیت', max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    published_at = models.DateTimeField('زمان انتشار', null=True, blank=True, db_index=True)
    seo_title = models.CharField('عنوان SEO', max_length=180, blank=True)
    meta_description = models.CharField('توضیح متا', max_length=300, blank=True)
    created_at = models.DateTimeField('زمان ایجاد', auto_now_add=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'مقاله'
        verbose_name_plural = 'مقاله‌ها'
        ordering = ('-published_at', '-pk')
        indexes = [models.Index(fields=('status', '-published_at'), name='article_public_idx')]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('content:article_detail', kwargs={'slug': self.slug})


class MarketNews(models.Model):
    class Trend(models.TextChoices):
        RISING = 'rising', 'افزایشی'
        FALLING = 'falling', 'کاهشی'
        UNCHANGED = 'unchanged', 'بدون تغییر'

    price_observation = models.OneToOneField(
        'pricing.PriceObservation', verbose_name='ثبت قیمت تأییدشده', related_name='market_news',
        on_delete=models.PROTECT,
    )
    previous_observation = models.ForeignKey(
        'pricing.PriceObservation', verbose_name='ثبت مقایسه', related_name='market_news_as_previous',
        null=True, blank=True, on_delete=models.SET_NULL,
    )
    variant = models.ForeignKey(
        'catalog.ProductVariant', verbose_name='گونهٔ محصول', related_name='market_news', on_delete=models.PROTECT,
    )
    headline = models.CharField('تیتر خبر', max_length=240)
    summary = models.CharField('خلاصهٔ تغییر', max_length=500)
    trend = models.CharField('روند', max_length=12, choices=Trend.choices, db_index=True)
    previous_amount = models.DecimalField('مبلغ پیشین', max_digits=18, decimal_places=0)
    current_amount = models.DecimalField('مبلغ جدید', max_digits=18, decimal_places=0)
    currency = models.CharField('ارز', max_length=3, choices=(('IRR', 'ریال'), ('IRT', 'تومان'), ('USD', 'دلار')))
    price_basis = models.CharField('واحد قیمت', max_length=12)
    tax_included = models.BooleanField('مالیات در قیمت لحاظ شده', null=True, blank=True)
    delivery_location = models.CharField('محل تحویل', max_length=140, blank=True)
    change_percent = models.DecimalField('درصد تغییر', max_digits=9, decimal_places=2)
    published_at = models.DateTimeField('زمان انتشار', db_index=True)

    class Meta:
        verbose_name = 'خبر تغییر قیمت'
        verbose_name_plural = 'اخبار تغییر قیمت'
        ordering = ('-published_at', '-pk')
        indexes = [models.Index(fields=('trend', '-published_at'), name='market_news_trend_date_idx')]

    def __str__(self):
        return self.headline

    def get_absolute_url(self):
        return reverse('content:market_news_detail', kwargs={'pk': self.pk})


class ProductQuestion(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار بررسی'
        PUBLISHED = 'published', 'منتشرشده'
        ANSWERED = 'answered', 'پاسخ داده‌شده'
        REJECTED = 'rejected', 'ردشده'

    product = models.ForeignKey(
        'catalog.Product', verbose_name='محصول', related_name='questions', on_delete=models.CASCADE,
    )
    profile = models.ForeignKey(
        'accounts.CustomerProfile', verbose_name='حساب ثبت‌کننده', related_name='product_questions',
        null=True, blank=True, on_delete=models.SET_NULL,
    )
    display_name = models.CharField('نام نمایشی', max_length=80)
    question = models.TextField('پرسش', max_length=2000)
    answer = models.TextField('پاسخ مدیر', max_length=3000, blank=True)
    status = models.CharField('وضعیت', max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='بررسی‌کننده', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='reviewed_product_questions',
    )
    created_at = models.DateTimeField('زمان ثبت', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)
    published_at = models.DateTimeField('زمان انتشار', null=True, blank=True)

    class Meta:
        verbose_name = 'پرسش محصول'
        verbose_name_plural = 'پرسش‌های محصول'
        ordering = ('-published_at', '-pk')
        indexes = [models.Index(fields=('product', 'status', '-created_at'), name='product_question_pub_idx')]

    def __str__(self):
        return f'{self.product} — {self.display_name} — {self.get_status_display()}'


class ProductReview(models.Model):
    RATING_CHOICES = tuple((value, f'{value} از ۵') for value in range(1, 6))

    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار بررسی'
        APPROVED = 'approved', 'منتشرشده'
        REJECTED = 'rejected', 'ردشده'

    product = models.ForeignKey(
        'catalog.Product', verbose_name='محصول', related_name='reviews', on_delete=models.CASCADE,
    )
    profile = models.ForeignKey(
        'accounts.CustomerProfile', verbose_name='حساب ثبت‌کننده', related_name='product_reviews',
        on_delete=models.CASCADE,
    )
    display_name = models.CharField('نام نمایشی', max_length=80, default='مشتری تأییدشده')
    rating = models.PositiveSmallIntegerField('امتیاز', choices=RATING_CHOICES)
    title = models.CharField('عنوان دیدگاه', max_length=140, blank=True)
    review = models.TextField('دیدگاه', max_length=3000)
    status = models.CharField('وضعیت', max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='بررسی‌کننده', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='reviewed_product_reviews',
    )
    created_at = models.DateTimeField('زمان ثبت', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)
    published_at = models.DateTimeField('زمان انتشار', null=True, blank=True)

    class Meta:
        verbose_name = 'دیدگاه محصول'
        verbose_name_plural = 'دیدگاه‌های محصول'
        ordering = ('-published_at', '-pk')
        constraints = [
            models.UniqueConstraint(fields=('product', 'profile'), name='unique_customer_product_review'),
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name='valid_product_review_rating'),
        ]
        indexes = [models.Index(fields=('product', 'status', '-published_at'), name='product_review_pub_idx')]

    def __str__(self):
        return f'{self.product} — {self.rating}/5 — {self.get_status_display()}'


class ArticleComment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار بررسی'
        APPROVED = 'approved', 'منتشرشده'
        REJECTED = 'rejected', 'ردشده'

    article = models.ForeignKey(
        Article, verbose_name='مقاله', related_name='comments', on_delete=models.CASCADE,
    )
    profile = models.ForeignKey(
        'accounts.CustomerProfile', verbose_name='حساب ثبت‌کننده', related_name='article_comments',
        on_delete=models.CASCADE,
    )
    display_name = models.CharField('نام نمایشی', max_length=80, default='مشتری تأییدشده')
    comment = models.TextField('دیدگاه', max_length=2000)
    status = models.CharField('وضعیت', max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='بررسی‌کننده', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='reviewed_article_comments',
    )
    created_at = models.DateTimeField('زمان ثبت', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)
    published_at = models.DateTimeField('زمان انتشار', null=True, blank=True)

    class Meta:
        verbose_name = 'دیدگاه مقاله'
        verbose_name_plural = 'دیدگاه‌های مقاله'
        ordering = ('published_at', 'pk')
        indexes = [models.Index(fields=('article', 'status', 'published_at'), name='article_comment_pub_idx')]

    def __str__(self):
        return f'{self.article} — {self.display_name} — {self.get_status_display()}'


class MediaItem(models.Model):
    class Kind(models.TextChoices):
        VIDEO = 'video', 'ویدیو'
        PODCAST = 'podcast', 'پادکست'

    title = models.CharField('عنوان', max_length=180)
    slug = models.SlugField('شناسهٔ نشانی', max_length=200, unique=True)
    kind = models.CharField('نوع', max_length=8, choices=Kind.choices, db_index=True)
    summary = models.CharField('خلاصه', max_length=360, blank=True)
    description = models.TextField('توضیحات', blank=True)
    media_url = models.URLField('نشانی پخش یا منبع', max_length=500)
    cover_image_url = models.URLField('نشانی تصویر', max_length=500, blank=True)
    duration_seconds = models.PositiveIntegerField('مدت (ثانیه)', null=True, blank=True)
    is_published = models.BooleanField('منتشرشده', default=False, db_index=True)
    published_at = models.DateTimeField('زمان انتشار', null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = 'رسانه'
        verbose_name_plural = 'رسانه‌ها'
        ordering = ('-published_at', '-pk')

    def __str__(self):
        return f'{self.get_kind_display()} — {self.title}'


class FAQ(models.Model):
    question = models.CharField('پرسش', max_length=240)
    answer = models.TextField('پاسخ')
    section = models.CharField('بخش', max_length=80, blank=True, db_index=True)
    sort_order = models.PositiveSmallIntegerField('ترتیب', default=0)
    is_active = models.BooleanField('فعال', default=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'پرسش متداول'
        verbose_name_plural = 'پرسش‌های متداول'
        ordering = ('sort_order', 'pk')

    def __str__(self):
        return self.question


class CompanyRequest(models.Model):
    class Kind(models.TextChoices):
        COMPLAINT = 'complaint', 'شکایت'
        FEEDBACK = 'feedback', 'پیشنهاد و انتقاد'
        CAREER = 'career', 'درخواست همکاری'
        EXPORT = 'export', 'استعلام صادرات'

    class Status(models.TextChoices):
        NEW = 'new', 'جدید'
        REVIEWING = 'reviewing', 'در حال بررسی'
        ANSWERED = 'answered', 'پاسخ داده شد'
        CLOSED = 'closed', 'بسته شد'

    public_id = models.UUIDField('شناسهٔ پیگیری', default=uuid.uuid4, unique=True, editable=False)
    profile = models.ForeignKey(
        'accounts.CustomerProfile', verbose_name='حساب مشتری', related_name='company_requests',
        null=True, blank=True, on_delete=models.SET_NULL,
    )
    kind = models.CharField('نوع درخواست', max_length=12, choices=Kind.choices, db_index=True)
    name = models.CharField('نام', max_length=120)
    mobile = models.CharField(
        'شمارهٔ همراه', max_length=11,
        validators=[RegexValidator(r'^09\d{9}$', 'شمارهٔ همراه باید با ۰۹ شروع شود و ۱۱ رقم باشد.')],
    )
    email = models.EmailField('ایمیل', blank=True)
    company_name = models.CharField('نام شرکت', max_length=160, blank=True)
    subject = models.CharField('عنوان / موقعیت شغلی', max_length=180, blank=True)
    destination_country = models.CharField('کشور مقصد', max_length=100, blank=True)
    product_interest = models.CharField('محصول یا نیاز', max_length=240, blank=True)
    experience_years = models.PositiveSmallIntegerField('سابقهٔ کاری (سال)', null=True, blank=True)
    quantity_tonnes = models.DecimalField(
        'مقدار تقریبی (تن)', max_digits=12, decimal_places=3, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.001'))],
    )
    delivery_terms = models.CharField(
        'شرایط تحویل', max_length=8, blank=True,
        choices=[
            ('EXW', 'EXW — تحویل درب کارخانه'),
            ('FCA', 'FCA — تحویل به حمل‌کننده'),
            ('FOB', 'FOB — تحویل روی عرشهٔ کشتی'),
            ('CFR', 'CFR — هزینه و کرایه تا بندر مقصد'),
            ('CIF', 'CIF — هزینه، بیمه و کرایه تا بندر مقصد'),
            ('DAP', 'DAP — تحویل در مقصد'),
            ('OTHER', 'سایر / نیاز به مشاوره'),
        ],
    )
    message = models.TextField('شرح درخواست', max_length=5000)
    consent = models.BooleanField('رضایت تماس برای پیگیری', default=False)
    source_path = models.CharField('صفحهٔ مبدأ', max_length=255, blank=True)
    status = models.CharField('وضعیت پیگیری', max_length=12, choices=Status.choices, default=Status.NEW, db_index=True)
    admin_note = models.TextField('یادداشت داخلی', blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='مسئول پیگیری', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='assigned_company_requests',
    )
    created_at = models.DateTimeField('زمان ثبت', default=timezone.now, db_index=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    class Meta:
        verbose_name = 'درخواست شرکت'
        verbose_name_plural = 'درخواست‌های شرکت'
        ordering = ('-created_at', '-pk')
        indexes = [
            models.Index(fields=('kind', 'status', 'created_at'), name='company_req_status_idx'),
            models.Index(fields=('profile', 'status', 'created_at'), name='company_req_profile_idx'),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} — {self.name} — {self.created_at:%Y-%m-%d %H:%M}'
