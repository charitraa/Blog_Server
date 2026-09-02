"""
Copy media that is already on disk up to Cloudinary.

Deliberately conservative, because the failure mode of getting this wrong is a
database full of references to files that do not exist:

  * It is a dry run unless you pass --apply.
  * It never deletes anything from the local media folder.
  * It skips any field whose value already looks like a Cloudinary reference,
    so re-running it is safe.
  * A file that fails to upload leaves its database row untouched and is
    reported at the end, rather than being half-migrated.

Verify with --dry-run first, then --apply, then check the site. Only delete
`media/` once you are satisfied, and keep a copy.
"""

from django.apps import apps as django_apps
from django.core.files.storage import FileSystemStorage
from django.core.management.base import BaseCommand, CommandError
from django.db import models

# Every model field that holds an upload, found by inspection rather than a
# hard-coded list, so a field added later is picked up automatically.
def iter_file_fields():
    for model in django_apps.get_models():
        fields = [
            field for field in model._meta.get_fields()
            if isinstance(field, models.FileField)
        ]
        if fields:
            yield model, fields


class Command(BaseCommand):
    help = 'Upload existing local media files to Cloudinary and repoint the database at them.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually upload and save. Without this the command only reports.',
        )
        parser.add_argument(
            '--model',
            help='Limit to one model, as app_label.ModelName (e.g. post.Post).',
        )

    def handle(self, *args, **options):
        from django.conf import settings

        if not settings.USE_CLOUDINARY:
            raise CommandError(
                'Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME, '
                'CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET first.'
            )

        apply_changes = options['apply']
        only = (options.get('model') or '').lower()

        local = FileSystemStorage(location=settings.MEDIA_ROOT)
        migrated = skipped = missing = 0
        failures = []

        self.stdout.write(self.style.MIGRATE_HEADING(
            'Migrating local media to Cloudinary' if apply_changes
            else 'DRY RUN — nothing will be uploaded or saved'
        ))

        for model, fields in iter_file_fields():
            label = f'{model._meta.app_label}.{model._meta.object_name}'
            if only and label.lower() != only:
                continue

            names = [field.name for field in fields]
            queryset = model._default_manager.all()

            for instance in queryset.iterator():
                for name in names:
                    field_file = getattr(instance, name, None)
                    raw = getattr(field_file, 'name', '') or ''
                    if not raw:
                        continue

                    # Already on Cloudinary: its stored name is a public id or
                    # a full URL, not a path that exists on this disk.
                    if raw.startswith(('http://', 'https://', 'image/upload/')):
                        skipped += 1
                        continue

                    if not local.exists(raw):
                        missing += 1
                        self.stdout.write(self.style.WARNING(
                            f'  missing on disk: {label}#{instance.pk}.{name} -> {raw}'
                        ))
                        continue

                    self.stdout.write(f'  {label}#{instance.pk}.{name}  {raw}')
                    if not apply_changes:
                        migrated += 1
                        continue

                    try:
                        with local.open(raw, 'rb') as handle:
                            # Saving through the field re-uploads via the
                            # configured (Cloudinary) storage and rewrites the
                            # stored name in one step.
                            field_file.save(raw, handle, save=False)
                        instance.save(update_fields=[name])
                        migrated += 1
                    except Exception as exc:
                        # The row keeps pointing at the local file, so nothing
                        # is left dangling.
                        failures.append(f'{label}#{instance.pk}.{name}: {exc}')
                        self.stdout.write(self.style.ERROR(f'    failed: {exc}'))

        self.stdout.write('')
        verb = 'Uploaded' if apply_changes else 'Would upload'
        self.stdout.write(self.style.SUCCESS(f'{verb}: {migrated}'))
        self.stdout.write(f'Already on Cloudinary: {skipped}')
        if missing:
            self.stdout.write(self.style.WARNING(f'Referenced but not on disk: {missing}'))
        if failures:
            self.stdout.write(self.style.ERROR(f'Failed: {len(failures)}'))
            for line in failures:
                self.stdout.write(self.style.ERROR(f'  {line}'))

        if not apply_changes:
            self.stdout.write('\nRe-run with --apply to perform the migration.')
        else:
            self.stdout.write(
                '\nLocal files were NOT deleted. Check the site, then remove '
                'media/ yourself once you are satisfied — and keep a backup.'
            )
