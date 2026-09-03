"""
Fills a fresh install with believable sample content.

This is the opposite of `seed_categories` and `seed_tags`: those create
reference data a real site needs, this creates *fake* data so the frontend,
the dashboard counters and the moderation queue have something to render before
anybody has written a word. Nothing here should ever exist on a live site,
which is why the command refuses to run with DEBUG off unless you insist.

Every row is keyed on a stable identifier (a demo email, a fixed slug), so
re-running the command updates nothing and duplicates nothing. Demo accounts
use @example.com addresses — a domain reserved by RFC 2606 — so a stray
notification email can never reach a real person.

    python manage.py seed_demo            # create
    python manage.py seed_demo --undo     # remove every demo account and its content

Comments, likes and follows are created through the ORM, so the notification
signals fire and the demo inbox fills up on its own.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.comment.models import Comment, CommentLike, CommentReport
from apps.newsletter.models import NewsletterSubscriber
from apps.post.models import (
    Bookmark, Category, Like, Post, ReadingHistory, Series, SeriesPost, Tag,
)
from apps.user.models import Follow, Role, TopicFollow, User

DEMO_PASSWORD = 'MindfulDemo!2024'

# (email, username, first, last, role, headline, bio)
DEMO_USERS = [
    (
        'editor@example.com', 'demo-editor', 'Ada', 'Whitfield', Role.EDITOR,
        'Editor at Marginalia',
        'I read everything before it goes out. Commas are not optional.',
    ),
    (
        'author@example.com', 'demo-author', 'Rafael', 'Okonkwo', Role.AUTHOR,
        'Backend engineer',
        'Django, Postgres and the unglamorous work of keeping an API honest.',
    ),
    (
        'designer@example.com', 'demo-designer', 'Mira', 'Lindqvist', Role.AUTHOR,
        'Interface designer',
        'Type, spacing, and why your form needs fewer fields than you think.',
    ),
    (
        'contributor@example.com', 'demo-contributor', 'Tomas', 'Bergeron', Role.CONTRIBUTOR,
        'Writes occasionally',
        'First-time contributor. Currently waiting on a review.',
    ),
    (
        'reader@example.com', 'demo-reader', 'Ines', 'Haddad', Role.MEMBER,
        'Reader',
        'Here for the long-form posts and the comment threads.',
    ),
]

# (slug, author email, category, tags, status, visibility, title, subtitle, body)
DEMO_POSTS = [
    (
        'why-your-api-should-be-boring', 'author@example.com', 'Programming',
        ['Python', 'Django', 'API'], Post.Status.PUBLISHED, Post.Visibility.PUBLIC,
        'Why your API should be boring',
        'Predictability is a feature, and cleverness has a maintenance bill.',
        '<p>The best endpoint I ever wrote does one thing, returns the same shape '
        'every time, and has not been touched in three years.</p>'
        '<h2>Consistency beats elegance</h2>'
        '<p>A client integrating against your API is building a mental model of it. '
        'Every exception to your own conventions costs somebody an afternoon.</p>'
        '<ul><li>One resource per URL.</li><li>Errors in one shape, everywhere.</li>'
        '<li>Pagination that never changes its mind.</li></ul>'
        '<p>Boring is what lets a second team ship against you without asking you '
        'anything.</p>',
    ),
    (
        'the-database-is-not-a-detail', 'author@example.com', 'Programming',
        ['Databases', 'Performance', 'Django'], Post.Status.PUBLISHED, Post.Visibility.PUBLIC,
        'The database is not a detail',
        'Most slow applications are fast applications asking bad questions.',
        '<p>Before you add a cache, look at the queries. The answer is usually '
        '<code>select_related</code> and an index nobody created.</p>'
        '<h2>Count your queries</h2>'
        '<p>A list view that issues one query per row will look fine on your laptop '
        'with twelve rows in it, and fall over the week you get readers.</p>'
        '<blockquote>An index is a promise about how the data will be read.</blockquote>',
    ),
    (
        'forms-with-fewer-fields', 'designer@example.com', 'Design',
        ['UX', 'Accessibility', 'UI'], Post.Status.PUBLISHED, Post.Visibility.PUBLIC,
        'Forms with fewer fields',
        'Every input is a question you are making somebody answer.',
        '<p>The fastest way to improve a sign-up form is to delete half of it.</p>'
        '<h2>Ask later, or never</h2>'
        '<p>You do not need a phone number to create an account. You need it when '
        'something actually depends on it, and at that point the person has a '
        'reason to give it to you.</p>'
        '<p>Label every field, never rely on placeholder text, and let the browser '
        'autofill do its job.</p>',
    ),
    (
        'reading-notes-on-attention', 'designer@example.com', 'Personal',
        ['Books', 'Writing'], Post.Status.PUBLISHED, Post.Visibility.MEMBERS,
        'Reading notes on attention',
        'Members-only: a month of notes, mostly unfinished.',
        '<p>I kept a notebook for four weeks about what pulled my attention and '
        'what held it. The two lists barely overlap.</p>'
        '<p>What held it: long articles with headings, printed pages, one '
        'conversation with a friend that ran to two hours.</p>',
    ),
    (
        'threat-modelling-for-small-teams', 'author@example.com', 'Cybersecurity',
        ['Security', 'Privacy'], Post.Status.PUBLISHED, Post.Visibility.PUBLIC,
        'Threat modelling for small teams',
        'You do not need a framework. You need one hour and a whiteboard.',
        '<p>Ask three questions: what would hurt most if it leaked, who would want '
        'it, and what is currently stopping them.</p>'
        '<h2>Write down the boring answers</h2>'
        '<p>Most real incidents are a leaked key or a permission nobody revoked, '
        'not a novel attack.</p>',
    ),
    (
        'shipping-on-a-friday', 'author@example.com', 'Business',
        ['DevOps', 'Testing', 'Opinion'], Post.Status.SCHEDULED, Post.Visibility.PUBLIC,
        'Shipping on a Friday',
        'Scheduled: the rule is not about Fridays.',
        '<p>If a deploy is frightening on a Friday it was frightening on Tuesday '
        'and you were not paying attention.</p>'
        '<p>Fix the rollback, not the calendar.</p>',
    ),
    (
        'notes-on-writing-documentation', 'contributor@example.com', 'Education',
        ['Writing', 'Tutorial'], Post.Status.IN_REVIEW, Post.Visibility.PUBLIC,
        'Notes on writing documentation',
        'Submitted for review — sits in the editor queue.',
        '<p>Documentation fails in a predictable way: it explains what the code is '
        'instead of what the reader is trying to do.</p>'
        '<p>Start from the task. "How do I authenticate a request" is a heading. '
        '"The authentication module" is not.</p>',
    ),
    (
        'draft-half-an-idea-about-caching', 'author@example.com', 'Programming',
        ['Performance'], Post.Status.DRAFT, Post.Visibility.PRIVATE,
        'Half an idea about caching',
        '',
        '<p>Unfinished draft. Only the author and an editor can see this one, which '
        'is what makes it useful for testing the dashboard.</p>',
    ),
]

# A three-part series, assembled from posts seeded above.
DEMO_SERIES = (
    'building-an-api-you-can-live-with',
    'Building an API you can live with',
    'author@example.com',
    'Three posts on the parts of an API that only hurt after a year in production.',
    ['why-your-api-should-be-boring', 'the-database-is-not-a-detail',
     'threat-modelling-for-small-teams'],
)

# (post slug, commenter email, body, [(replier email, reply body)])
DEMO_COMMENTS = [
    (
        'why-your-api-should-be-boring', 'reader@example.com',
        'The pagination point is underrated. We changed ours once and broke every '
        'client we had.',
        [('author@example.com', 'Exactly this — and the clients you break are '
                                'always the ones you cannot contact.')],
    ),
    (
        'why-your-api-should-be-boring', 'designer@example.com',
        'Would love a follow-up on error shapes. @demo-editor is this house style now?',
        [],
    ),
    (
        'forms-with-fewer-fields', 'contributor@example.com',
        'We cut four fields from our sign-up and completion went up by a third. '
        'No other change.',
        [('designer@example.com', 'That matches everything I have seen. Thanks for '
                                  'the number.')],
    ),
    (
        'the-database-is-not-a-detail', 'reader@example.com',
        'Buy cheap tokens here!!! www.definitely-not-spam.example',
        [],
    ),
]

DEMO_SUBSCRIBERS = [
    ('subscriber.one@example.com', True),
    ('subscriber.two@example.com', True),
    ('unconfirmed@example.com', False),
]

DEMO_EMAILS = [row[0] for row in DEMO_USERS]


class Command(BaseCommand):
    help = 'Create sample users, posts, comments, likes and subscribers for development.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--undo',
            action='store_true',
            help='Delete the demo accounts and everything they own, and the demo subscribers.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Allow this to run with DEBUG off. Almost certainly a mistake.',
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options['force']:
            raise CommandError(
                'seed_demo creates fake accounts with a shared, published password '
                'and refuses to run with DEBUG off. Pass --force if this really is '
                'a throwaway environment.'
            )

        if options['undo']:
            self._undo()
            return

        with transaction.atomic():
            users = self._users()
            posts = self._posts(users)
            self._series(users, posts)
            comments = self._comments(users, posts)
            self._reactions(users, posts, comments)
            self._graph(users)
            self._subscribers()

        self.stdout.write(self.style.SUCCESS('\nDemo data ready.'))
        self.stdout.write(f'  Sign in as any of: {", ".join(DEMO_EMAILS)}')
        self.stdout.write(f'  Password for all of them: {DEMO_PASSWORD}')
        self.stdout.write('  Remove it all again with: manage.py seed_demo --undo')

    # --- create ---------------------------------------------------------

    def _users(self):
        """Demo accounts, pre-verified so they can sign in without the email step."""
        users = {}
        for email, username, first, last, role, headline, bio in DEMO_USERS:
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                user = User.objects.create_user(
                    email=email,
                    password=DEMO_PASSWORD,
                    username=username,
                    first_name=first,
                    last_name=last,
                    role=role,
                    headline=headline,
                    bio=bio,
                    is_verified=True,
                )
                self.stdout.write(self.style.SUCCESS(f'  + user {email} ({role})'))
            users[email] = user
        return users

    def _posts(self, users):
        posts = {}
        now = timezone.now()
        for index, row in enumerate(DEMO_POSTS):
            (slug, author_email, category_name, tag_names, status, visibility,
             title, subtitle, body) = row

            existing = Post.objects.filter(slug=slug).first()
            if existing:
                posts[slug] = existing
                continue

            category = Category.objects.filter(name__iexact=category_name).first()
            if category is None:
                self.stdout.write(self.style.WARNING(
                    f'  ! category "{category_name}" is missing — run seed_categories first'
                ))

            post = Post(
                slug=slug,
                title=title,
                subtitle=subtitle,
                content=body,
                author=users[author_email],
                category=category,
                status=status,
                visibility=visibility,
                # Spread the dates so "latest" and the archive have something to
                # order by instead of every post sharing one timestamp.
                scheduled_for=now + timedelta(days=3) if status == Post.Status.SCHEDULED else None,
                is_featured=index == 0,
                view_count=140 - index * 12,
            )
            post.save()

            # published_at is stamped by save() as "now" for every post, which
            # would make the whole archive look like it appeared at once.
            if post.status == Post.Status.PUBLISHED:
                Post.objects.filter(pk=post.pk).update(
                    published_at=now - timedelta(days=2 + index * 5),
                )
                post.refresh_from_db()

            tags = [Tag.get_or_create_by_name(name) for name in tag_names]
            post.tags.set([tag for tag in tags if tag])

            posts[slug] = post
            self.stdout.write(self.style.SUCCESS(f'  + post {slug} ({status})'))
        return posts

    def _series(self, users, posts):
        slug, title, author_email, description, member_slugs = DEMO_SERIES
        series, created = Series.objects.get_or_create(
            slug=slug,
            defaults={
                'title': title,
                'author': users[author_email],
                'description': description,
            },
        )
        for position, post_slug in enumerate(member_slugs, start=1):
            post = posts.get(post_slug)
            if post:
                SeriesPost.objects.get_or_create(
                    series=series, post=post, defaults={'position': position},
                )
        if created:
            self.stdout.write(self.style.SUCCESS(f'  + series {slug}'))
        return series

    def _comments(self, users, posts):
        created = []
        for post_slug, author_email, body, replies in DEMO_COMMENTS:
            post = posts.get(post_slug)
            if post is None:
                continue

            comment = Comment.objects.filter(post=post, author=users[author_email], content=body).first()
            if comment is None:
                comment = Comment.objects.create(
                    post=post, author=users[author_email], content=body,
                )
                self.stdout.write(self.style.SUCCESS(f'  + comment on {post_slug}'))
            created.append(comment)

            for replier_email, reply_body in replies:
                # Appended whether or not it is new, so the returned list is the
                # same on every run — `_reactions` picks comments out of it by
                # position, and a list that shifted would like a different
                # comment each time.
                reply = Comment.objects.filter(parent=comment, content=reply_body).first()
                if reply is None:
                    reply = Comment.objects.create(
                        post=post,
                        parent=comment,
                        author=users[replier_email],
                        content=reply_body,
                    )
                created.append(reply)

        self._moderation(users, created)
        return created

    def _moderation(self, users, comments):
        """
        Give the moderation queue one open report to show.

        The last demo comment is deliberately spam, so the admin moderation view
        has a real row instead of an empty state.
        """
        spam = next(
            (comment for comment in comments if 'definitely-not-spam' in comment.content),
            None,
        )
        if spam is None:
            return
        _, created = CommentReport.objects.get_or_create(
            comment=spam,
            reporter=users['editor@example.com'],
            defaults={
                'reason': CommentReport.Reason.SPAM,
                'detail': 'Link farm. Same text posted on three other threads.',
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS('  + open comment report'))

    def _reactions(self, users, posts, comments):
        """Reactions, bookmarks and reading progress from the demo readers."""
        reactors = [users['reader@example.com'], users['contributor@example.com'],
                    users['editor@example.com']]
        kinds = [Like.Kind.LIKE, Like.Kind.LOVE, Like.Kind.INSIGHTFUL]

        published = [
            post for post in posts.values()
            if post.status == Post.Status.PUBLISHED
        ]
        added = 0
        for offset, post in enumerate(published):
            for index, user in enumerate(reactors):
                if post.author_id == user.id:
                    continue
                _, created = Like.objects.get_or_create(
                    post=post, user=user,
                    defaults={'kind': kinds[(offset + index) % len(kinds)]},
                )
                added += created
            _, created = Bookmark.objects.get_or_create(
                post=post, user=users['reader@example.com'],
            )
            added += created
            _, created = ReadingHistory.objects.get_or_create(
                post=post,
                user=users['reader@example.com'],
                defaults={
                    'progress': 100 if offset % 2 == 0 else 45,
                    'is_finished': offset % 2 == 0,
                },
            )
            added += created

        for comment in comments[:3]:
            if comment.author_id != users['reader@example.com'].id:
                _, created = CommentLike.objects.get_or_create(
                    comment=comment, user=users['reader@example.com'],
                )
                added += created

        self._report('reactions, bookmarks and reading history', added)

    def _graph(self, users):
        """Follows between the demo accounts, plus a couple of topic follows."""
        pairs = [
            ('reader@example.com', 'author@example.com'),
            ('reader@example.com', 'designer@example.com'),
            ('contributor@example.com', 'author@example.com'),
            ('designer@example.com', 'author@example.com'),
        ]
        added = 0
        for follower_email, following_email in pairs:
            _, created = Follow.objects.get_or_create(
                follower=users[follower_email], following=users[following_email],
            )
            added += created

        reader = users['reader@example.com']
        for name in ('Programming', 'Cybersecurity'):
            category = Category.objects.filter(name__iexact=name).first()
            if category:
                _, created = TopicFollow.objects.get_or_create(user=reader, category=category)
                added += created
        tag = Tag.objects.filter(name__iexact='Django').first()
        if tag:
            _, created = TopicFollow.objects.get_or_create(user=reader, tag=tag)
            added += created

        self._report('follows and topic follows', added)

    def _subscribers(self):
        added = 0
        for email, confirmed in DEMO_SUBSCRIBERS:
            subscriber, created = NewsletterSubscriber.objects.get_or_create(email=email)
            if created and confirmed:
                subscriber.confirm()
            added += created
        self._report('newsletter subscribers', added)

    def _report(self, label, added):
        """Say what was created, so a second run does not claim to have added rows."""
        if added:
            self.stdout.write(self.style.SUCCESS(f'  + {added} {label}'))
        else:
            self.stdout.write(f'  = {label} already present')

    # --- remove ---------------------------------------------------------

    def _undo(self):
        """
        Delete only what this command creates.

        Demo accounts are matched by their exact seeded addresses, and deleting a
        user cascades to their posts, comments, likes and notifications — so
        nothing written by a real account is touched.
        """
        with transaction.atomic():
            users = User.objects.filter(email__in=DEMO_EMAILS)
            user_count = users.count()
            users.delete()

            Post.objects.filter(slug__in=[row[0] for row in DEMO_POSTS]).delete()
            Series.objects.filter(slug=DEMO_SERIES[0]).delete()
            subscribers = NewsletterSubscriber.objects.filter(
                email__in=[email for email, _ in DEMO_SUBSCRIBERS],
            )
            subscriber_count = subscribers.count()
            subscribers.delete()

        self.stdout.write(self.style.SUCCESS(
            f'Removed {user_count} demo account(s) and {subscriber_count} demo subscriber(s). '
            'Categories and tags were left alone.'
        ))
