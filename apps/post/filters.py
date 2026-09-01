"""Query-parameter filters for the post list endpoint."""

import django_filters as filters

from .models import Post


class PostFilter(filters.FilterSet):
    """
    Every filter is declared explicitly. Arbitrary `?field__lookup=` pairs are
    not accepted, so a client cannot reach columns the API does not expose.
    """

    category = filters.CharFilter(field_name='category__slug', lookup_expr='iexact')
    tag = filters.CharFilter(field_name='tags__slug', lookup_expr='iexact')
    author = filters.CharFilter(field_name='author__username', lookup_expr='iexact')
    date_from = filters.DateTimeFilter(field_name='published_at', lookup_expr='gte')
    date_to = filters.DateTimeFilter(field_name='published_at', lookup_expr='lte')
    status = filters.ChoiceFilter(choices=Post.Status.choices, method='filter_status')

    class Meta:
        model = Post
        fields = ['category', 'tag', 'author', 'status', 'date_from', 'date_to']

    def filter_status(self, queryset, name, value):
        """
        Drafts are only ever reachable by someone allowed to see them.

        The base queryset is already narrowed by `Post.objects.visible_to()`, so
        an anonymous visitor asking for `?status=draft` gets an empty page
        rather than somebody else's unpublished work.
        """
        return queryset.filter(status=value)
