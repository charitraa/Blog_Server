"""Creates the baseline set of categories the publishing UI offers.

Categories are reference data, not sample content: the editor needs them to
exist before an author can file a post. Running this repeatedly is safe — it
only adds what is missing and never edits or deletes an existing row.
"""

from django.core.management.base import BaseCommand

from apps.post.models import Category

CATEGORIES = [
    ('Technology', 'Software, hardware and the systems that connect them.'),
    ('Programming', 'Languages, patterns, tooling and craft.'),
    ('Cybersecurity', 'Threats, defences and secure engineering practice.'),
    ('Design', 'Interface, interaction and visual design.'),
    ('Business', 'Product, strategy and the work of building companies.'),
    ('Education', 'Learning, teaching and explaining hard things well.'),
    ('Lifestyle', 'Habits, health and life outside of work.'),
    ('Personal', 'Essays, reflections and personal experience.'),
]


class Command(BaseCommand):
    help = 'Create the baseline blog categories if they do not already exist.'

    def handle(self, *args, **options):
        created = 0
        for name, description in CATEGORIES:
            _, was_created = Category.objects.get_or_create(
                name=name,
                defaults={'description': description},
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f'  + {name}'))

        total = Category.objects.count()
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created {created} categories ({total} total).'))
        else:
            self.stdout.write(f'All categories already present ({total} total).')
