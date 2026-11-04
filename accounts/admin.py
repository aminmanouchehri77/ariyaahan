from django.contrib import admin

from .models import CustomerAddress, CustomerNotification, CustomerProfile, PriceAlert, PushSubscription


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ('mobile', 'full_name', 'allow_price_notifications', 'created_at')
    search_fields = ('mobile', 'full_name', 'user__username')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(CustomerAddress)
class CustomerAddressAdmin(admin.ModelAdmin):
    list_display = ('title', 'profile', 'recipient', 'city', 'is_default', 'updated_at')
    list_filter = ('province', 'city', 'is_default')
    search_fields = ('profile__mobile', 'recipient', 'city', 'postal_code', 'address')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PriceAlert)
class PriceAlertAdmin(admin.ModelAdmin):
    list_display = ('profile', 'variant', 'direction', 'target_amount', 'currency', 'price_basis', 'is_active', 'last_notified_at')
    list_filter = ('direction', 'currency', 'price_basis', 'is_active')
    search_fields = ('profile__mobile', 'variant__product__name', 'variant__name')
    readonly_fields = ('created_at', 'last_notified_at')


@admin.register(CustomerNotification)
class CustomerNotificationAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'profile', 'kind', 'title', 'is_read')
    list_filter = ('kind', 'is_read', 'created_at')
    search_fields = ('profile__mobile', 'title', 'body')
    readonly_fields = ('profile', 'kind', 'title', 'body', 'target_url', 'price_alert', 'price_observation', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('profile', 'endpoint_hash', 'created_at', 'updated_at')
    search_fields = ('profile__mobile', 'endpoint_hash')
    readonly_fields = ('profile', 'endpoint_hash', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
