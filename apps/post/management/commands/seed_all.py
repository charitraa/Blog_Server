"""
One command a deploy can call.

The individual seeds are small and safe on their own, but a deploy script
should not have to know the list — or the order, since the demo content needs
the categories and tags to already exist. This runs all of them, and is the
command `build.sh` calls on Render.

    python manage.py seed_all              # migrate + categories + tags + admin
    python manage.py seed_all --demo       # ... and sample content (development)
    python manage.py seed_all --no-migrate # when migrations ran in an earlier step

Every step is idempotent, so this belongs in a build command that runs on every
deploy, not in a one-off console session you have to remember.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run every seed: migrations, categories, tags, the admin account and optional demo data.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--demo',
            action='store_true',
            help='Also create the sample users, posts and comments (development only).',
        )
        parser.add_argument(
            '--no-migrate',
            action='store_true',
            help='Skip `migrate`, for when the deploy already ran it.',
        )
        parser.add_argument(
            '--force-password',
            action='store_true',
            help='Passed through to seed_admin: reset an existing admin password.',
        )

    def handle(self, *args, **options):
        steps = []
        if not options['no_migrate']:
            steps.append(('Applying migrations', 'migrate', {'interactive': False}))
        steps += [
            ('Categories', 'seed_categories', {}),
            ('Tags', 'seed_tags', {}),
            ('Admin account', 'seed_admin', {'force_password': options['force_password']}),
        ]
        if options['demo']:
            steps.append(('Demo content', 'seed_demo', {}))

        for label, command, kwargs in steps:
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n{label}'))
            call_command(command, **kwargs)

        self.stdout.write(self.style.SUCCESS('\nSeeding complete.'))
