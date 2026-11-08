from django.contrib import admin

from .models import AuditLog, RedirectRule


@admin.register(RedirectRule)
class RedirectRuleAdmin(admin.ModelAdmin):
    list_display = ('old_path', 'destination', 'status_code', 'is_active', 'updated_at')
    list_filter = ('status_code', 'is_active', 'updated_at')
    search_fields = ('old_path', 'destination', 'note')
    readonly_fields = ('updated_at',)



@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'model_label', 'object_repr')
    list_filter = ('action', 'model_label', 'created_at')
    search_fields = ('object_repr', 'object_id', 'actor__username')
    readonly_fields = [field.name for field in AuditLog._meta.fields]
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
