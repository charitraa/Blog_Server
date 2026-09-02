"""
AI assistant endpoints, mounted at /api/ai/.

Three rules hold across all of them:

  * Every call is explicitly triggered by a signed-in author. Nothing fires on
    page load, and no endpoint edits a post — suggestions are returned for the
    author to accept or ignore.
  * They share a tight throttle scope of their own, because each request costs
    real money at the provider.
  * A provider failure is a 503 with a plain sentence, never a stack trace and
    never anything containing the API key.
"""

import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.post.models import Post
from django.shortcuts import get_object_or_404

from . import services
from .client import AIError, AIUnavailable, is_configured
from .serializers import (
    AIStatusSerializer,
    AnswerSerializer,
    AskRequestSerializer,
    ContentSerializer,
    OutlineRequestSerializer,
    OutlineSerializer,
    ProofreadRequestSerializer,
    RewriteRequestSerializer,
    SeoSuggestionSerializer,
    SocialRequestSerializer,
    SummarySerializer,
    TextResultSerializer,
    TitleSuggestionSerializer,
    TranslateRequestSerializer,
)

logger = logging.getLogger('apps.ai')


class AIView(APIView):
    """Shared plumbing: authentication, throttling and provider error handling."""

    permission_classes = [IsAuthenticated]
    throttle_scope = 'ai'

    def run(self, task, *args, **kwargs):
        try:
            return task(*args, **kwargs)
        except AIUnavailable as exc:
            raise ServiceUnavailable(str(exc)) from exc
        except AIError as exc:
            raise ServiceUnavailable(str(exc)) from exc


class ServiceUnavailable(Exception):
    """Turned into a 503 by the handler below."""

    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


def _unavailable(detail):
    return Response({'detail': detail}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


def _guarded(handler):
    """Wraps a view method so provider failures become a clean 503."""
    def wrapper(self, request, *args, **kwargs):
        try:
            return handler(self, request, *args, **kwargs)
        except (AIUnavailable, AIError) as exc:
            return _unavailable(str(exc))
    return wrapper


class AIStatusView(APIView):
    """
    GET /api/ai/status/

    Public so the editor can decide whether to render the assistant before the
    author clicks anything. Exposes no credentials.
    """

    permission_classes = [AllowAny]
    serializer_class = AIStatusSerializer

    @extend_schema(responses={200: AIStatusSerializer})
    def get(self, request):
        from django.conf import settings

        features = [
            'titles', 'seo', 'summary', 'outline', 'rewrite',
            'proofread', 'social', 'translate', 'ask',
        ] if is_configured() else []

        return Response({
            'enabled': is_configured(),
            'provider': settings.AI_PREFERRED_PROVIDER if is_configured() else '',
            'features': features,
        })


class SuggestTitlesView(AIView):
    """POST /api/ai/titles/ — title options for a draft."""

    serializer_class = ContentSerializer

    @extend_schema(request=ContentSerializer, responses={200: TitleSuggestionSerializer})
    @_guarded
    def post(self, request):
        serializer = ContentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        titles = services.suggest_titles(serializer.validated_data['content'])
        return Response({'titles': titles})


class SuggestSeoView(AIView):
    """POST /api/ai/seo/ — search title, description and tags."""

    serializer_class = ContentSerializer

    @extend_schema(request=ContentSerializer, responses={200: SeoSuggestionSerializer})
    @_guarded
    def post(self, request):
        serializer = ContentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.suggest_seo(
            serializer.validated_data['content'],
            serializer.validated_data.get('title', ''),
        )
        return Response(result)


class SummarizeView(AIView):
    """POST /api/ai/summary/ — a short summary of a draft."""

    serializer_class = ContentSerializer

    @extend_schema(request=ContentSerializer, responses={200: SummarySerializer})
    @_guarded
    def post(self, request):
        serializer = ContentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({'summary': services.summarize(serializer.validated_data['content'])})


class OutlineView(AIView):
    """POST /api/ai/outline/ — a starting structure from a topic."""

    serializer_class = OutlineRequestSerializer

    @extend_schema(request=OutlineRequestSerializer, responses={200: OutlineSerializer})
    @_guarded
    def post(self, request):
        serializer = OutlineRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sections = services.outline(
            serializer.validated_data['topic'],
            serializer.validated_data.get('audience', ''),
        )
        return Response({'sections': sections})


class RewriteView(AIView):
    """POST /api/ai/rewrite/ — rewrite a selected passage."""

    serializer_class = RewriteRequestSerializer

    @extend_schema(request=RewriteRequestSerializer, responses={200: TextResultSerializer})
    @_guarded
    def post(self, request):
        serializer = RewriteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        text = services.rewrite(
            serializer.validated_data['text'], serializer.validated_data['tone'],
        )
        return Response({'text': text})


class ProofreadView(AIView):
    """POST /api/ai/proofread/ — spelling and grammar only."""

    serializer_class = ProofreadRequestSerializer

    @extend_schema(request=ProofreadRequestSerializer, responses={200: TextResultSerializer})
    @_guarded
    def post(self, request):
        serializer = ProofreadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({'text': services.proofread(serializer.validated_data['text'])})


class SocialPostView(AIView):
    """POST /api/ai/social/ — a short announcement post."""

    serializer_class = SocialRequestSerializer

    @extend_schema(request=SocialRequestSerializer, responses={200: TextResultSerializer})
    @_guarded
    def post(self, request):
        serializer = SocialRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        text = services.social_post(
            serializer.validated_data['content'],
            serializer.validated_data.get('title', ''),
            serializer.validated_data['network'],
        )
        return Response({'text': text})


class TranslateView(AIView):
    """POST /api/ai/translate/ — translate a passage."""

    serializer_class = TranslateRequestSerializer

    @extend_schema(request=TranslateRequestSerializer, responses={200: TextResultSerializer})
    @_guarded
    def post(self, request):
        serializer = TranslateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        text = services.translate(
            serializer.validated_data['text'],
            serializer.validated_data['target_language'],
        )
        return Response({'text': text})


class AskAboutPostView(AIView):
    """
    POST /api/posts/<slug>/ask/ — answer a reader's question from the article.

    Scoped to a published post the reader can already open, so this cannot be
    used to read a draft they have no access to.
    """

    serializer_class = AskRequestSerializer

    @extend_schema(request=AskRequestSerializer, responses={200: AnswerSerializer})
    @_guarded
    def post(self, request, slug):
        post = get_object_or_404(Post.objects.visible_to(request.user), slug=slug)

        serializer = AskRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        answer = services.answer_question(
            post.content, serializer.validated_data['question'],
        )
        return Response({'answer': answer})
