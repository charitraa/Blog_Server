import logging

from django.conf import settings
from django.core.mail import send_mail
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import NewsletterSubscriber
from .serializers import SubscribeSerializer, TokenSerializer

logger = logging.getLogger('apps.newsletter')

# One answer for every outcome, so the endpoint cannot be used to test whether
# an address is already on the list.
NEUTRAL_REPLY = 'Thanks — check your inbox to confirm your subscription.'


def send_confirmation(subscriber):
    confirm_url = f'{settings.FRONTEND_URL.rstrip("/")}/newsletter/confirm?token={subscriber.token}'
    try:
        send_mail(
            f'Confirm your {settings.SITE_NAME} subscription',
            'Hello,\n\n'
            f'Please confirm your subscription to {settings.SITE_NAME}:\n\n'
            f'{confirm_url}\n\n'
            'If you did not request this, you can ignore this email — nothing will be sent.',
            settings.DEFAULT_FROM_EMAIL,
            [subscriber.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception('Failed to send newsletter confirmation to subscriber %s', subscriber.pk)


class SubscribeView(APIView):
    """POST /api/newsletter/subscribe/ — start double opt-in."""

    permission_classes = [AllowAny]
    throttle_scope = 'auth'
    serializer_class = SubscribeSerializer

    @extend_schema(request=SubscribeSerializer, responses={200: None})
    def post(self, request):
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        subscriber, created = NewsletterSubscriber.objects.get_or_create(email=email)

        # Re-send only while unconfirmed; a confirmed address is never re-mailed
        # by this endpoint, so it cannot be used to pester someone.
        if created or not subscriber.is_confirmed:
            send_confirmation(subscriber)

        return Response({'message': NEUTRAL_REPLY})


class ConfirmView(APIView):
    """POST /api/newsletter/confirm/ — complete double opt-in."""

    permission_classes = [AllowAny]
    throttle_scope = 'auth'
    serializer_class = TokenSerializer

    @extend_schema(request=TokenSerializer, responses={200: None})
    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subscriber = NewsletterSubscriber.objects.filter(
            token=serializer.validated_data['token']
        ).first()
        if subscriber is None:
            return Response(
                {'detail': 'That confirmation link is not valid.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subscriber.confirm()
        return Response({'message': 'Subscription confirmed.', 'email': subscriber.email})


class UnsubscribeView(APIView):
    """POST /api/newsletter/unsubscribe/ — one click, no account needed."""

    permission_classes = [AllowAny]
    throttle_scope = 'auth'
    serializer_class = TokenSerializer

    @extend_schema(request=TokenSerializer, responses={200: None})
    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subscriber = NewsletterSubscriber.objects.filter(
            token=serializer.validated_data['token']
        ).first()
        if subscriber is None:
            return Response(
                {'detail': 'That unsubscribe link is not valid.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subscriber.unsubscribe()
        return Response({'message': 'You have been unsubscribed.'})
