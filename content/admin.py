from django.contrib import admin
from django.utils import timezone

from .models import Article, ArticleComment, ArticleTag, CompanyPage, CompanyRequest, FAQ, MarketNews, MediaItem, ProductQuestion, ProductReview


@admin.register(CompanyPage)
class CompanyPageAdmin(admin.ModelAdmin):
    list_display = ('title', 'kind', 'slug', 'is_published', 'updated_at')
    list_filter = ('kind', 'is_published')
    search_fields = ('title', 'slug', 'summary', 'body')
    readonly_fields = ('updated_at',)
    fieldsets = (
        ('محتوای صفحه', {'fields': ('kind', 'slug', 'title', 'summary', 'body', 'is_published')}),
        ('بهینه‌سازی جست‌وجو', {'fields': ('seo_title', 'meta_description', 'updated_at')}),
    )


@admin.register(ArticleTag)
class ArticleTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    search_fields = ('name', 'slug')


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'status', 'author_name', 'published_at', 'updated_at')
    list_filter = ('status', 'category', 'published_at', 'tags')
    search_fields = ('title', 'slug', 'excerpt', 'body', 'author_name')
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ('tags', 'related_products')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'published_at'

    def save_model(self, request, obj, form, change):
        if obj.status == Article.Status.PUBLISHED and not obj.published_at:
            obj.published_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(MediaItem)
class MediaItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'kind', 'is_published', 'published_at')
    list_filter = ('kind', 'is_published', 'published_at')
    search_fields = ('title', 'slug', 'summary', 'description')
    prepopulated_fields = {'slug': ('title',)}

    def save_model(self, request, obj, form, change):
        if obj.is_published and not obj.published_at:
            obj.published_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ('question', 'section', 'sort_order', 'is_active', 'updated_at')
    list_filter = ('section', 'is_active')
    search_fields = ('question', 'answer')
    ordering = ('sort_order', 'pk')
    readonly_fields = ('updated_at',)


@admin.register(CompanyRequest)
class CompanyRequestAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'kind', 'name', 'mobile', 'subject', 'status', 'assigned_to')
    list_filter = ('kind', 'status', 'created_at')
    search_fields = ('public_id', 'name', 'mobile', 'email', 'company_name', 'subject', 'destination_country')
    readonly_fields = ('public_id', 'consent', 'source_path', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    list_per_page = 30
    fieldsets = (
        ('درخواست', {
            'fields': ('public_id', 'kind', 'status', 'name', 'mobile', 'email', 'company_name',
                       'subject', 'destination_country', 'product_interest', 'experience_years', 'message', 'consent'),
        }),
        ('پیگیری داخلی', {'fields': ('assigned_to', 'admin_note', 'source_path', 'created_at', 'updated_at')}),
    )


@admin.register(MarketNews)
class MarketNewsAdmin(admin.ModelAdmin):
    list_display = ('published_at', 'trend', 'variant', 'previous_amount', 'current_amount', 'change_percent', 'delivery_location')
    list_filter = ('trend', 'currency', 'published_at')
    search_fields = ('headline', 'variant__product__name', 'variant__name', 'delivery_location')
    readonly_fields = tuple(field.name for field in MarketNews._meta.fields)
    date_hierarchy = 'published_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProductQuestion)
class ProductQuestionAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'product', 'display_name', 'status', 'reviewer', 'published_at')
    list_filter = ('status', 'created_at', 'published_at')
    search_fields = ('product__name', 'display_name', 'question', 'answer')
    readonly_fields = ('product', 'profile', 'display_name', 'question', 'created_at', 'updated_at', 'reviewer', 'published_at')
    date_hierarchy = 'created_at'
    fields = ('product', 'profile', 'display_name', 'question', 'answer', 'status', 'reviewer', 'published_at', 'created_at', 'updated_at')

    def save_model(self, request, obj, form, change):
        obj.reviewer = request.user
        if obj.status in (ProductQuestion.Status.PUBLISHED, ProductQuestion.Status.ANSWERED) and not obj.published_at:
            obj.published_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'product', 'display_name', 'rating', 'status', 'reviewer', 'published_at')
    list_filter = ('status', 'rating', 'created_at', 'published_at')
    search_fields = ('product__name', 'display_name', 'title', 'review')
    readonly_fields = ('product', 'profile', 'display_name', 'rating', 'title', 'review', 'reviewer', 'created_at', 'updated_at', 'published_at')
    date_hierarchy = 'created_at'
    fields = ('product', 'profile', 'display_name', 'rating', 'title', 'review', 'status', 'reviewer', 'published_at', 'created_at', 'updated_at')

    def save_model(self, request, obj, form, change):
        obj.reviewer = request.user
        if obj.status == ProductReview.Status.APPROVED and not obj.published_at:
            obj.published_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(ArticleComment)
class ArticleCommentAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'article', 'display_name', 'status', 'reviewer', 'published_at')
    list_filter = ('status', 'created_at', 'published_at')
    search_fields = ('article__title', 'display_name', 'comment')
    readonly_fields = ('article', 'profile', 'display_name', 'comment', 'reviewer', 'created_at', 'updated_at', 'published_at')
    date_hierarchy = 'created_at'
    fields = ('article', 'profile', 'display_name', 'comment', 'status', 'reviewer', 'published_at', 'created_at', 'updated_at')

    def save_model(self, request, obj, form, change):
        obj.reviewer = request.user
        if obj.status == ArticleComment.Status.APPROVED and not obj.published_at:
            obj.published_at = timezone.now()
        super().save_model(request, obj, form, change)
