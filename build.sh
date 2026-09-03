#!/usr/bin/env bash
#
# Render build command.
#
# Set this as the service's **Build Command** (`./build.sh`) and
# `gunicorn blog_server.wsgi:application` as the **Start Command**.
#
# Everything here is idempotent, so it runs on every deploy rather than being a
# one-off you have to remember in the shell: Render gives you no interactive
# console on the free tier, which is exactly why `createsuperuser` cannot be
# used and `seed_admin` reads ADMIN_EMAIL / ADMIN_PASSWORD from the environment
# instead.

# Fail the build rather than starting a server against a half-migrated database.
set -o errexit
set -o pipefail
set -o nounset

pip install --upgrade pip
pip install -r requirements.txt

# Static files for the Django admin and the Swagger UI.
python manage.py collectstatic --no-input

# migrate + baseline categories + baseline tags + the owner account.
# Skipped silently if ADMIN_EMAIL is not set, so this never breaks a deploy
# whose admin is managed by hand.
python manage.py seed_all

# Sample content is deliberately not seeded here. If you want it in a staging
# environment, run it yourself once:
#   python manage.py seed_demo --force
