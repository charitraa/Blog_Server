import logging

from django.conf import settings
from django.core.mail import send_mail
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics

from blog_server import captcha
from blog_server.pagination import StandardPagination
from blog_server.permission import CanManageUsers

from . import brevo
from .models import Campaign, NewsletterSubscriber
from .serializers import (
    CampaignSerializer,
    CampaignWriteSerializer,
    SubscribeSerializer,
    TokenSerializer,
)

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
        # Same reasoning as password reset: it emails an address the requester
        # chose, so an open form is an inbox-bombing tool.
        captcha.check(request, request.data.get('captcha'))

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

        # Mirror the confirmation into Brevo so campaigns actually reach them.
        # Failure is logged, not surfaced: the local record is authoritative,
        # and telling someone their confirmation failed when it did not would
        # be worse than a list that needs re-syncing.
        try:
            brevo.upsert_contact(subscriber.email)
        except brevo.BrevoError:
            logger.exception('Could not add %s to the Brevo list', subscriber.pk)

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

        # Take them off the Brevo list too, or they would keep receiving
        # campaigns despite having unsubscribed here.
        try:
            brevo.remove_from_list(subscriber.email)
        except brevo.BrevoError:
            logger.exception('Could not remove %s from the Brevo list', subscriber.pk)

        return Response({'message': 'You have been unsubscribed.'})


class CampaignListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/newsletter/campaigns/   drafts and sends, with their figures
    POST /api/newsletter/campaigns/   write a new draft

    Staff only: a campaign goes to every confirmed subscriber, so this is not
    something an ordinary account should reach.
    """

    permission_classes = [CanManageUsers]
    pagination_class = StandardPagination
    filter_backends = []
    queryset = Campaign.objects.all()

    def get_serializer_class(self):
        return CampaignWriteSerializer if self.request.method == 'POST' else CampaignSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class CampaignDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE /api/newsletter/campaigns/<id>/

    A sent campaign cannot be edited or deleted — the emails are already in
    people's inboxes, and letting the record drift from what was actually sent
    would make the statistics meaningless.
    """

    permission_classes = [CanManageUsers]
    queryset = Campaign.objects.all()

    def get_serializer_class(self):
        return CampaignWriteSerializer if self.request.method in ('PATCH', 'PUT') else CampaignSerializer

    def _guard_sent(self):
        campaign = self.get_object()
        if campaign.status == Campaign.Status.SENT:
            return Response(
                {'detail': 'A campaign that has already gone out cannot be changed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None

    def update(self, request, *args, **kwargs):
        blocked = self._guard_sent()
        return blocked or super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        blocked = self._guard_sent()
        return blocked or super().destroy(request, *args, **kwargs)


class CampaignSendView(APIView):
    """
    POST /api/newsletter/campaigns/<id>/send/

    Creates the campaign at Brevo and sends it. Irreversible, so it refuses to
    run twice and answers with what actually happened rather than assuming.
    """

    permission_classes = [CanManageUsers]
    serializer_class = CampaignSerializer

    @extend_schema(request=None, responses={200: CampaignSerializer})
    def post(self, request, pk):
        campaign = get_object_or_404(Campaign, pk=pk)

        if campaign.status == Campaign.Status.SENT:
            return Response({'detail': 'That campaign has already been sent.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if not brevo.is_configured():
            return Response(
                {'detail': 'Brevo is not configured, so campaigns cannot be sent.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        confirmed = NewsletterSubscriber.objects.filter(
            is_confirmed=True, is_active=True,
        ).count()
        if confirmed == 0:
            return Response({'detail': 'There are no confirmed subscribers to send to.'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            created = brevo.create_campaign(campaign.name, campaign.subject, campaign.html)
            provider_id = created.get('id')
            brevo.send_campaign(provider_id)
        except brevo.BrevoError as exc:
            campaign.status = Campaign.Status.FAILED
            campaign.save(update_fields=['status'])
            logger.exception('Campaign %s failed to send', campaign.pk)
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        campaign.provider_campaign_id = str(provider_id)
        campaign.status = Campaign.Status.SENT
        campaign.sent_at = timezone.now()
        campaign.save(update_fields=['provider_campaign_id', 'status', 'sent_at'])
        logger.info('%s sent campaign %s to %s subscribers',
                    request.user.username, campaign.pk, confirmed)

        return Response(CampaignSerializer(campaign).data)


class CampaignStatsView(APIView):
    """
    GET /api/newsletter/campaigns/<id>/stats/ — refresh opens and clicks.

    Fetched on demand rather than stored on a schedule: figures keep moving for
    days after a send, and nobody needs them accurate to the minute.
    """

    permission_classes = [CanManageUsers]
    serializer_class = CampaignSerializer

    @extend_schema(responses={200: CampaignSerializer})
    def get(self, request, pk):
        campaign = get_object_or_404(Campaign, pk=pk)
        campaign.refresh_stats()
        return Response(CampaignSerializer(campaign).data)
