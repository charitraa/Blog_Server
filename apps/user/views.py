import logging
import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.post.models import Like, Post
from blog_server.pagination import StandardPagination

from .models import Follow, LoginCode, PasswordResetToken, TopicFollow
from .serializers import (
    DashboardSerializer,
    EmailChangeSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PasswordUpdateSerializer,
    RefreshSerializer,
    SocialAuthSerializer,
    SocialProviderSerializer,
    TopicFollowSerializer,
    UserCreateSerializer,
    UserMeSerializer,
    UserPhotoUpdateSerializer,
    UserPublicSerializer,
    UserUpdateSerializer,
    VerifyEmailSerializer,
)
from .social import PROVIDERS, available_providers

logger = logging.getLogger('apps.user')
User = get_user_model()

# Returned for every failed login, whatever the real reason, so the endpoint
# cannot be used to discover which email addresses exist.
INVALID_CREDENTIALS = 'Invalid email or password.'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def issue_tokens(user):
    refresh = RefreshToken.for_user(user)
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}


def set_auth_cookies(response, access_token, refresh_token=None):
    """
    Mirror the tokens into httpOnly cookies.

    The SPA authenticates with the `Authorization` header; the access cookie is
    kept because the original clients used it, and the refresh cookie lets a
    client keep the access token in memory only and still restore its session
    after a reload without ever putting a token in localStorage.
    """
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=int(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds()),
    )
    if refresh_token is not None:
        response.set_cookie(
            key=settings.REFRESH_COOKIE_NAME,
            value=refresh_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()),
        )
    return response


def clear_auth_cookies(response):
    for name in (settings.AUTH_COOKIE_NAME, settings.REFRESH_COOKIE_NAME):
        response.delete_cookie(name, samesite=settings.COOKIE_SAMESITE)
    return response


def auth_response(user, request, message, http_status=status.HTTP_200_OK):
    tokens = issue_tokens(user)
    payload = {
        'message': message,
        'user': UserMeSerializer(user, context={'request': request}).data,
        **tokens,
    }
    return set_auth_cookies(Response(payload, status=http_status), tokens['access'], tokens['refresh'])


def send_login_code(user):
    """Email a fresh one-time code, invalidating any earlier unused ones."""
    LoginCode.objects.filter(user=user, is_used=False).update(is_used=True)
    code = f'{random.randint(0, 999999):06d}'
    LoginCode.objects.create(
        user=user,
        code=code,
        expires_at=timezone.now() + timedelta(minutes=settings.LOGIN_CODE_TTL_MINUTES),
    )
    try:
        send_mail(
            f'Your {settings.SITE_NAME} verification code',
            f'Hello {user.display_name},\n\n'
            f'Your verification code is: {code}\n\n'
            f'It expires in {settings.LOGIN_CODE_TTL_MINUTES} minutes.\n\n'
            'If you did not request this, you can ignore this email.',
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except Exception:
        # A mail outage must not turn into a 500 for the user; the code is
        # already stored and can be re-sent.
        logger.exception('Failed to send verification email to user %s', user.pk)
        return False
    return True


def author_queryset():
    """Public users annotated with the counters their profile shows."""
    published = Post.objects.filter(author=OuterRef('pk'), status=Post.Status.PUBLISHED)
    return (
        User.objects.filter(is_active=True)
        .annotate(
            post_count=Count('author_post', filter=Q(author_post__status=Post.Status.PUBLISHED), distinct=True),
            follower_count=Count('follower_set', distinct=True),
            following_count=Count('following_set', distinct=True),
        )
        .annotate(has_posts=Exists(published))
    )


# ---------------------------------------------------------------------------
# Registration & sign-in
# ---------------------------------------------------------------------------

class RegisterView(generics.CreateAPIView):
    """POST /api/auth/register/"""

    serializer_class = UserCreateSerializer
    permission_classes = [AllowAny]
    throttle_scope = 'register'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        if settings.REQUIRE_EMAIL_VERIFICATION:
            send_login_code(user)
            return Response(
                {
                    'message': 'Account created. Check your email for a verification code.',
                    'requires_verification': True,
                    'email': user.email,
                },
                status=status.HTTP_201_CREATED,
            )

        user.is_verified = True
        user.save(update_fields=['is_verified'])
        return auth_response(user, request, 'Account created.', status.HTTP_201_CREATED)


class LoginView(APIView):
    """POST /api/auth/login/ — accepts an email or a username."""

    permission_classes = [AllowAny]
    throttle_scope = 'auth'
    serializer_class = LoginSerializer

    @extend_schema(request=LoginSerializer, responses={200: UserMeSerializer})
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = authenticate(
            request,
            username=serializer.validated_data['identifier'],
            password=serializer.validated_data['password'],
        )
        if user is None:
            return Response({'detail': INVALID_CREDENTIALS}, status=status.HTTP_401_UNAUTHORIZED)

        if user.is_currently_suspended:
            # Said plainly: unlike a bad password, this is not something the
            # person can fix by trying again.
            detail = 'This account has been suspended.'
            if user.suspension_reason:
                detail = f'{detail} Reason: {user.suspension_reason}'
            return Response({'detail': detail}, status=status.HTTP_403_FORBIDDEN)

        if settings.REQUIRE_EMAIL_VERIFICATION and not user.is_verified:
            send_login_code(user)
            return Response(
                {
                    'message': 'Verification code sent to your email.',
                    'requires_verification': True,
                    'email': user.email,
                },
                status=status.HTTP_200_OK,
            )

        return auth_response(user, request, 'Login successful.')


class VerifyEmailView(APIView):
    """POST /api/auth/verify/ — confirm the emailed code and sign in."""

    permission_classes = [AllowAny]
    throttle_scope = 'auth'
    serializer_class = VerifyEmailSerializer

    @extend_schema(request=VerifyEmailSerializer, responses={200: UserMeSerializer})
    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.filter(email__iexact=serializer.validated_data['email']).first()
        if user is None:
            return Response({'detail': 'Invalid or expired code.'}, status=status.HTTP_400_BAD_REQUEST)

        login_code = LoginCode.objects.filter(
            user=user, code=serializer.validated_data['code'], is_used=False
        ).first()
        if login_code is None or not login_code.is_usable:
            return Response({'detail': 'Invalid or expired code.'}, status=status.HTTP_400_BAD_REQUEST)

        login_code.is_used = True
        login_code.save(update_fields=['is_used'])

        if not user.is_verified:
            user.is_verified = True
            user.save(update_fields=['is_verified'])

        return auth_response(user, request, 'Email verified.')


class ResendCodeView(APIView):
    """POST /api/auth/resend-code/"""

    permission_classes = [AllowAny]
    throttle_scope = 'auth'

    @extend_schema(request=None, responses={200: None})
    def post(self, request):
        email = (request.data.get('email') or '').strip()
        user = User.objects.filter(email__iexact=email).first()
        if user and not user.is_verified:
            send_login_code(user)
        # Same answer either way: never confirm whether an address is registered.
        return Response({'message': 'If that address needs verification, a code is on its way.'})


class LogoutView(APIView):
    """POST /api/auth/logout/ — blacklists the refresh token and clears the cookie."""

    permission_classes = [IsAuthenticated]
    serializer_class = RefreshSerializer

    @extend_schema(request=RefreshSerializer, responses={200: None})
    def post(self, request):
        # JavaScript cannot delete an httpOnly cookie, so the server has to do
        # both halves of a logout: blacklist the refresh token and clear cookies.
        refresh_token = request.data.get('refresh') or request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except TokenError:
                # An already-expired or unknown token still means "logged out".
                pass

        return clear_auth_cookies(Response({'message': 'Logged out.'}))


class RefreshView(APIView):
    """POST /api/auth/refresh/ — rotates the refresh token and re-sets the cookie."""

    permission_classes = [AllowAny]
    throttle_scope = 'auth'
    serializer_class = RefreshSerializer

    @extend_schema(request=RefreshSerializer, responses={200: None})
    def post(self, request):
        # Body first so header-based clients work; cookie fallback so a client
        # that keeps nothing in JavaScript can still refresh.
        raw = request.data.get('refresh') or request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not raw:
            return Response({'detail': 'A refresh token is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            refresh = RefreshToken(raw)
            user = User.objects.filter(pk=refresh.payload.get('user_id'), is_active=True).first()
            if user is None:
                return Response({'detail': 'Invalid refresh token.'}, status=status.HTTP_401_UNAUTHORIZED)

            if settings.SIMPLE_JWT.get('ROTATE_REFRESH_TOKENS'):
                if settings.SIMPLE_JWT.get('BLACKLIST_AFTER_ROTATION'):
                    refresh.blacklist()
                refresh = RefreshToken.for_user(user)

            payload = {'access': str(refresh.access_token), 'refresh': str(refresh)}
        except TokenError:
            return clear_auth_cookies(
                Response({'detail': 'Invalid or expired refresh token.'},
                         status=status.HTTP_401_UNAUTHORIZED)
            )

        return set_auth_cookies(Response(payload), payload['access'], payload['refresh'])


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------

class MeView(generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/users/me/"""

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return UserMeSerializer if self.request.method == 'GET' else UserUpdateSerializer

    def get_object(self):
        return author_queryset().get(pk=self.request.user.pk)

    def update(self, request, *args, **kwargs):
        instance = request.user
        serializer = UserUpdateSerializer(
            instance, data=request.data, partial=True, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserMeSerializer(self.get_object(), context=self.get_serializer_context()).data)


class MeAvatarView(APIView):
    """POST /api/users/me/avatar/ — multipart upload of the profile picture."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserPhotoUpdateSerializer

    @extend_schema(request=UserPhotoUpdateSerializer, responses={200: UserMeSerializer})
    def post(self, request):
        serializer = UserPhotoUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserMeSerializer(request.user, context={'request': request}).data)

    def put(self, request):
        return self.post(request)


class MePasswordView(APIView):
    """POST /api/users/me/password/"""

    permission_classes = [IsAuthenticated]
    throttle_scope = 'auth'
    serializer_class = PasswordUpdateSerializer

    @extend_schema(request=PasswordUpdateSerializer, responses={200: None})
    def post(self, request):
        serializer = PasswordUpdateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # New credentials, new session: hand back fresh tokens.
        return auth_response(request.user, request, 'Password updated.')


class MeEmailView(APIView):
    """POST /api/users/me/email/ — changing an email requires re-verification."""

    permission_classes = [IsAuthenticated]
    throttle_scope = 'auth'
    serializer_class = EmailChangeSerializer

    @extend_schema(request=EmailChangeSerializer, responses={200: None})
    def post(self, request):
        serializer = EmailChangeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.email = serializer.validated_data['email']
        user.is_verified = False
        user.save(update_fields=['email', 'is_verified'])
        send_login_code(user)

        return Response({
            'message': 'Verification code sent to your new address.',
            'requires_verification': True,
            'email': user.email,
        })


class MeDashboardView(APIView):
    """GET /api/users/me/dashboard/ — counters for the author dashboard."""

    permission_classes = [IsAuthenticated]
    serializer_class = DashboardSerializer

    @extend_schema(responses={200: DashboardSerializer})
    def get(self, request):
        user = request.user
        # One aggregate over the author's posts instead of six separate counts.
        totals = Post.objects.filter(author=user).aggregate(
            total_posts=Count('id', distinct=True),
            published_posts=Count('id', filter=Q(status=Post.Status.PUBLISHED), distinct=True),
            draft_posts=Count('id', filter=Q(status=Post.Status.DRAFT), distinct=True),
        )
        views = Post.objects.filter(author=user).aggregate(
            total_views=Sum('view_count')
        )['total_views'] or 0

        data = {
            'total_posts': totals['total_posts'],
            'published_posts': totals['published_posts'],
            'draft_posts': totals['draft_posts'],
            'total_views': views,
            'total_likes': Like.objects.filter(post__author=user).count(),
            'total_comments': user.author_post.aggregate(
                total=Count('comments', distinct=True)
            )['total'] or 0,
            'follower_count': Follow.objects.filter(following=user).count(),
            'following_count': Follow.objects.filter(follower=user).count(),
        }
        return Response(DashboardSerializer(data).data)


# ---------------------------------------------------------------------------
# Public profiles
# ---------------------------------------------------------------------------

class UserListView(generics.ListAPIView):
    """
    GET /api/users/ — public author directory.

    Only authors with at least one published post are listed, and only public
    fields are serialized, so this cannot be used to enumerate accounts.
    """

    serializer_class = UserPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = StandardPagination
    search_fields = ['username', 'first_name', 'last_name', 'bio']
    ordering_fields = ['date_joined', 'post_count', 'follower_count']
    ordering = ['-post_count']
    filterset_fields = []

    def get_queryset(self):
        return author_queryset().filter(has_posts=True)


class UserDetailView(generics.RetrieveAPIView):
    """GET /api/users/<username>/ — public author profile."""

    serializer_class = UserPublicSerializer
    permission_classes = [AllowAny]
    lookup_field = 'username'

    def get_queryset(self):
        return author_queryset()

    def get_object(self):
        return get_object_or_404(self.get_queryset(), username__iexact=self.kwargs['username'])


class FollowView(APIView):
    """POST / DELETE /api/users/<username>/follow/"""

    permission_classes = [IsAuthenticated]

    def _target(self, username, request):
        user = get_object_or_404(User, username__iexact=username, is_active=True)
        if user.pk == request.user.pk:
            return None
        return user

    @extend_schema(request=None, responses={200: None})
    def post(self, request, username):
        target = self._target(username, request)
        if target is None:
            return Response({'detail': 'You cannot follow yourself.'}, status=status.HTTP_400_BAD_REQUEST)
        # get_or_create + the unique constraint make repeat follows a no-op.
        Follow.objects.get_or_create(follower=request.user, following=target)
        return Response({
            'is_following': True,
            'follower_count': Follow.objects.filter(following=target).count(),
        })

    @extend_schema(request=None, responses={200: None})
    def delete(self, request, username):
        target = self._target(username, request)
        if target is None:
            return Response({'detail': 'You cannot unfollow yourself.'}, status=status.HTTP_400_BAD_REQUEST)
        Follow.objects.filter(follower=request.user, following=target).delete()
        return Response({
            'is_following': False,
            'follower_count': Follow.objects.filter(following=target).count(),
        })


class UserFollowersView(generics.ListAPIView):
    """GET /api/users/<username>/followers/"""

    queryset = User.objects.none()  # for schema generation only
    serializer_class = UserPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = StandardPagination

    def get_queryset(self):
        target = get_object_or_404(User, username__iexact=self.kwargs['username'])
        return author_queryset().filter(following_set__following=target)


class UserFollowingView(generics.ListAPIView):
    """GET /api/users/<username>/following/"""

    queryset = User.objects.none()  # for schema generation only
    serializer_class = UserPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = StandardPagination

    def get_queryset(self):
        target = get_object_or_404(User, username__iexact=self.kwargs['username'])
        return author_queryset().filter(follower_set__follower=target)


# ---------------------------------------------------------------------------
# Social sign-in
# ---------------------------------------------------------------------------

def user_from_social(profile):
    """
    Resolve a social profile onto an account, creating one if needed.

    Matching is by verified email, which is what makes "sign in with GitHub"
    land on the account someone originally registered by email. The providers
    in `social.py` refuse to return an unverified address, so this cannot be
    used to take over an account by claiming somebody else's email.
    """
    user = User.objects.filter(email__iexact=profile.email).first()
    if user is not None:
        # A social sign-in proves the address, so an unverified account becomes
        # verified here rather than being sent through the email code again.
        updates = []
        if not user.is_verified:
            user.is_verified = True
            updates.append('is_verified')
        if not user.first_name and profile.first_name:
            user.first_name = profile.first_name[:30]
            updates.append('first_name')
        if not user.last_name and profile.last_name:
            user.last_name = profile.last_name[:30]
            updates.append('last_name')
        if updates:
            user.save(update_fields=updates)
        return user, False

    username = profile.username or User.generate_username(profile.email)
    if User.objects.filter(username__iexact=username).exists():
        username = User.generate_username(profile.email)

    user = User.objects.create_user(
        email=profile.email,
        # No usable password: this account signs in through the provider. A
        # password can still be set later through the reset flow.
        password=None,
        username=username,
        first_name=profile.first_name[:30],
        last_name=profile.last_name[:30],
        is_verified=True,
        auth_provider=profile.provider,
    )
    user.set_unusable_password()
    user.save(update_fields=['password'])
    return user, True


class SocialAuthView(APIView):
    """
    POST /api/auth/social/<provider>/

    Takes the one-time `code` from GitHub or Google, exchanges it server-side
    and answers with the same token payload as a password login, so the
    frontend treats every sign-in route identically.
    """

    permission_classes = [AllowAny]
    throttle_scope = 'auth'
    serializer_class = SocialAuthSerializer

    @extend_schema(request=SocialAuthSerializer, responses={200: UserMeSerializer})
    def post(self, request, provider):
        provider_class = PROVIDERS.get((provider or '').lower())
        if provider_class is None:
            return Response(
                {'detail': f'Unknown sign-in provider "{provider}".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = SocialAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        redirect_uri = serializer.validated_data.get('redirect_uri') or None
        # AuthenticationFailed from the provider is already a clean 401.
        access_token = provider_class.exchange(serializer.validated_data['code'], redirect_uri)
        profile = provider_class.profile(access_token)

        user, created = user_from_social(profile)
        if not user.is_active:
            return Response({'detail': 'This account has been disabled.'},
                            status=status.HTTP_403_FORBIDDEN)

        message = 'Account created.' if created else 'Login successful.'
        return auth_response(user, request, message,
                             status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class SocialProvidersView(APIView):
    """
    GET /api/auth/providers/

    Lets the frontend render only the buttons this deployment can actually
    honour, and hands it the client ids and authorize URLs so the OAuth
    endpoints are not duplicated in the client.
    """

    permission_classes = [AllowAny]
    serializer_class = SocialProviderSerializer

    @extend_schema(responses={200: SocialProviderSerializer(many=True)})
    def get(self, request):
        catalogue = {
            'github': {
                'authorize_url': 'https://github.com/login/oauth/authorize',
                'client_id': settings.GITHUB_CLIENT_ID,
                'scope': 'read:user user:email',
            },
            'google': {
                'authorize_url': 'https://accounts.google.com/o/oauth2/v2/auth',
                'client_id': settings.GOOGLE_CLIENT_ID,
                'scope': 'openid email profile',
            },
        }
        return Response([
            {'name': name, **catalogue[name]}
            for name in available_providers()
            if name in catalogue
        ])


# ---------------------------------------------------------------------------
# Forgotten passwords
# ---------------------------------------------------------------------------

class PasswordResetRequestView(APIView):
    """
    POST /api/auth/password-reset/

    Always answers the same way, whether or not the address is registered, so
    this cannot be used to discover which emails have accounts.
    """

    permission_classes = [AllowAny]
    throttle_scope = 'auth'
    serializer_class = PasswordResetRequestSerializer

    @extend_schema(request=PasswordResetRequestSerializer, responses={200: None})
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.filter(
            email__iexact=serializer.validated_data['email'], is_active=True
        ).first()
        if user is not None:
            raw_token = PasswordResetToken.issue(user, settings.PASSWORD_RESET_TTL_MINUTES)
            reset_url = f'{settings.FRONTEND_URL.rstrip("/")}/reset-password?token={raw_token}'
            try:
                send_mail(
                    f'Reset your {settings.SITE_NAME} password',
                    f'Hello {user.display_name},\n\n'
                    'We received a request to reset your password. Open this link to choose a new one:\n\n'
                    f'{reset_url}\n\n'
                    f'The link expires in {settings.PASSWORD_RESET_TTL_MINUTES} minutes and can be used once.\n\n'
                    'If you did not ask for this, you can ignore this email — your password will not change.',
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
            except Exception:
                logger.exception('Failed to send a password reset email to user %s', user.pk)

        return Response({
            'message': 'If an account exists for that address, a reset link is on its way.'
        })


class PasswordResetConfirmView(APIView):
    """POST /api/auth/password-reset/confirm/ — set a new password from the emailed token."""

    permission_classes = [AllowAny]
    throttle_scope = 'auth'
    serializer_class = PasswordResetConfirmSerializer

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: UserMeSerializer})
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Only the hash is stored, so the lookup hashes the incoming token too.
        token_hash = PasswordResetToken.hash_token(serializer.validated_data['token'])
        reset = PasswordResetToken.objects.select_related('user').filter(token_hash=token_hash).first()
        if reset is None or not reset.is_usable:
            return Response(
                {'detail': 'This reset link is invalid or has expired.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = reset.user
        try:
            validate_password(serializer.validated_data['new_password'], user=user)
        except DjangoValidationError as exc:
            raise DRFValidationError({'new_password': list(exc.messages)})

        user.set_password(serializer.validated_data['new_password'])
        # Someone who can read the mailbox has proved they own the address.
        if not user.is_verified:
            user.is_verified = True
        user.save(update_fields=['password', 'is_verified'])
        reset.consume()

        # Every other outstanding link is now void.
        PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(
            used_at=timezone.now()
        )

        return auth_response(user, request, 'Password updated. You are signed in.')


# ---------------------------------------------------------------------------
# Following topics
# ---------------------------------------------------------------------------

class TopicFollowView(APIView):
    """
    POST   /api/topics/<kind>/<slug>/follow/   follow a category or tag
    DELETE /api/topics/<kind>/<slug>/follow/   unfollow

    `kind` is "category" or "tag". Following a subject rather than a person is
    what makes the personalised feed useful to a reader who likes a topic but
    has no particular writer in mind.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TopicFollowSerializer

    def resolve(self, kind, slug):
        from apps.post.models import Category, Tag

        if kind == 'category':
            return 'category', get_object_or_404(Category, slug=slug)
        if kind == 'tag':
            return 'tag', get_object_or_404(Tag, slug=slug)
        return None, None

    def _count(self, field, target):
        return TopicFollow.objects.filter(**{field: target}).count()

    @extend_schema(request=None, responses={200: None})
    def post(self, request, kind, slug):
        field, target = self.resolve(kind, slug)
        if target is None:
            return Response({'detail': f'Unknown topic type "{kind}".'},
                            status=status.HTTP_400_BAD_REQUEST)

        TopicFollow.objects.get_or_create(user=request.user, **{field: target})
        return Response({'is_following': True, 'follower_count': self._count(field, target)})

    @extend_schema(request=None, responses={200: None})
    def delete(self, request, kind, slug):
        field, target = self.resolve(kind, slug)
        if target is None:
            return Response({'detail': f'Unknown topic type "{kind}".'},
                            status=status.HTTP_400_BAD_REQUEST)

        TopicFollow.objects.filter(user=request.user, **{field: target}).delete()
        return Response({'is_following': False, 'follower_count': self._count(field, target)})


class MyTopicsView(generics.ListAPIView):
    """GET /api/topics/following/ — the categories and tags this reader follows."""

    serializer_class = TopicFollowSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = []
    queryset = TopicFollow.objects.none()  # for schema generation only

    def get_queryset(self):
        return TopicFollow.objects.filter(user=self.request.user).select_related(
            'category', 'tag'
        )
