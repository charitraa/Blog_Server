"""
Semantic search and vector-based related posts.

Keyword search finds posts that share *words* with the query. This finds posts
that share *meaning* — "how do I stop XSS" matches an article called
"Preventing cross-site scripting" despite no word in common.

Both entry points degrade rather than fail: with no embeddings, no API key, or
a provider outage, they fall back to the keyword and tag behaviour that was
already there. A search box that returns something useful beats one that
returns an error.
"""

import logging

from django.conf import settings

from apps.ai.embeddings import EmbeddingUnavailable, embed_one, rank

from .models import Post, PostEmbedding

logger = logging.getLogger('apps.post')

# Below this, matches are noise. Measured against the model in use: an
# unrelated document scored 0.03-0.09 while a genuine match scored 0.34-0.51.
MIN_SIMILARITY = 0.15


def _vectors_for(queryset):
    """(post_id, vector) pairs for posts that have a current embedding."""
    return list(
        PostEmbedding.objects
        .filter(post__in=queryset, model=settings.NVIDIA_EMBED_MODEL)
        .values_list('post_id', 'vector')
    )


def _ordered(post_ids, base_queryset):
    """
    Fetch posts and restore the ranking order.

    A database `IN` clause returns rows in whatever order it likes, which would
    throw away the ranking the whole exercise produced.
    """
    posts = {post.id: post for post in base_queryset.filter(id__in=post_ids)}
    return [posts[pk] for pk in post_ids if pk in posts]


def semantic_search(query, base_queryset, limit=20):
    """
    Rank visible posts by meaning.

    Returns `(posts, used_semantic)` so the caller can tell the reader which
    kind of search actually ran instead of quietly pretending.
    """
    if not query.strip():
        return [], False

    try:
        query_vector = embed_one(query, input_type='query')
    except EmbeddingUnavailable:
        logger.info('Semantic search unavailable; falling back to keyword search.')
        return [], False

    if not query_vector:
        return [], False

    candidates = _vectors_for(base_queryset)
    if not candidates:
        return [], False

    ranked = rank(query_vector, candidates, limit=limit, threshold=MIN_SIMILARITY)
    return _ordered([pk for pk, _ in ranked], base_queryset), True


def related_by_meaning(post, base_queryset, limit=4):
    """
    Posts that are actually about the same thing.

    Better than shared tags, which only work when the author remembered to tag
    consistently. Falls back to the tag/category query when there is no
    embedding to compare against.
    """
    embedding = PostEmbedding.objects.filter(
        post=post, model=settings.NVIDIA_EMBED_MODEL,
    ).first()
    if embedding is None or not embedding.vector:
        return [], False

    candidates = [
        (pk, vector) for pk, vector in _vectors_for(base_queryset.exclude(pk=post.pk))
    ]
    if not candidates:
        return [], False

    ranked = rank(embedding.vector, candidates, limit=limit, threshold=MIN_SIMILARITY)
    return _ordered([pk for pk, _ in ranked], base_queryset), True


def refresh_embedding(post, force=False):
    """
    Bring one post's embedding up to date.

    Skips the API call when the text has not changed, because each call costs
    money and re-embedding an unchanged article buys nothing.
    """
    from apps.ai.embeddings import embed_one as embed

    existing = PostEmbedding.objects.filter(post=post).first()
    if existing and not force and not existing.is_stale:
        return existing

    text = PostEmbedding.source_text(post)
    if not text.strip():
        return None

    vector = embed(text, input_type='passage')
    if not vector:
        return None

    embedding, _ = PostEmbedding.objects.update_or_create(
        post=post,
        defaults={
            'vector': vector,
            'model': settings.NVIDIA_EMBED_MODEL,
            'content_hash': PostEmbedding.hash_for(post),
        },
    )
    return embedding
