from django.contrib import admin

from .models import Comment, CommentReport


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


@admin.register(CommentReport)
class CommentReportAdmin(admin.ModelAdmin):
    """The moderation queue. Acting on a report is what hides a comment."""

    list_display = ['comment', 'reason', 'reporter', 'status', 'created_at']
    list_filter = ['status', 'reason', 'created_at']
    search_fields = ['comment__content', 'reporter__username', 'detail']
    raw_id_fields = ['comment', 'reporter']
    readonly_fields = ['id', 'created_at']
    actions = ['hide_comments', 'dismiss_reports']

    @admin.action(description='Hide the reported comments and close the reports')
    def hide_comments(self, request, queryset):
        from django.utils import timezone

        comment_ids = list(queryset.values_list('comment_id', flat=True))
        Comment.objects.filter(id__in=comment_ids).update(is_hidden=True)
        updated = queryset.update(
            status=CommentReport.Status.REVIEWED, resolved_at=timezone.now()
        )
        self.message_user(request, f'{updated} report(s) actioned.')

    @admin.action(description='Dismiss the reports and leave the comments visible')
    def dismiss_reports(self, request, queryset):
        from django.utils import timezone

        updated = queryset.update(
            status=CommentReport.Status.DISMISSED, resolved_at=timezone.now()
        )
        self.message_user(request, f'{updated} report(s) dismissed.')
