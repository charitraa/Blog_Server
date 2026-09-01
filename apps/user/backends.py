"""Authentication backend allowing sign-in with either an email or a username."""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()


class EmailOrUsernameBackend(ModelBackend):
    """
    Resolves `username` (DRF passes the login identifier under this name) against
    both the email and the username column.

    On a miss it still runs the password hasher against a dummy hash so that a
    non-existent account takes the same time as a wrong password. Without that,
    response timing leaks which emails are registered.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = username or kwargs.get('email')
        if not identifier or not password:
            return None

        try:
            user = User.objects.get(
                Q(email__iexact=identifier) | Q(username__iexact=identifier)
            )
        except User.DoesNotExist:
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            # Should be impossible (both columns are unique) but never guess.
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
