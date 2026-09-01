"""Comment creation, editing, ownership and threading tests."""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.comment.models import Comment
from apps.post.models import Post

User = get_user_model()
BODY = 'This is a body long enough to satisfy the minimum content length rule.'


def make_user(email='writer@example.com', username='writer'):
    return User.objects.create_user(
        email=email, username=username, password='StrongPass!234',
        first_name='Ada', last_name='Lovelace', is_verified=True,
    )


class CommentTests(APITestCase):
    def setUp(self):
        self.author = make_user()
        self.reader = make_user('reader@example.com', 'reader')
        self.post = Post.objects.create(
            title='A post to discuss', content=BODY, author=self.author,
            status=Post.Status.PUBLISHED,
        )
        self.url = f'/api/posts/{self.post.slug}/comments/'

    # -- reading -----------------------------------------------------------

    def test_anonymous_visitors_can_read_comments(self):
        Comment.objects.create(post=self.post, author=self.reader, content='Nice write-up.')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_comment_payload_carries_the_author_block(self):
        Comment.objects.create(post=self.post, author=self.reader, content='Nice write-up.')
        row = self.client.get(self.url).data['results'][0]
        for field in ('id', 'author', 'content', 'created_at', 'updated_at', 'replies', 'can_edit'):
            self.assertIn(field, row)
        self.assertEqual(row['author']['username'], 'reader')

    def test_reading_a_thread_does_not_scale_queries_with_replies(self):
        for index in range(5):
            parent = Comment.objects.create(post=self.post, author=self.reader,
                                            content=f'Comment {index}')
            Comment.objects.create(post=self.post, author=self.author,
                                   content='A reply', parent=parent)
        # post lookup, comment count, comment page, prefetched replies
        with self.assertNumQueries(4):
            self.client.get(self.url)

    # -- creating ----------------------------------------------------------

    def test_anonymous_cannot_comment(self):
        response = self.client.post(self.url, {'content': 'Hello'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_signed_in_user_can_comment(self):
        self.client.force_authenticate(self.reader)
        response = self.client.post(self.url, {'content': 'Great post!'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['content'], 'Great post!')
        self.assertEqual(response.data['author']['username'], 'reader')

    def test_empty_comment_is_rejected(self):
        self.client.force_authenticate(self.reader)
        response = self.client.post(self.url, {'content': '   '}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_comment_count_appears_on_the_post(self):
        self.client.force_authenticate(self.reader)
        self.client.post(self.url, {'content': 'One'}, format='json')
        self.client.post(self.url, {'content': 'Two'}, format='json')

        post = self.client.get(f'/api/posts/{self.post.slug}/')
        self.assertEqual(post.data['comment_count'], 2)

    # -- replies -----------------------------------------------------------

    def test_reply_is_nested_under_its_parent(self):
        parent = Comment.objects.create(post=self.post, author=self.reader, content='Question?')
        self.client.force_authenticate(self.author)
        reply = self.client.post(self.url, {'content': 'Answer!', 'parent': str(parent.id)},
                                 format='json')

        self.assertEqual(reply.status_code, status.HTTP_201_CREATED)
        thread = self.client.get(self.url).data
        self.assertEqual(thread['count'], 1)  # only top-level rows are paginated
        self.assertEqual(thread['results'][0]['replies'][0]['content'], 'Answer!')

    def test_replying_to_a_reply_flattens_onto_the_top_level_thread(self):
        parent = Comment.objects.create(post=self.post, author=self.reader, content='Question?')
        reply = Comment.objects.create(post=self.post, author=self.author,
                                       content='Answer', parent=parent)

        self.client.force_authenticate(self.reader)
        nested = self.client.post(self.url, {'content': 'Follow-up', 'parent': str(reply.id)},
                                  format='json')
        self.assertEqual(nested.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Comment.objects.get(pk=nested.data['id']).parent_id, parent.id)

    def test_parent_from_another_post_is_rejected(self):
        other_post = Post.objects.create(title='Another post', content=BODY, author=self.author,
                                         status=Post.Status.PUBLISHED)
        foreign = Comment.objects.create(post=other_post, author=self.reader, content='Elsewhere')

        self.client.force_authenticate(self.reader)
        response = self.client.post(self.url, {'content': 'Wrong thread', 'parent': str(foreign.id)},
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -- editing and deleting ---------------------------------------------

    def test_author_can_edit_their_own_comment(self):
        comment = Comment.objects.create(post=self.post, author=self.reader, content='Typo here')
        self.client.force_authenticate(self.reader)
        response = self.client.patch(f'/api/comments/{comment.id}/', {'content': 'Fixed'},
                                     format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['content'], 'Fixed')
        self.assertTrue(response.data['is_edited'])

    def test_a_different_user_cannot_edit_someone_elses_comment(self):
        comment = Comment.objects.create(post=self.post, author=self.reader, content='Mine')
        self.client.force_authenticate(self.author)
        response = self.client.patch(f'/api/comments/{comment.id}/', {'content': 'Hijacked'},
                                     format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        comment.refresh_from_db()
        self.assertEqual(comment.content, 'Mine')

    def test_a_different_user_cannot_delete_someone_elses_comment(self):
        comment = Comment.objects.create(post=self.post, author=self.reader, content='Mine')
        self.client.force_authenticate(self.author)
        response = self.client.delete(f'/api/comments/{comment.id}/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())

    def test_author_can_delete_their_own_comment(self):
        comment = Comment.objects.create(post=self.post, author=self.reader, content='Mine')
        self.client.force_authenticate(self.reader)
        response = self.client.delete(f'/api/comments/{comment.id}/')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())

    def test_staff_may_moderate_any_comment(self):
        comment = Comment.objects.create(post=self.post, author=self.reader, content='Spam')
        staff = make_user('staff@example.com', 'staff')
        staff.is_staff = True
        staff.save()

        self.client.force_authenticate(staff)
        response = self.client.delete(f'/api/comments/{comment.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_the_post_of_a_comment_cannot_be_reassigned_by_an_edit(self):
        other_post = Post.objects.create(title='Another post', content=BODY, author=self.author,
                                         status=Post.Status.PUBLISHED)
        comment = Comment.objects.create(post=self.post, author=self.reader, content='Mine')

        self.client.force_authenticate(self.reader)
        self.client.patch(f'/api/comments/{comment.id}/',
                          {'content': 'Mine', 'post': str(other_post.id)}, format='json')

        comment.refresh_from_db()
        self.assertEqual(comment.post_id, self.post.id)

    def test_comments_on_someone_elses_draft_are_not_reachable(self):
        draft = Post.objects.create(title='Secret draft', content=BODY, author=self.author,
                                    status=Post.Status.DRAFT)
        self.client.force_authenticate(self.reader)
        response = self.client.get(f'/api/posts/{draft.slug}/comments/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
