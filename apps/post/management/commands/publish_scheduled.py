"""
Promote scheduled posts whose time has come.

The queryset already treats a scheduled post with a past date as published, so
the site is correct without this ever running. What the command adds is tidiness
— the stored `status` catches up with reality — which keeps the admin, the
dashboard counts and any future export from disagreeing with the public site.

Run it from cron, as often as your scheduling granularity needs:

    */5 * * * * cd /srv/blog && ./venv/bin/python manage.py publish_scheduled
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.post.models import Post


class Command(BaseCommand):
    help = 'Flip scheduled posts whose publication time has passed to published.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List what would be published without changing anything.',
        )

    def handle(self, *args, **options):
        now = timezone.now()
        due = Post.objects.filter(
            status=Post.Status.SCHEDULED,
            scheduled_for__lte=now,
            deleted_at__isnull=True,
        )

        if not due.exists():
            self.stdout.write('Nothing is due.')
            return

        for post in due:
            self.stdout.write(f'  {post.slug}  (was due {post.scheduled_for:%Y-%m-%d %H:%M})')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(f'{due.count()} post(s) would be published.'))
            return

        # published_at was already set to scheduled_for when the post was
        # scheduled, so the article keeps the date readers were promised
        # rather than the moment this command happened to run.
        count = due.update(status=Post.Status.PUBLISHED)
        self.stdout.write(self.style.SUCCESS(f'Published {count} post(s).'))
