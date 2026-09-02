"""Role ladder, capability gating and the administration endpoints."""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.comment.models import Comment, CommentReport
from apps.post.models import Post
from apps.user.models import Role

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule.'


def make_user(email, username, role=Role.AUTHOR, **extra):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Test', last_name='Person', is_verified=True, role=role, **extra
    )


class RoleLadderTests(APITestCase):
    def test_ranking_is_ordered(self):
        contributor = make_user('c@example.com', 'c', Role.CONTRIBUTOR)
        editor = make_user('e@example.com', 'e', Role.EDITOR)
        self.assertLess(contributor.role_rank, editor.role_rank)

    def test_at_least_is_inclusive(self):
        editor = make_user('e@example.com', 'e', Role.EDITOR)
        self.assertTrue(editor.at_least(Role.EDITOR))
        self.assertTrue(editor.at_least(Role.AUTHOR))
        self.assertFalse(editor.at_least(Role.ADMIN))

    def test_capabilities_by_role(self):
        expected = {
            Role.USER: (False, False, False, False),
            Role.MEMBER: (False, False, False, False),
            Role.CONTRIBUTOR: (True, False, False, False),
            Role.AUTHOR: (True, True, False, False),
            Role.MODERATOR: (True, True, False, True),
            Role.EDITOR: (True, True, True, True),
            Role.ADMIN: (True, True, True, True),
            Role.SUPER_ADMIN: (True, True, True, True),
        }
        for index, (role, (write, publish, edit_others, moderate)) in enumerate(expected.items()):
            user = make_user(f'r{index}@example.com', f'r{index}', role)
            self.assertEqual(user.can_write, write, role)
            self.assertEqual(user.can_publish, publish, role)
            self.assertEqual(user.can_edit_others, edit_others, role)
            self.assertEqual(user.can_moderate, moderate, role)

    def test_admins_only_manage_users(self):
        self.assertFalse(make_user('e@example.com', 'e', Role.EDITOR).can_manage_users)
        self.assertTrue(make_user('a@example.com', 'a', Role.ADMIN).can_manage_users)

    def test_an_admin_cannot_grant_super_admin(self):
        admin = make_user('a@example.com', 'a', Role.ADMIN)
        self.assertTrue(admin.may_assign_role(Role.EDITOR))
        self.assertFalse(admin.may_assign_role(Role.ADMIN))
        self.assertFalse(admin.may_assign_role(Role.SUPER_ADMIN))

    def test_a_super_admin_may_grant_anything(self):
        boss = make_user('s@example.com', 's', Role.SUPER_ADMIN)
        self.assertTrue(boss.may_assign_role(Role.SUPER_ADMIN))

    def test_a_superuser_outranks_a_broken_role_value(self):
        user = make_user('root@example.com', 'root', Role.USER)
        user.is_superuser = True
        self.assertTrue(user.can_manage_users)

    def test_admin_roles_get_django_admin_access(self):
        admin = make_user('a@example.com', 'a', Role.ADMIN)
        self.assertTrue(admin.is_staff)
        self.assertFalse(make_user('w@example.com', 'w', Role.AUTHOR).is_staff)


class PublishCapabilityTests(APITestCase):
    """A contributor drafts; an author publishes."""

    def setUp(self):
        self.contributor = make_user('c@example.com', 'contrib', Role.CONTRIBUTOR)
        self.author = make_user('a@example.com', 'writer', Role.AUTHOR)
        self.payload = {'title': 'A new story', 'content': BODY}

    def test_a_contributor_may_save_a_draft(self):
        self.client.force_authenticate(self.contributor)
        response = self.client.post(
            '/api/posts/', {**self.payload, 'status': 'draft'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'draft')

    def test_a_contributor_cannot_publish(self):
        self.client.force_authenticate(self.contributor)
        response = self.client.post(
            '/api/posts/', {**self.payload, 'status': 'published'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Post.objects.count(), 0)

    def test_the_refusal_explains_what_to_do(self):
        self.client.force_authenticate(self.contributor)
        response = self.client.post(
            '/api/posts/', {**self.payload, 'status': 'published'}, format='json'
        )
        self.assertIn('cannot publish', str(response.data).lower())

    def test_a_contributor_cannot_publish_by_editing_a_draft_later(self):
        draft = Post.objects.create(title='Draft', content=BODY, author=self.contributor)
        self.client.force_authenticate(self.contributor)
        response = self.client.patch(
            f'/api/posts/{draft.slug}/', {'status': 'published'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'draft')

    def test_an_author_may_publish(self):
        self.client.force_authenticate(self.author)
        response = self.client.post(
            '/api/posts/', {**self.payload, 'status': 'published'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'published')

    def test_an_editor_may_publish_a_contributors_draft(self):
        draft = Post.objects.create(title='Submitted', content=BODY, author=self.contributor)
        editor = make_user('e@example.com', 'editor', Role.EDITOR)

        self.client.force_authenticate(editor)
        response = self.client.patch(
            f'/api/posts/{draft.slug}/', {'status': 'published'}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'published')
        # The byline stays with the person who wrote it.
        self.assertEqual(draft.author, self.contributor)


class SuspensionTests(APITestCase):
    def setUp(self):
        self.user = make_user('s@example.com', 'suspended')

    def test_a_suspended_account_cannot_sign_in(self):
        self.user.is_suspended = True
        self.user.suspension_reason = 'Repeated spam'
        self.user.save()

        response = self.client.post('/api/auth/login/', {
            'email': 's@example.com', 'password': 'StrongPass!234',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('suspended', response.data['detail'].lower())
        self.assertIn('Repeated spam', response.data['detail'])

    def test_an_expired_suspension_stops_applying(self):
        from datetime import timedelta

        from django.utils import timezone

        self.user.is_suspended = True
        self.user.suspended_until = timezone.now() - timedelta(hours=1)
        self.user.save()

        self.assertFalse(self.user.is_currently_suspended)
        response = self.client.post('/api/auth/login/', {
            'email': 's@example.com', 'password': 'StrongPass!234',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class AdminEndpointTests(APITestCase):
    def setUp(self):
        self.admin = make_user('a@example.com', 'admin', Role.ADMIN)
        self.author = make_user('w@example.com', 'writer', Role.AUTHOR)
        Post.objects.create(title='Live', content=BODY, author=self.author,
                            status=Post.Status.PUBLISHED)

    def test_stats_require_moderation_rights(self):
        self.client.force_authenticate(self.author)
        self.assertEqual(self.client.get('/api/admin/stats/').status_code,
                         status.HTTP_403_FORBIDDEN)

    def test_stats_are_returned_to_an_admin(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/admin/stats/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_posts'], 1)
        self.assertEqual(response.data['published_posts'], 1)
        self.assertEqual(response.data['total_users'], 2)

    def test_user_list_requires_admin_not_merely_moderator(self):
        moderator = make_user('m@example.com', 'mod', Role.MODERATOR)
        self.client.force_authenticate(moderator)
        self.assertEqual(self.client.get('/api/admin/users/').status_code,
                         status.HTTP_403_FORBIDDEN)

    def test_an_admin_can_change_a_role(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f'/api/admin/users/{self.author.username}/role/',
            {'role': 'editor'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.author.refresh_from_db()
        self.assertEqual(self.author.role, 'editor')

    def test_an_admin_cannot_promote_anyone_to_super_admin(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f'/api/admin/users/{self.author.username}/role/',
            {'role': 'super_admin'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.author.refresh_from_db()
        self.assertEqual(self.author.role, 'author')

    def test_nobody_can_change_their_own_role(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f'/api/admin/users/{self.admin.username}/role/',
            {'role': 'super_admin'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_an_admin_cannot_demote_a_super_admin(self):
        boss = make_user('s@example.com', 'boss', Role.SUPER_ADMIN)
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f'/api/admin/users/{boss.username}/role/', {'role': 'user'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_suspending_and_lifting(self):
        self.client.force_authenticate(self.admin)

        suspended = self.client.post(
            f'/api/admin/users/{self.author.username}/suspend/',
            {'reason': 'Spam'}, format='json',
        )
        self.assertEqual(suspended.status_code, status.HTTP_200_OK)
        self.author.refresh_from_db()
        self.assertTrue(self.author.is_suspended)

        lifted = self.client.delete(f'/api/admin/users/{self.author.username}/suspend/')
        self.assertEqual(lifted.status_code, status.HTTP_200_OK)
        self.author.refresh_from_db()
        self.assertFalse(self.author.is_suspended)

    def test_you_cannot_suspend_yourself(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            f'/api/admin/users/{self.admin.username}/suspend/', {}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_the_admin_user_list_exposes_emails(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/admin/users/')
        emails = [row['email'] for row in response.data['results']]
        self.assertIn('w@example.com', emails)

    def test_capability_flags_are_reported_on_me(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/users/me/')
        self.assertEqual(response.data['role'], 'admin')
        self.assertTrue(response.data['can_manage_users'])
        self.assertTrue(response.data['can_moderate'])


class ModerationQueueTests(APITestCase):
    def setUp(self):
        self.moderator = make_user('m@example.com', 'mod', Role.MODERATOR)
        self.author = make_user('w@example.com', 'writer')
        self.reader = make_user('r@example.com', 'reader')

        self.post = Post.objects.create(title='Live', content=BODY, author=self.author,
                                        status=Post.Status.PUBLISHED)
        self.comment = Comment.objects.create(post=self.post, author=self.reader,
                                              content='Buy cheap watches')
        self.report = CommentReport.objects.create(
            comment=self.comment, reporter=self.author, reason='spam',
        )

    def test_the_queue_lists_open_reports(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.get('/api/admin/reports/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['comment_content'], 'Buy cheap watches')

    def test_the_queue_is_closed_to_ordinary_users(self):
        self.client.force_authenticate(self.reader)
        self.assertEqual(self.client.get('/api/admin/reports/').status_code,
                         status.HTTP_403_FORBIDDEN)

    def test_hiding_removes_the_comment_from_public_threads(self):
        self.client.force_authenticate(self.moderator)
        response = self.client.post(
            f'/api/admin/reports/{self.report.id}/action/', {'action': 'hide'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.comment.refresh_from_db()
        self.assertTrue(self.comment.is_hidden)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, 'reviewed')

        public = self.client.get(f'/api/posts/{self.post.slug}/comments/')
        self.assertEqual(public.data['count'], 0)

    def test_dismissing_leaves_the_comment_visible(self):
        self.client.force_authenticate(self.moderator)
        self.client.post(
            f'/api/admin/reports/{self.report.id}/action/', {'action': 'dismiss'}, format='json',
        )
        self.comment.refresh_from_db()
        self.assertFalse(self.comment.is_hidden)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, 'dismissed')

    def test_a_hidden_comment_can_be_restored(self):
        self.comment.is_hidden = True
        self.comment.save()

        self.client.force_authenticate(self.moderator)
        self.client.post(
            f'/api/admin/reports/{self.report.id}/action/', {'action': 'unhide'}, format='json',
        )
        self.comment.refresh_from_db()
        self.assertFalse(self.comment.is_hidden)

    def test_moderating_never_deletes_the_comment(self):
        self.client.force_authenticate(self.moderator)
        self.client.post(
            f'/api/admin/reports/{self.report.id}/action/', {'action': 'hide'}, format='json',
        )
        self.assertTrue(Comment.objects.filter(pk=self.comment.pk).exists())
