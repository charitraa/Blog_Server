"""
Diagnose the outgoing mail configuration.

Every email the site sends — verification codes, password resets, newsletter
confirmations — goes through the same settings. When one of them fails the
sending code logs the error and moves on, because a mail outage must never turn
into a 500 for the person using the site. That safety net also means a
misconfiguration is invisible from the outside, which is what this command is
for: it reports the effective settings, proves the credentials, and optionally
sends a real message.
"""

import smtplib

from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Report the mail configuration, test the SMTP login, and optionally send a test email.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--to',
            help='Send a real test email to this address. Defaults to EMAIL_HOST_USER.',
        )
        parser.add_argument(
            '--send',
            action='store_true',
            help='Actually send the test email (otherwise only the login is tested).',
        )

    def handle(self, *args, **options):
        backend = settings.EMAIL_BACKEND
        is_smtp = backend.endswith('smtp.EmailBackend')

        self.stdout.write(self.style.MIGRATE_HEADING('Effective mail settings'))
        self.stdout.write(f'  EMAIL_BACKEND      {backend}')
        self.stdout.write(f'  EMAIL_HOST         {settings.EMAIL_HOST}:{settings.EMAIL_PORT}')
        self.stdout.write(f'  EMAIL_USE_TLS      {settings.EMAIL_USE_TLS}')
        self.stdout.write(f'  EMAIL_HOST_USER    {settings.EMAIL_HOST_USER or "(blank)"}')
        self.stdout.write(
            f'  EMAIL_HOST_PASSWORD {"set, " + str(len(settings.EMAIL_HOST_PASSWORD)) + " chars" if settings.EMAIL_HOST_PASSWORD else "(blank)"}'
        )
        self.stdout.write(f'  DEFAULT_FROM_EMAIL {settings.DEFAULT_FROM_EMAIL}')
        self.stdout.write('')

        if not is_smtp:
            self.stdout.write(self.style.WARNING(
                'Not using SMTP: emails are written to the console, not delivered.\n'
                'Set EMAIL_HOST_USER and EMAIL_HOST_PASSWORD in .env to send real mail.'
            ))
            return

        if settings.DEFAULT_FROM_EMAIL != settings.EMAIL_HOST_USER:
            self.stdout.write(self.style.WARNING(
                f'DEFAULT_FROM_EMAIL ({settings.DEFAULT_FROM_EMAIL}) is not the authenticated\n'
                f'account ({settings.EMAIL_HOST_USER}). Most providers reject or rewrite this.'
            ))
            self.stdout.write('')

        self.stdout.write(self.style.MIGRATE_HEADING('SMTP login'))
        connection = get_connection()
        try:
            connection.open()
            connection.close()
            self.stdout.write(self.style.SUCCESS('  Connected and authenticated.'))
        except smtplib.SMTPAuthenticationError as exc:
            self.stdout.write(self.style.ERROR(f'  Credentials rejected: {exc.smtp_code} {exc.smtp_error.decode(errors="replace") if isinstance(exc.smtp_error, bytes) else exc.smtp_error}'))
            self.stdout.write(
                '\n  For a Google account this almost always means the password is not a\n'
                '  valid App Password. Turn on 2-Step Verification, then create one at\n'
                '  https://myaccount.google.com/apppasswords and paste it as\n'
                '  EMAIL_HOST_PASSWORD. A normal account password will not work.'
            )
            return
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'  Could not connect: {type(exc).__name__}: {exc}'))
            return

        recipient = options['to'] or settings.EMAIL_HOST_USER
        if not options['send']:
            self.stdout.write(
                f'\nConfiguration looks usable. Re-run with --send to email {recipient}.'
            )
            return

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(f'Sending a test email to {recipient}'))
        try:
            send_mail(
                f'{settings.SITE_NAME} — mail configuration test',
                'If you are reading this, verification codes, password resets and '
                'newsletter confirmations will all send correctly.',
                settings.DEFAULT_FROM_EMAIL,
                [recipient],
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS('  Accepted by the server. Check the inbox (and spam).'))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'  Send failed: {type(exc).__name__}: {exc}'))
