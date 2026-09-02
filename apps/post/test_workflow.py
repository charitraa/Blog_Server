"""Editorial workflow: submit, queue, approve, send back."""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.notification.models import Notification
from apps.post.models import Post

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule.'


def make_user(email, username, role='author'):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Test', last_name='Person', is_verified=True, role=role,
    )


class SubmitTests(APITestCase):
    def setUp(self):
        self.contributor = make_user('c@example.com', 'contrib', 'contributor')
        self.editor = make_user('e@example.com', 'editor', 'editor')
        self.draft = Post.objects.create(title='Draft', content=BODY,
                                         author=self.contributor)

    def test_a_contributor_can_submit_their_draft(self):
        self.client.force_authenticate(self.contributor)
        response = self.client.post(f'/api/posts/{self.draft.slug}/submit/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, Post.Status.IN_REVIEW)

    def test_submitting_notifies_editors(self):
        self.client.force_authenticate(self.contributor)
        self.client.post(f'/api/posts/{self.draft.slug}/submit/')
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.editor, verb=Notification.Verb.SUBMITTED,
            ).exists()
        )

    def test_a_stranger_cannot_submit_somebody_elses_draft(self):
        other = make_user('o@example.com', 'other')
        self.client.force_authenticate(other)
        response = self.client.post(f'/api/posts/{self.draft.slug}/submit/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_an_empty_draft_cannot_be_submitted(self):
        thin = Post.objects.create(title='Thin', content='short', author=self.contributor)
        self.client.force_authenticate(self.contributor)
        response = self.client.post(f'/api/posts/{thin.slug}/submit/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_published_post_cannot_be_submitted(self):
        self.draft.status = Post.Status.PUBLISHED
        self.draft.save()
        self.client.force_authenticate(self.contributor)
        response = self.client.post(f'/api/posts/{self.draft.slug}/submit/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resubmitting_clears_the_old_feedback(self):
        """The note referred to a version that no longer exists."""
        self.draft.review_note = 'Needs a stronger opening'
        self.draft.save()

        self.client.force_authenticate(self.contributor)
        self.client.post(f'/api/posts/{self.draft.slug}/submit/')
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.review_note, '')


class ReviewQueueTests(APITestCase):
    def setUp(self):
        self.contributor = make_user('c@example.com', 'contrib', 'contributor')
        self.editor = make_user('e@example.com', 'editor', 'editor')
        self.submitted = Post.objects.create(
            title='Waiting', content=BODY, author=self.contributor,
            status=Post.Status.IN_REVIEW,
        )
        Post.objects.create(title='Just a draft', content=BODY, author=self.contributor)

    def test_the_queue_lists_only_submissions(self):
        self.client.force_authenticate(self.editor)
        response = self.client.get('/api/posts/review-queue/')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['slug'], self.submitted.slug)

    def test_a_contributor_sees_no_queue(self):
        self.client.force_authenticate(self.contributor)
        self.assertEqual(self.client.get('/api/posts/review-queue/').data['count'], 0)

    def test_the_queue_needs_a_sign_in(self):
        self.assertEqual(self.client.get('/api/posts/review-queue/').status_code,
                         status.HTTP_401_UNAUTHORIZED)


class ReviewDecisionTests(APITestCase):
    def setUp(self):
        self.contributor = make_user('c@example.com', 'contrib', 'contributor')
        self.editor = make_user('e@example.com', 'editor', 'editor')
        self.post = Post.objects.create(
            title='Waiting', content=BODY, author=self.contributor,
            status=Post.Status.IN_REVIEW,
        )
        self.url = f'/api/posts/{self.post.slug}/review/'

    def test_approving_publishes_it(self):
        self.client.force_authenticate(self.editor)
        response = self.client.post(self.url, {'action': 'approve'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.PUBLISHED)
        self.assertIsNotNone(self.post.published_at)

    def test_the_byline_stays_with_the_writer(self):
        self.client.force_authenticate(self.editor)
        self.client.post(self.url, {'action': 'approve'}, format='json')
        self.post.refresh_from_db()
        self.assertEqual(self.post.author, self.contributor)
        self.assertEqual(self.post.reviewed_by, self.editor)

    def test_requesting_changes_sends_it_back_with_a_note(self):
        self.client.force_authenticate(self.editor)
        response = self.client.post(
            self.url, {'action': 'request_changes', 'note': 'Add sources.'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.DRAFT)
        self.assertEqual(self.post.review_note, 'Add sources.')

    def test_a_rejection_without_a_reason_is_refused(self):
        """Sending work back without saying why is not a review."""
        self.client.force_authenticate(self.editor)
        response = self.client.post(self.url, {'action': 'request_changes'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.IN_REVIEW)

    def test_a_contributor_cannot_approve_their_own_post(self):
        self.client.force_authenticate(self.contributor)
        response = self.client.post(self.url, {'action': 'approve'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, Post.Status.IN_REVIEW)

    def test_an_unknown_action_is_rejected(self):
        self.client.force_authenticate(self.editor)
        response = self.client.post(self.url, {'action': 'shred'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_the_author_is_notified_of_the_decision(self):
        self.client.force_authenticate(self.editor)
        self.client.post(self.url, {'action': 'approve'}, format='json')
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.contributor, verb=Notification.Verb.APPROVED,
            ).exists()
        )

    def test_the_author_sees_the_feedback_on_their_own_post(self):
        self.client.force_authenticate(self.editor)
        self.client.post(self.url, {'action': 'request_changes', 'note': 'Add sources.'},
                         format='json')

        self.client.force_authenticate(self.contributor)
        response = self.client.get(f'/api/posts/{self.post.slug}/')
        self.assertEqual(response.data['review_note'], 'Add sources.')
