"""
Notifications Django Admin Configuration.
"""

from django.contrib import admin

from .models import Notification, NotificationTemplate, UserNotificationPreference


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ["template_key", "name", "channel", "is_active", "updated_at"]
    list_filter = ["channel", "is_active"]
    search_fields = ["template_key", "name", "subject"]


@admin.register(UserNotificationPreference)
class UserNotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "channel", "is_enabled", "updated_at"]
    list_filter = ["channel", "is_enabled"]
    search_fields = ["user__phone_number"]
    raw_id_fields = ["user"]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["user", "channel", "title", "status", "sent_at", "created_at"]
    list_filter = ["channel", "status"]
    search_fields = ["user__phone_number", "title", "body"]
    raw_id_fields = ["user", "template"]
    readonly_fields = ["id", "created_at", "sent_at", "read_at"]

    def has_add_permission(self, request):
        return False
