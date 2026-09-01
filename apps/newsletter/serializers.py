from rest_framework import serializers

from .models import NewsletterSubscriber


class SubscribeSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        return value.lower().strip()


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField(required=True, max_length=64)


class SubscriberSerializer(serializers.ModelSerializer):
    """Admin-facing view of a subscriber. The token is never exposed."""

    class Meta:
        model = NewsletterSubscriber
        fields = ['id', 'email', 'is_confirmed', 'is_active', 'created_at', 'confirmed_at']
        read_only_fields = fields
