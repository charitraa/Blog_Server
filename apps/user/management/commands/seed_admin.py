"""
Create (or repair) the owner account without a prompt.

`createsuperuser` asks questions, which makes it useless in the one place an
admin account is hardest to create by hand: a deploy. Render, Docker and CI all
run a non-interactive build step, so this command takes the same three values
from the environment instead and is safe to run on every deploy — it creates the
account the first time and then only ever corrects its flags.

Configure it with ADMIN_EMAIL / ADMIN_USERNAME / ADMIN_PASSWORD (Django's own
DJANGO_SUPERUSER_* names are accepted too, so an existing deploy's variables
keep working).

With nothing configured the behaviour splits on DEBUG, which is the difference
between a laptop and a deploy:

* DEBUG on  — falls back to admin@example.com / MindfulAdmin!2024 and prints
  them, so a fresh clone has a working admin login in one command.
* DEBUG off — reports that it was skipped and exits successfully, so a build
  script can always call it and no deploy ever gets a published password.

An existing account keeps its password. Rotating it is a deliberate act:

    python manage.py seed_admin --force-password
"""

from decouple import config
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.user.models import Role, User

# Local development only, and only when nothing has been configured. Handing
# out a known password is the right trade on a laptop — `runserver` on
# localhost with a throwaway SQLite file is not a thing worth protecting, and
# the alternative is every contributor inventing their own and losing it.
#
# This is why the fallback is gated on DEBUG rather than on "no ADMIN_EMAIL":
# a deploy runs with DEBUG off, where the command skips instead, so these
# credentials can never become a live site's admin login.
DEV_ADMIN_EMAIL = 'admin@example.com'
DEV_ADMIN_USERNAME = 'admin'
DEV_ADMIN_PASSWORD = 'MindfulAdmin!2024'


def _from_env(*names, default=''):
    """First non-empty value among `names`, read the way settings.py reads."""
    for name in names:
        value = config(name, default='')
        if value:
            return value
    return default


class Command(BaseCommand):
    help = 'Create or update the super admin account from the environment, without prompting.'

    def add_arguments(self, parser):
        parser.add_argument('--email', help='Defaults to ADMIN_EMAIL / DJANGO_SUPERUSER_EMAIL.')
        parser.add_argument(
            '--username',
            help='Defaults to ADMIN_USERNAME / DJANGO_SUPERUSER_USERNAME, else derived from the email.',
        )
        parser.add_argument(
            '--password',
            help='Defaults to ADMIN_PASSWORD / DJANGO_SUPERUSER_PASSWORD. Prefer the environment: '
                 'a password typed here lands in your shell history.',
        )
        parser.add_argument(
            '--force-password',
            action='store_true',
            help='Reset the password of an account that already exists.',
        )

    def handle(self, *args, **options):
        email = (options['email'] or _from_env('ADMIN_EMAIL', 'DJANGO_SUPERUSER_EMAIL')).strip().lower()
        username = (options['username'] or _from_env('ADMIN_USERNAME', 'DJANGO_SUPERUSER_USERNAME')).strip()
        password = options['password'] or _from_env('ADMIN_PASSWORD', 'DJANGO_SUPERUSER_PASSWORD')

        used_dev_default = False
        if not email:
            if not settings.DEBUG:
                # Not an error: a build script calls this unconditionally, and a
                # deploy that manages its admin by hand should not fail for it.
                self.stdout.write(
                    'No ADMIN_EMAIL set — skipping admin seed. '
                    'Set ADMIN_EMAIL and ADMIN_PASSWORD to create the owner account.'
                )
                return
            email, username, used_dev_default = DEV_ADMIN_EMAIL, DEV_ADMIN_USERNAME, True
            password = password or DEV_ADMIN_PASSWORD
            self.stdout.write(self.style.WARNING(
                'No ADMIN_EMAIL set — using the development default. '
                'Set ADMIN_EMAIL and ADMIN_PASSWORD in .env to choose your own.'
            ))

        existing = User.objects.filter(email__iexact=email).first()

        if existing is None and not password:
            raise CommandError(
                f'Cannot create {email} without a password. '
                'Set ADMIN_PASSWORD (or pass --password).'
            )

        if password:
            self._check_password(password, email, username)

        if existing:
            self._promote(existing, password if options['force_password'] else None)
        else:
            self._create(email, username, password)

        if used_dev_default:
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING('Development admin login'))
            self.stdout.write(f'  Email / username  {DEV_ADMIN_EMAIL}  (or "{DEV_ADMIN_USERNAME}")')
            self.stdout.write(f'  Password          {DEV_ADMIN_PASSWORD}')
            self.stdout.write('  Admin site        http://localhost:8000/admin/')
            if existing and not options['force_password']:
                self.stdout.write(self.style.WARNING(
                    '  This account already existed, so the password above is only '
                    'right if it was the one it was created with. '
                    'Run with --force-password to set it.'
                ))

    # --- helpers --------------------------------------------------------

    def _check_password(self, password, email, username):
        """
        Refuse a weak password rather than documenting the risk.

        This account can publish, moderate and hand out roles on a site that is
        reachable from the internet, and the value usually arrives from a
        dashboard field where nothing else is checking it.
        """
        probe = User(email=email, username=username or 'admin')
        try:
            validate_password(password, probe)
        except ValidationError as error:
            raise CommandError(
                'The admin password was rejected:\n  '
                + '\n  '.join(error.messages)
            ) from error

    def _create(self, email, username, password):
        user = User.objects.create_superuser(
            email=email,
            password=password,
            username=username or User.generate_username(email),
            role=Role.SUPER_ADMIN,
        )
        self.stdout.write(self.style.SUCCESS(
            f'Created super admin {user.email} (username: {user.username}).'
        ))

    def _promote(self, user, new_password):
        """
        Make sure an account that already exists can actually sign in as owner.

        This is the case that bites on a real deploy: the account was made
        before the role ladder existed, or email verification was switched on
        afterwards, and the owner is locked out of their own site. Re-running
        the seed fixes it.
        """
        fields = []
        for field, value in (
            ('is_staff', True),
            ('is_superuser', True),
            ('is_active', True),
            ('is_verified', True),
            ('is_suspended', False),
            ('role', Role.SUPER_ADMIN),
        ):
            if getattr(user, field) != value:
                setattr(user, field, value)
                fields.append(field)

        if new_password:
            user.set_password(new_password)
            fields.append('password')

        if not fields:
            self.stdout.write(f'{user.email} is already the super admin. Nothing to do.')
            return

        user.save(update_fields=fields)
        changed = ', '.join(fields)
        self.stdout.write(self.style.SUCCESS(f'Updated {user.email} ({changed}).'))
        if 'password' not in fields:
            self.stdout.write(
                '  Password left as it was. Use --force-password to rotate it.'
            )
