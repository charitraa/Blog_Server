"""
Text embeddings, for semantic search and vector-based related posts.

An embedding turns text into a list of numbers positioned so that things which
*mean* similar things sit close together. That is what lets "how do I stop XSS"
find an article titled "Preventing cross-site scripting" — keyword search
cannot, because they share no words.

Model choice was measured, not assumed: of the seven embedding models in the
NVIDIA catalogue, only two are enabled for this account. `nemotron-3-embed-1b`
was picked for separating related from unrelated text cleanly (0.51 vs 0.21 on
a same-topic/different-topic pair, and 0.34 vs 0.03 on an unrelated one).

Queries and documents are embedded with **different** `input_type` values.
That is not optional for this model family — a question and the passage that
answers it are phrased differently, and telling the model which it is looking
at is what makes them land near each other.
"""

import logging
import math

import requests
from django.conf import settings

logger = logging.getLogger('apps.ai')

TIMEOUT = 60
# The API rejects very large batches; this keeps a backfill of a thousand posts
# to a manageable number of requests without risking a rejection.
BATCH_SIZE = 32


class EmbeddingUnavailable(Exception):
    """The embedding service is not configured or could not be reached."""


def is_configured():
    return bool(settings.AI_ENABLED and settings.NVIDIA_API_KEY
                and settings.NVIDIA_EMBED_MODEL)


def _embed_batch(texts, input_type):
    try:
        response = requests.post(
            f'{settings.NVIDIA_BASE_URL.rstrip("/")}/embeddings',
            headers={
                'Authorization': f'Bearer {settings.NVIDIA_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'model': settings.NVIDIA_EMBED_MODEL,
                'input': texts,
                'input_type': input_type,
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning('Embedding service unreachable: %s', exc)
        raise EmbeddingUnavailable('The search index service could not be reached.') from exc

    if response.status_code >= 400:
        logger.warning('Embedding service returned %s: %s',
                       response.status_code, response.text[:300])
        raise EmbeddingUnavailable('The search index service returned an error.')

    try:
        body = response.json()
        # The API does not promise input order, so results are sorted by index.
        return [row['embedding'] for row in sorted(body['data'], key=lambda r: r['index'])]
    except (ValueError, KeyError) as exc:
        raise EmbeddingUnavailable('The search index service returned something unexpected.') from exc


def embed(texts, input_type='passage'):
    """
    Embed a list of texts. `input_type` is 'query' or 'passage'.

    Empty strings are filtered out rather than sent: the API rejects them, and
    one empty post body should not fail a whole backfill batch.
    """
    if not is_configured():
        raise EmbeddingUnavailable('Semantic search is not configured on this server.')

    cleaned = [t for t in (text.strip() for text in texts) if t]
    if not cleaned:
        return []

    vectors = []
    for start in range(0, len(cleaned), BATCH_SIZE):
        vectors.extend(_embed_batch(cleaned[start:start + BATCH_SIZE], input_type))
    return vectors


def embed_one(text, input_type='passage'):
    vectors = embed([text], input_type)
    return vectors[0] if vectors else None


def cosine(a, b):
    """
    Similarity between two vectors, from -1 to 1.

    Cosine rather than raw distance because it compares *direction* and ignores
    magnitude — a long article and a short one about the same subject should
    score alike.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def rank(query_vector, candidates, limit=10, threshold=0.0):
    """
    Score candidates against a query vector, best first.

    `candidates` is an iterable of (identifier, vector). Brute force on purpose:
    for a blog with thousands of posts this is milliseconds, and it needs no
    vector database or extension. Past roughly 50k posts, move the vectors into
    pgvector and let the database do the ordering.
    """
    scored = [
        (identifier, cosine(query_vector, vector))
        for identifier, vector in candidates
        if vector
    ]
    scored = [row for row in scored if row[1] >= threshold]
    scored.sort(key=lambda row: row[1], reverse=True)
    return scored[:limit]
