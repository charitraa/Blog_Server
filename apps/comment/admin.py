from django.contrib import admin

from .models import Comment


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('short_content', 'author', 'post', 'parent', 'is_edited', 'created_at')
    list_filter = ('is_edited', 'created_at')
    search_fields = ('content', 'author__email', 'author__username', 'post__title')
    raw_id_fields = ('post', 'author', 'parent')
    readonly_fields = ('created_at', 'updated_at')
    list_select_related = ('author', 'post', 'parent')
    date_hierarchy = 'created_at'

    @admin.display(description='comment')
    def short_content(self, obj):
        return obj.content[:70] + ('…' if len(obj.content) > 70 else '')
