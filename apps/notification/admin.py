from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['recipient', 'verb', 'actor', 'is_read', 'created_at']
    list_filter = ['verb', 'is_read', 'created_at']
    search_fields = ['recipient__username', 'recipient__email', 'actor__username']
    readonly_fields = ['id', 'created_at']
    raw_id_fields = ['recipient', 'actor', 'post', 'comment']
