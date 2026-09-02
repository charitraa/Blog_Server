"""
Semantic search and vector related posts.

The embedding API is mocked — these assert our ranking, fallback and staleness
logic, not the provider's model. Vectors here are tiny and hand-made so the
expected ordering is obvious from reading them.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.ai.embeddings import EmbeddingUnavailable, cosine, rank
from apps.post.models import Post, PostEmbedding
from apps.post.search import MIN_SIMILARITY, refresh_embedding

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule.'
MODEL = 'nvidia/nemotron-3-embed-1b'

WITH_EMBEDDINGS = override_settings(
    AI_ENABLED=True, NVIDIA_API_KEY='test-key', NVIDIA_EMBED_MODEL=MODEL,
)


def make_user(email='w@example.com', username='writer'):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Ada', last_name='Lovelace', is_verified=True,
    )


class MathTests(APITestCase):
    def test_identical_vectors_score_one(self):
        self.assertAlmostEqual(cosine([1, 0, 0], [1, 0, 0]), 1.0)

    def test_perpendicular_vectors_score_zero(self):
        self.assertAlmostEqual(cosine([1, 0], [0, 1]), 0.0)

    def test_magnitude_is_ignored(self):
        """A long article and a short one on the same subject should score alike."""
        self.assertAlmostEqual(cosine([1, 1], [5, 5]), 1.0)

    def test_mismatched_lengths_score_zero_rather_than_crashing(self):
        self.assertEqual(cosine([1, 0], [1, 0, 0]), 0.0)

    def test_empty_vectors_score_zero(self):
        self.assertEqual(cosine([], [1]), 0.0)
        self.assertEqual(cosine([0, 0], [1, 1]), 0.0)

    def test_ranking_is_best_first(self):
        ranked = rank([1, 0], [('a', [0, 1]), ('b', [1, 0]), ('c', [0.7, 0.7])])
        self.assertEqual([pk for pk, _ in ranked], ['b', 'c', 'a'])

    def test_the_threshold_drops_weak_matches(self):
        ranked = rank([1, 0], [('a', [0, 1]), ('b', [1, 0])], threshold=0.5)
        self.assertEqual([pk for pk, _ in ranked], ['b'])

    def test_the_limit_is_respected(self):
        ranked = rank([1, 0], [('a', [1, 0]), ('b', [1, 0]), ('c', [1, 0])], limit=2)
        self.assertEqual(len(ranked), 2)

    def test_candidates_without_a_vector_are_skipped(self):
        ranked = rank([1, 0], [('a', []), ('b', [1, 0])])
        self.assertEqual([pk for pk, _ in ranked], ['b'])


@WITH_EMBEDDINGS
class EmbeddingRefreshTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.post = Post.objects.create(
            title='Cross-site scripting', content=BODY, author=self.author,
            status=Post.Status.PUBLISHED,
        )

    @patch('apps.ai.embeddings.embed', return_value=[[0.1, 0.2, 0.3]])
    def test_an_embedding_is_created(self, mocked):
        embedding = refresh_embedding(self.post)
        self.assertEqual(embedding.vector, [0.1, 0.2, 0.3])
        self.assertEqual(embedding.model, MODEL)
        self.assertTrue(embedding.content_hash)

    @patch('apps.ai.embeddings.embed', return_value=[[0.1, 0.2, 0.3]])
    def test_an_unchanged_post_is_not_re_embedded(self, mocked):
        """Each call costs money; re-embedding unchanged text buys nothing."""
        refresh_embedding(self.post)
        refresh_embedding(self.post)
        self.assertEqual(mocked.call_count, 1)

    @patch('apps.ai.embeddings.embed', return_value=[[0.1, 0.2, 0.3]])
    def test_editing_the_post_makes_it_stale(self, mocked):
        refresh_embedding(self.post)
        self.post.title = 'Something else entirely'
        self.post.save()

        refresh_embedding(self.post)
        self.assertEqual(mocked.call_count, 2)

    @patch('apps.ai.embeddings.embed', return_value=[[0.1, 0.2, 0.3]])
    def test_changing_the_model_makes_every_embedding_stale(self, mocked):
        """Vectors from two different models must never be compared."""
        embedding = refresh_embedding(self.post)
        with override_settings(NVIDIA_EMBED_MODEL='some/other-model'):
            self.assertTrue(embedding.is_stale)

    @patch('apps.ai.embeddings.embed', return_value=[[0.1, 0.2, 0.3]])
    def test_force_re_embeds_regardless(self, mocked):
        refresh_embedding(self.post)
        refresh_embedding(self.post, force=True)
        self.assertEqual(mocked.call_count, 2)

    def test_the_source_text_leads_with_the_title(self):
        self.post.subtitle = 'A short deck'
        text = PostEmbedding.source_text(self.post)
        self.assertTrue(text.startswith('Cross-site scripting'))
        self.assertIn('A short deck', text)


@WITH_EMBEDDINGS
class SemanticSearchTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.xss = Post.objects.create(
            title='Preventing cross-site scripting', content=BODY,
            author=self.author, status=Post.Status.PUBLISHED,
        )
        self.bread = Post.objects.create(
            title='Sourdough for beginners', content=BODY,
            author=self.author, status=Post.Status.PUBLISHED,
        )
        # Hand-made vectors: the query below points at the XSS one.
        PostEmbedding.objects.create(post=self.xss, vector=[1.0, 0.0],
                                     model=MODEL, content_hash='a')
        PostEmbedding.objects.create(post=self.bread, vector=[0.0, 1.0],
                                     model=MODEL, content_hash='b')

    @patch('apps.post.search.embed_one', return_value=[1.0, 0.0])
    def test_meaning_beats_keywords(self, mocked):
        """The query shares no words with the title it should find."""
        response = self.client.get('/api/posts/search/', {'q': 'how do I stop XSS'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['semantic'])
        self.assertEqual(response.data['results'][0]['slug'], self.xss.slug)

    @patch('apps.post.search.embed_one', return_value=[1.0, 0.0])
    def test_unrelated_posts_are_dropped_by_the_threshold(self, mocked):
        response = self.client.get('/api/posts/search/', {'q': 'xss'})
        slugs = [row['slug'] for row in response.data['results']]
        self.assertNotIn(self.bread.slug, slugs)

    @patch('apps.post.search.embed_one', side_effect=EmbeddingUnavailable('down'))
    def test_it_falls_back_to_keywords_when_the_service_is_down(self, mocked):
        """A search box that still works beats one that errors."""
        response = self.client.get('/api/posts/search/', {'q': 'sourdough'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['semantic'])
        self.assertEqual(response.data['results'][0]['slug'], self.bread.slug)

    def test_the_response_says_which_search_ran(self):
        """The UI must not imply a capability that did not run."""
        response = self.client.get('/api/posts/search/', {'q': 'sourdough',
                                                          'semantic': 'false'})
        self.assertFalse(response.data['semantic'])

    def test_an_empty_query_returns_nothing(self):
        response = self.client.get('/api/posts/search/', {'q': '  '})
        self.assertEqual(response.data['count'], 0)

    @patch('apps.post.search.embed_one', return_value=[1.0, 0.0])
    def test_drafts_never_surface_in_search(self, mocked):
        draft = Post.objects.create(title='Secret XSS notes', content=BODY,
                                    author=self.author, status=Post.Status.DRAFT)
        PostEmbedding.objects.create(post=draft, vector=[1.0, 0.0],
                                     model=MODEL, content_hash='c')

        response = self.client.get('/api/posts/search/', {'q': 'xss'})
        self.assertNotIn(draft.slug, [r['slug'] for r in response.data['results']])

    @patch('apps.post.search.embed_one', return_value=[1.0, 0.0])
    def test_embeddings_from_another_model_are_ignored(self, mocked):
        PostEmbedding.objects.filter(post=self.xss).update(model='some/old-model')
        response = self.client.get('/api/posts/search/', {'q': 'xss'})
        self.assertNotIn(self.xss.slug, [r['slug'] for r in response.data['results']])


@WITH_EMBEDDINGS
class RelatedPostTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.subject = Post.objects.create(title='XSS', content=BODY,
                                           author=self.author, status=Post.Status.PUBLISHED)
        self.close = Post.objects.create(title='CSP headers', content=BODY,
                                         author=self.author, status=Post.Status.PUBLISHED)
        self.far = Post.objects.create(title='Bread', content=BODY,
                                       author=self.author, status=Post.Status.PUBLISHED)

    def index(self):
        for post, vector in ((self.subject, [1.0, 0.0]), (self.close, [0.95, 0.31]),
                             (self.far, [0.0, 1.0])):
            PostEmbedding.objects.create(post=post, vector=vector, model=MODEL,
                                         content_hash=post.slug)

    def test_related_uses_meaning_when_indexed(self):
        self.index()
        response = self.client.get(f'/api/posts/{self.subject.slug}/related/')
        slugs = [row['slug'] for row in response.data]
        self.assertEqual(slugs[0], self.close.slug)
        self.assertNotIn(self.far.slug, slugs)

    def test_a_post_is_never_related_to_itself(self):
        self.index()
        response = self.client.get(f'/api/posts/{self.subject.slug}/related/')
        self.assertNotIn(self.subject.slug, [row['slug'] for row in response.data])

    def test_it_falls_back_to_tags_without_an_index(self):
        """A brand new post has related content before the index catches up."""
        from apps.post.models import Tag

        tag = Tag.objects.create(name='security')
        self.subject.tags.add(tag)
        self.close.tags.add(tag)

        response = self.client.get(f'/api/posts/{self.subject.slug}/related/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.close.slug, [row['slug'] for row in response.data])
