"""
Build or refresh the semantic search index.

Embeddings are generated here rather than on every save so that publishing a
post is not held up by a call to an external service, and so a bulk import does
not fire hundreds of paid API calls one at a time.

Run it after importing content, after changing the embedding model, or on a
schedule:

    */30 * * * * cd /srv/blog && ./venv/bin/python manage.py build_search_index
"""

from django.core.management.base import BaseCommand, CommandError

from apps.ai.embeddings import EmbeddingUnavailable, is_configured
from apps.post.models import Post, PostEmbedding
from apps.post.search import refresh_embedding


class Command(BaseCommand):
    help = 'Generate embeddings for published posts so semantic search can find them.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='Re-embed everything, even posts that have not changed.')
        parser.add_argument('--limit', type=int,
                            help='Stop after this many posts.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what needs embedding without calling the API.')

    def handle(self, *args, **options):
        if not is_configured():
            raise CommandError(
                'Embeddings are not configured. Set NVIDIA_API_KEY and NVIDIA_EMBED_MODEL.'
            )

        posts = Post.objects.published().order_by('-published_at')
        if options['limit']:
            posts = posts[:options['limit']]

        done = skipped = failed = 0

        for post in posts:
            existing = PostEmbedding.objects.filter(post=post).first()
            needs = options['force'] or existing is None or existing.is_stale

            if not needs:
                skipped += 1
                continue

            if options['dry_run']:
                self.stdout.write(f'  would embed: {post.slug}')
                done += 1
                continue

            try:
                refresh_embedding(post, force=options['force'])
                self.stdout.write(f'  {post.slug}')
                done += 1
            except EmbeddingUnavailable as exc:
                # Stop rather than burn through the rest against a dead service.
                raise CommandError(f'Embedding failed on {post.slug}: {exc}')
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'  {post.slug}: {exc}'))
                failed += 1

        self.stdout.write('')
        verb = 'Would embed' if options['dry_run'] else 'Embedded'
        self.stdout.write(self.style.SUCCESS(f'{verb}: {done}'))
        self.stdout.write(f'Already current: {skipped}')
        if failed:
            self.stdout.write(self.style.ERROR(f'Failed: {failed}'))
