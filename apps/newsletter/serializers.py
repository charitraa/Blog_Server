from rest_framework import serializers

from .models import Campaign, NewsletterSubscriber


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


class CampaignSerializer(serializers.ModelSerializer):
    """A campaign and its latest known figures."""

    created_by = serializers.CharField(source='created_by.username', read_only=True, default=None)
    open_rate = serializers.FloatField(read_only=True)
    click_rate = serializers.FloatField(read_only=True)

    class Meta:
        model = Campaign
        fields = ['id', 'name', 'subject', 'status', 'created_by', 'created_at',
                  'sent_at', 'stats', 'stats_updated_at', 'open_rate', 'click_rate']
        read_only_fields = ['id', 'status', 'created_by', 'created_at', 'sent_at',
                            'stats', 'stats_updated_at', 'open_rate', 'click_rate']


class CampaignWriteSerializer(serializers.ModelSerializer):
    """Create or edit a draft. Sending is a separate, deliberate action."""

    class Meta:
        model = Campaign
        fields = ['id', 'name', 'subject', 'html']
        read_only_fields = ['id']

    def validate_html(self, value):
        if len(value.strip()) < 20:
            raise serializers.ValidationError('The email needs a body.')
        return value
