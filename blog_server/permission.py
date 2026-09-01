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
