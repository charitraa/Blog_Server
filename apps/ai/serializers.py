"""Request and response shapes for the AI endpoints."""

from rest_framework import serializers

from .services import TONES


class ContentSerializer(serializers.Serializer):
    """Anything that operates on a draft."""

    content = serializers.CharField(min_length=40, max_length=200_000)
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)


class TitleSuggestionSerializer(serializers.Serializer):
    titles = serializers.ListField(child=serializers.CharField())


class SeoSuggestionSerializer(serializers.Serializer):
    seo_title = serializers.CharField()
    seo_description = serializers.CharField()
    tags = serializers.ListField(child=serializers.CharField())


class SummarySerializer(serializers.Serializer):
    summary = serializers.CharField()


class OutlineRequestSerializer(serializers.Serializer):
    topic = serializers.CharField(min_length=3, max_length=300)
    audience = serializers.CharField(required=False, allow_blank=True, max_length=200)


class OutlineSectionSerializer(serializers.Serializer):
    heading = serializers.CharField()
    points = serializers.ListField(child=serializers.CharField())


class OutlineSerializer(serializers.Serializer):
    sections = OutlineSectionSerializer(many=True)


class RewriteRequestSerializer(serializers.Serializer):
    text = serializers.CharField(min_length=10, max_length=20_000)
    tone = serializers.ChoiceField(choices=sorted(TONES), default='clearer')


class TextResultSerializer(serializers.Serializer):
    text = serializers.CharField()


class ProofreadRequestSerializer(serializers.Serializer):
    text = serializers.CharField(min_length=10, max_length=20_000)


class SocialRequestSerializer(serializers.Serializer):
    content = serializers.CharField(min_length=40, max_length=200_000)
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)
    network = serializers.ChoiceField(
        choices=['general', 'twitter', 'linkedin'], default='general',
    )


class TranslateRequestSerializer(serializers.Serializer):
    text = serializers.CharField(min_length=1, max_length=20_000)
    target_language = serializers.CharField(max_length=40)


class AskRequestSerializer(serializers.Serializer):
    question = serializers.CharField(min_length=3, max_length=500)


class AnswerSerializer(serializers.Serializer):
    answer = serializers.CharField()


class AIStatusSerializer(serializers.Serializer):
    """
    What the UI needs to decide whether to render the assistant at all.

    No key, no model ids beyond a display name — nothing here is a credential.
    """

    enabled = serializers.BooleanField()
    provider = serializers.CharField()
    features = serializers.ListField(child=serializers.CharField())
