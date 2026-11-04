from django.contrib import admin

from .models import RedirectRule


@admin.register(RedirectRule)
class RedirectRuleAdmin(admin.ModelAdmin):
    list_display = ('old_path', 'destination', 'status_code', 'is_active', 'updated_at')
    list_filter = ('status_code', 'is_active', 'updated_at')
    search_fields = ('old_path', 'destination', 'note')
    readonly_fields = ('updated_at',)
