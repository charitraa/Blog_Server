"""Reusable object-level permissions.

Authorization is always decided here on the server. Nothing in these classes
trusts a flag sent by the frontend.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated


class LoginRequiredPermission(IsAuthenticated):
    """
    Kept for backwards compatibility with the original cookie-based views.

    Authentication itself now happens in
    `apps.user.authentication.CookieOrHeaderJWTAuthentication`, which accepts
    both an `Authorization: Bearer` header and the legacy `access_token`
    cookie, so this only has to assert that somebody is signed in.
    """

    message = 'Authentication credentials were not provided.'


class IsAuthorOrReadOnly(BasePermission):
    """Anyone may read; only the object's author (or staff) may modify it."""

    message = 'You do not have permission to perform this action.'

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return obj.author_id == user.id or user.is_staff


class IsSelfOrReadOnly(BasePermission):
    """Anyone may read a profile; only its owner (or staff) may modify it."""

    message = 'You do not have permission to perform this action.'

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return obj.pk == user.pk or user.is_staff


# ---------------------------------------------------------------------------
# Role-based permissions
# ---------------------------------------------------------------------------
#
# Every class below asks the user object about a *capability* rather than
# comparing role names. Adding or reordering a role then changes one ranking
# table in apps/user/models.py instead of every view that guards something.

class _CapabilityPermission(BasePermission):
    """Shared plumbing: a signed-in account whose capability flag is set."""

    capability = None

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return bool(getattr(user, self.capability, False))


class CanPublish(_CapabilityPermission):
    """Author and above. A contributor may draft but not make anything public."""

    capability = 'can_publish'
    message = 'Your account can save drafts but cannot publish them.'


class CanModerate(_CapabilityPermission):
    """Moderator and above: hiding comments, acting on reports."""

    capability = 'can_moderate'
    message = 'You do not have moderation permissions.'


class CanManageUsers(_CapabilityPermission):
    """Admin and above: roles, suspensions, the user list."""

    capability = 'can_manage_users'
    message = 'You do not have user management permissions.'


class IsAuthorOrEditor(BasePermission):
    """
    Anyone may read. The owner may always edit their own; an editor and above
    may edit anybody's.

    This is the role-aware successor to `IsAuthorOrReadOnly`, which only ever
    consulted `is_staff`.
    """

    message = 'You do not have permission to perform this action.'

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if getattr(user, 'can_edit_others', False):
            return True
        return obj.author_id == user.id
