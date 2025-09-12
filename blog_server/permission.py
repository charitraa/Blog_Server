from rest_framework.permissions import BasePermission
from rest_framework.exceptions import NotAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

class LoginRequiredPermission(BasePermission):
    """
    Custom permission to return a specific message when the user is not authenticated.
    """

    def has_permission(self, request, view):
        token = request.COOKIES.get("access_token")
        if not token:
            raise NotAuthenticated(detail="{ Login required }")

        # Manually authenticate the user
        auth = JWTAuthentication()
        try:
            validated_token = auth.get_validated_token(token)
            request.user = auth.get_user(validated_token)  # Set the authenticated user
        except Exception:
            raise NotAuthenticated(detail="{ Invalid token }")

        return True
