from django.contrib import admin

from .models import NewsletterSubscriber


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ('email', 'is_confirmed', 'is_active', 'created_at', 'confirmed_at')
    list_filter = ('is_confirmed', 'is_active', 'created_at')
    search_fields = ('email',)
    readonly_fields = ('created_at', 'confirmed_at', 'unsubscribed_at')
    # The token is a credential for confirm/unsubscribe; not browsable.
    exclude = ('token',)

    def has_add_permission(self, request):
        return False
