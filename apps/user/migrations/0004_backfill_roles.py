"""
Give existing accounts a role that matches the authority they already had.

Without this every account would land on the `author` default, silently
demoting the site's superusers on the first deploy of the role system.
"""

from django.db import migrations


def assign_roles(apps, schema_editor):
    User = apps.get_model('user', 'User')

    User.objects.filter(is_superuser=True).update(role='super_admin')
    User.objects.filter(is_superuser=False, is_staff=True).update(role='admin')
    # Everyone else keeps the `author` default: the site had no distinction
    # before this, so every existing account could already publish.


def clear_roles(apps, schema_editor):
    User = apps.get_model('user', 'User')
    User.objects.update(role='author')


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0003_user_is_suspended_user_role_user_suspended_until_and_more'),
    ]

    operations = [
        migrations.RunPython(assign_roles, clear_roles),
    ]
