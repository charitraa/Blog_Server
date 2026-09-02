"""
AI assistant endpoints.

The provider is mocked throughout: these assert the contract around the model —
auth, throttling scope, validation, error translation — not the model's prose.
Calling a real endpoint from the test suite would be slow, flaky and billed.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.ai.client import AIError, AIUnavailable
from apps.ai.utils import plain_text_excerpt
from apps.post.models import Post

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule for AI.'

WITH_AI = override_settings(AI_ENABLED=True, NVIDIA_API_KEY='test-key')
WITHOUT_AI = override_settings(AI_ENABLED=True, NVIDIA_API_KEY='')


def make_user(email='writer@example.com', username='writer'):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Ada', last_name='Lovelace', is_verified=True,
    )


class ExcerptTests(APITestCase):
    def test_markup_is_stripped(self):
        self.assertEqual(plain_text_excerpt('<p>Hello <b>world</b></p>', 100), 'Hello world')

    def test_long_text_is_clamped_on_a_word_boundary(self):
        result = plain_text_excerpt('word ' * 100, 20)
        self.assertLessEqual(len(result), 21)
        self.assertTrue(result.endswith('…'))

    def test_empty_input_is_safe(self):
        self.assertEqual(plain_text_excerpt(None, 50), '')


class StatusTests(APITestCase):
    @WITHOUT_AI
    def test_disabled_when_no_key_is_set(self):
        response = self.client.get('/api/ai/status/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['enabled'])
        self.assertEqual(response.data['features'], [])

    @WITH_AI
    def test_enabled_lists_features(self):
        response = self.client.get('/api/ai/status/')
        self.assertTrue(response.data['enabled'])
        self.assertIn('titles', response.data['features'])

    @WITH_AI
    def test_status_never_leaks_the_key(self):
        body = str(self.client.get('/api/ai/status/').data)
        self.assertNotIn('test-key', body)


@WITH_AI
class EndpointTests(APITestCase):
    def setUp(self):
        self.user = make_user()

    def test_every_endpoint_needs_a_sign_in(self):
        for path in ('/api/ai/titles/', '/api/ai/seo/', '/api/ai/summary/',
                     '/api/ai/outline/', '/api/ai/rewrite/', '/api/ai/proofread/',
                     '/api/ai/social/', '/api/ai/translate/'):
            with self.subTest(path=path):
                response = self.client.post(path, {}, format='json')
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('apps.ai.services.chat_json', return_value={'titles': ['One', 'Two']})
    def test_titles(self, mocked):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/ai/titles/', {'content': BODY}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['titles'], ['One', 'Two'])

    @patch('apps.ai.services.chat_json', return_value={
        'seo_title': 'T', 'seo_description': 'D', 'tags': ['a', 'B '],
    })
    def test_seo_normalises_tags(self, mocked):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/ai/seo/', {'content': BODY}, format='json')
        self.assertEqual(response.data['tags'], ['a', 'b'])

    @patch('apps.ai.services.chat', return_value='A short summary.')
    def test_summary(self, mocked):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/ai/summary/', {'content': BODY}, format='json')
        self.assertEqual(response.data['summary'], 'A short summary.')

    @patch('apps.ai.services.chat_json', return_value={
        'sections': [{'heading': 'Intro', 'points': ['a', 'b']}, {'heading': '', 'points': []}],
    })
    def test_outline_drops_headless_sections(self, mocked):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/ai/outline/', {'topic': 'IDOR'}, format='json')
        self.assertEqual(len(response.data['sections']), 1)
        self.assertEqual(response.data['sections'][0]['heading'], 'Intro')

    @patch('apps.ai.services.chat', return_value='Rewritten.')
    def test_rewrite(self, mocked):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            '/api/ai/rewrite/', {'text': 'Some text here.', 'tone': 'shorter'}, format='json',
        )
        self.assertEqual(response.data['text'], 'Rewritten.')

    def test_an_unknown_tone_is_rejected(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            '/api/ai/rewrite/', {'text': 'Some text here.', 'tone': 'piratical'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_content_that_is_too_short_is_rejected(self):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/ai/titles/', {'content': 'hi'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('apps.ai.services.chat', side_effect=AIUnavailable('The AI service is busy.'))
    def test_a_provider_outage_becomes_a_503(self, mocked):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/ai/summary/', {'content': BODY}, format='json')
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn('busy', response.data['detail'])

    @patch('apps.ai.services.chat_json', side_effect=AIError('Malformed answer.'))
    def test_a_malformed_answer_becomes_a_503(self, mocked):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/ai/titles/', {'content': BODY}, format='json')
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @patch('apps.ai.services.chat', side_effect=AIUnavailable('boom'))
    def test_errors_never_contain_the_api_key(self, mocked):
        self.client.force_authenticate(self.user)
        response = self.client.post('/api/ai/summary/', {'content': BODY}, format='json')
        self.assertNotIn('test-key', str(response.data))


@WITH_AI
class AskAboutPostTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.reader = make_user('r@example.com', 'reader')
        self.post = Post.objects.create(
            title='Live', content=BODY, author=self.author, status=Post.Status.PUBLISHED,
        )
        self.draft = Post.objects.create(
            title='Secret', content=BODY, author=self.author, status=Post.Status.DRAFT,
        )

    @patch('apps.ai.services.chat', return_value='Because of X.')
    def test_a_reader_can_ask_about_a_published_post(self, mocked):
        self.client.force_authenticate(self.reader)
        response = self.client.post(
            f'/api/posts/{self.post.slug}/ask/', {'question': 'Why?'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['answer'], 'Because of X.')

    @patch('apps.ai.services.chat', return_value='...')
    def test_it_cannot_be_used_to_read_someone_elses_draft(self, mocked):
        self.client.force_authenticate(self.reader)
        response = self.client.post(
            f'/api/posts/{self.draft.slug}/ask/', {'question': 'What?'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_asking_needs_a_sign_in(self):
        response = self.client.post(
            f'/api/posts/{self.post.slug}/ask/', {'question': 'Why?'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ScreeningTests(APITestCase):
    @WITH_AI
    @patch('apps.ai.services.chat', return_value='{"User Safety": "unsafe", '
                                                 '"Safety Categories": "Harassment"}')
    def test_an_unsafe_verdict_is_reported(self, mocked):
        from apps.ai.services import screen_text

        result = screen_text('something abusive')
        self.assertFalse(result['safe'])
        self.assertTrue(result['checked'])

    @WITH_AI
    @patch('apps.ai.services.chat', return_value='{"User Safety": "safe"}')
    def test_a_safe_verdict(self, mocked):
        from apps.ai.services import screen_text

        self.assertTrue(screen_text('a normal comment')['safe'])

    @WITH_AI
    @patch('apps.ai.services.chat', side_effect=AIUnavailable('down'))
    def test_screening_failure_never_blocks_a_comment(self, mocked):
        """Screening is an enhancement; an outage must not stop people talking."""
        from apps.ai.services import screen_text

        result = screen_text('a normal comment')
        self.assertTrue(result['safe'])
        self.assertFalse(result['checked'])
