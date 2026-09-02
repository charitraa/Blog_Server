from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import Follow, LoginCode, PasswordResetToken, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        (_('Personal info'), {
            'fields': ('first_name', 'last_name', 'photo', 'bio', 'headline',
                       'date_of_birth', 'district', 'city'),
        }),
        (_('Links'), {'fields': ('website', 'twitter', 'github', 'linkedin')}),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Verification'), {'fields': ('is_verified', 'auth_provider')}),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2'),
        }),
    )

    list_display = ('email', 'username', 'first_name', 'last_name', 'post_count',
                    'is_staff', 'is_verified', 'auth_provider')
    list_filter = ('is_staff', 'is_superuser', 'is_verified', 'auth_provider', 'is_active')
    search_fields = ('email', 'username', 'first_name', 'last_name')
    ordering = ('email',)
    readonly_fields = ('date_joined', 'last_login')

    @admin.display(description='posts')
    def post_count(self, obj):
        return obj.author_post.count()


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ('follower', 'following', 'created_at')
    search_fields = ('follower__username', 'following__username')
    raw_id_fields = ('follower', 'following')
    list_select_related = ('follower', 'following')


@admin.register(LoginCode)
class LoginCodeAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at', 'expires_at', 'is_used')
    list_filter = ('is_used',)
    search_fields = ('user__email',)
    raw_id_fields = ('user',)
    # The code itself is a credential; it is not browsable in the admin.
    exclude = ('code',)
    readonly_fields = ('user', 'created_at', 'expires_at')

    def has_add_permission(self, request):
        return False


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    """Read-only: the plain token is never stored, so nothing here can be reused."""

    list_display = ['user', 'created_at', 'expires_at', 'used_at']
    list_filter = ['created_at']
    search_fields = ['user__email', 'user__username']
    readonly_fields = ['id', 'user', 'token_hash', 'created_at', 'expires_at', 'used_at']

    def has_add_permission(self, request):
        return False
