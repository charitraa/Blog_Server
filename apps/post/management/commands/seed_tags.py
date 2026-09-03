"""
Creates a starting set of tags.

Tags are free-form — an author can type a new one while writing — but an empty
tag list makes the editor's picker and the tag pages look broken on a fresh
install. These are the labels the baseline categories imply, so the site has
something to filter by on day one.

Like `seed_categories`, this only ever adds. Matching is case-insensitive
(via `Tag.get_or_create_by_name`), so re-running it never creates a second
"Django" alongside "django".
"""

from django.core.management.base import BaseCommand

from apps.post.models import Tag

TAGS = [
    # Technology / programming
    'Python', 'Django', 'JavaScript', 'TypeScript', 'React', 'CSS',
    'API', 'Databases', 'Testing', 'DevOps', 'Open Source', 'Performance',
    # Cybersecurity
    'Security', 'Privacy', 'Cryptography',
    # Design
    'UI', 'UX', 'Accessibility', 'Typography',
    # Business / education / life
    'Career', 'Productivity', 'Writing', 'Tutorial', 'Opinion',
    'Machine Learning', 'Self Hosting', 'Books',
]


class Command(BaseCommand):
    help = 'Create the baseline post tags if they do not already exist.'

    def handle(self, *args, **options):
        created = 0
        for name in TAGS:
            if Tag.objects.filter(name__iexact=name).exists():
                continue
            Tag.get_or_create_by_name(name)
            created += 1
            self.stdout.write(self.style.SUCCESS(f'  + {name}'))

        total = Tag.objects.count()
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created {created} tags ({total} total).'))
        else:
            self.stdout.write(f'All tags already present ({total} total).')
