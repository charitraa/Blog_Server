from django.contrib import admin
from django.utils.html import format_html

from .models import Bookmark, Category, EditorImage, Like, Post, PostView, Tag


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'post_count')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}

    @admin.display(description='posts')
    def post_count(self, obj):
        return obj.posts.count()


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'post_count')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}

    @admin.display(description='posts')
    def post_count(self, obj):
        return obj.posts.count()


class CommentInline(admin.TabularInline):
    from apps.comment.models import Comment

    model = Comment
    extra = 0
    fields = ('author', 'content', 'parent', 'created_at')
    readonly_fields = ('author', 'created_at')
    show_change_link = True


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'category', 'status', 'published_at', 'view_count', 'like_total')
    list_filter = ('status', 'category', 'created_at', 'published_at')
    search_fields = ('title', 'content', 'excerpt', 'author__email', 'author__username')
    raw_id_fields = ('author',)
    filter_horizontal = ('tags',)
    date_hierarchy = 'created_at'
    readonly_fields = ('slug', 'reading_time', 'view_count', 'created_at', 'updated_at', 'cover_preview')
    inlines = [CommentInline]
    actions = ['publish_posts', 'unpublish_posts']
    list_select_related = ('author', 'category')

    fieldsets = (
        (None, {'fields': ('title', 'slug', 'author', 'status')}),
        ('Content', {'fields': ('excerpt', 'content', 'photo', 'cover_preview')}),
        ('Taxonomy', {'fields': ('category', 'tags')}),
        ('Metrics', {'fields': ('reading_time', 'view_count')}),
        ('Dates', {'fields': ('published_at', 'created_at', 'updated_at')}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('likes')

    @admin.display(description='likes')
    def like_total(self, obj):
        return obj.likes.count()

    @admin.display(description='cover')
    def cover_preview(self, obj):
        if not obj.photo:
            return '—'
        return format_html('<img src="{}" style="max-height:120px;border-radius:6px" />', obj.photo.url)

    @admin.action(description='Publish selected posts')
    def publish_posts(self, request, queryset):
        # Saved one by one so `Post.save()` stamps published_at correctly.
        for post in queryset.filter(status=Post.Status.DRAFT):
            post.status = Post.Status.PUBLISHED
            post.save()

    @admin.action(description='Move selected posts back to draft')
    def unpublish_posts(self, request, queryset):
        for post in queryset.filter(status=Post.Status.PUBLISHED):
            post.status = Post.Status.DRAFT
            post.save()


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ('post', 'user', 'created_at')
    search_fields = ('post__title', 'user__email', 'user__username')
    raw_id_fields = ('post', 'user')
    list_select_related = ('post', 'user')


@admin.register(PostView)
class PostViewAdmin(admin.ModelAdmin):
    list_display = ('post', 'user', 'created_at')
    raw_id_fields = ('post', 'user')
    list_select_related = ('post', 'user')
    # `fingerprint` is a salted hash and is not useful (or appropriate) to browse.
    exclude = ('fingerprint',)
    readonly_fields = ('post', 'user', 'created_at')

    def has_add_permission(self, request):
        return False


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ['user', 'post', 'created_at']
    search_fields = ['user__username', 'user__email', 'post__title']
    raw_id_fields = ['user', 'post']
    readonly_fields = ['id', 'created_at']


@admin.register(EditorImage)
class EditorImageAdmin(admin.ModelAdmin):
    list_display = ['image', 'uploaded_by', 'created_at']
    search_fields = ['uploaded_by__username', 'uploaded_by__email']
    raw_id_fields = ['uploaded_by']
    readonly_fields = ['id', 'created_at']
