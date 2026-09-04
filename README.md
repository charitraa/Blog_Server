# Mindful Blog Backend

## About the Project
Mindful Blog Backend is the server-side component of the Mindful Blog platform: a
publishing system with posts, drafts, categories, tags, likes, threaded comments,
author profiles and dashboard statistics. It is built with Django and Django REST
Framework and is consumed by the [Mindful Blog](https://github.com/charitraa/Mindful_Blog)
React frontend.

| | |
| --- | --- |
| Live site | <https://marginalia.charitrashrestha.com.np> |
| Frontend repo | <https://github.com/charitraa/marginalia> |

The frontend is deployed separately on Vercel and reaches this API through
`VITE_API_BASE_URL`. Run the two together locally by leaving that variable
empty: `vite.config.ts` then proxies `/api` and `/media` to
`VITE_DEV_API_TARGET`, which defaults to `http://127.0.0.1:8000`.

## 🛠️ Tech Stack
- **Framework**: Django 5.2 + Django REST Framework
- **Database**: SQLite by default; MySQL/PostgreSQL via `DB_ENGINE` and friends
- **Authentication**: JWT (`djangorestframework-simplejwt`) sent as a Bearer token,
  with the refresh token mirrored into an httpOnly cookie
- **Docs**: OpenAPI 3 via `drf-spectacular` (Swagger UI + ReDoc)
- **Media**: Pillow, with uploads validated by decoding rather than by MIME type
- **Sanitisation**: `bleach`, applied to post bodies on write

## ⚡ Features
- ✍️ Full post CRUD with a draft → published lifecycle and stable, readable slugs
- 🔒 JWT authentication with email **or** username login, refresh rotation and
  server-side logout (token blacklisting + cookie clearing)
- 📧 Optional email verification with one-time codes
- 🗂️ Categories and tags, with filtering, full-text search and safe sorting
- ❤️ Likes, made idempotent by a database unique constraint
- 💬 Threaded comments (one level deep) with author-only edit/delete
- 👤 Author profiles, follows, and per-author post listings
- 📊 Dashboard statistics computed from real data
- 👁️ Privacy-preserving view counting (salted, hashed fingerprints — no raw IPs)
- 🛡️ Object-level permissions, scoped rate limiting, strict CORS and HTML sanitisation
- 🔖 Bookmarks — a per-reader saved-for-later reading list
- 🔔 Notifications for likes, comments, replies and new followers, raised by
  signals so every path that creates one produces a notification
- 🔑 Social sign-in with GitHub and Google (matched on a **verified** email only)
- 🔓 Forgotten-password reset by emailed single-use link (only the hash is stored)
- 🖼️ Image uploads from inside the post editor, owned and rate limited per author
- 👁️‍🗨️ Shareable draft preview links, revocable by rotating the token
- 🚩 Comment reporting with an admin moderation queue (`is_hidden`)
- 📬 Newsletter with double opt-in and one-click unsubscribe
- 🌐 RSS + Atom feeds, `sitemap.xml` and `robots.txt`, all pointing at the frontend
- 🖼️ Cloudinary for uploaded media, so files survive a deploy on ephemeral hosts
- 📮 Brevo for email delivery, with real newsletter open and click rates
- 🤖 reCAPTCHA on registration, password reset and newsletter sign-up
- 🔓 Members-only posts, free — "member" means "has an account", not "has paid"
- 🤖 Optional AI assistant (NVIDIA NIM): titles, SEO, summaries, outlines,
  rewriting, proofreading, translation and reader Q&A
- 📖 Generated OpenAPI schema that matches the implementation

## 📂 Folder Structure
```bash
Blog_Server/
├── blog_server/            # Project configuration
│   ├── settings.py         # Environment-driven settings
│   ├── urls.py             # Root URLConf (/api/ + legacy routes)
│   ├── permission.py       # Reusable object-level permissions
│   ├── pagination.py       # Shared pagination classes
│   ├── validators.py       # Image upload validation
│   ├── exceptions.py       # Consistent API error format
│   ├── sitemaps.py         # Sitemaps describing the frontend's URLs
│   └── api_logging.py      # Request logging with credential redaction
├── apps/
│   ├── user/               # Accounts, auth, profiles, follows
│   │   ├── authentication.py   # Bearer-or-cookie JWT
│   │   ├── social.py           # GitHub / Google OAuth providers
│   │   ├── backends.py         # Email-or-username sign-in
│   │   ├── auth_urls.py        # /api/auth/
│   │   ├── urls.py             # /api/users/
│   │   └── legacy_urls.py      # /user/ compatibility aliases
│   ├── post/               # Posts, categories, tags, likes, views
│   │   ├── utils.py            # Sanitisation, slugs, reading time
│   │   ├── filters.py          # Explicit, allowlisted query filters
│   │   ├── feeds.py            # RSS and Atom syndication
│   │   └── management/commands/
│   │       ├── seed_all.py         # Everything below, in order (used by build.sh)
│   │       ├── seed_categories.py  # Baseline categories
│   │       ├── seed_tags.py        # Baseline tags
│   │       ├── seed_demo.py        # Sample users, posts and comments (dev only)
│   │       └── publish_scheduled.py
│   ├── comment/            # Comments, replies and moderation reports
│   ├── notification/       # Signal-driven notification inbox
│   └── newsletter/         # Double opt-in mailing list
├── media/                  # User uploads
├── build.sh                # Render build command: install, collectstatic, seed
├── .env.example            # Copy to .env
├── manage.py
└── requirements.txt
```

## 🚀 Getting Started

### 1️⃣ Clone the repo
```bash
git clone https://github.com/charitraa/Blog_Server.git
cd Blog_Server
```

### 2️⃣ Create a virtual environment and install dependencies
```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3️⃣ Configure the environment
```bash
cp .env.example .env
```
Then set `SECRET_KEY` in `.env`. Generate one with:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```
`.env.example` documents every supported variable. Nothing secret is hard-coded, and
`CORS_ALLOWED_ORIGINS` must list your frontend origins — never a wildcard in production.

Leaving `EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD` blank prints verification emails to the
console instead of failing, which is usually what you want locally. Set
`REQUIRE_EMAIL_VERIFICATION=False` to skip the code step entirely during development.

### 4️⃣ Migrate and seed, in one command
```bash
python manage.py seed_all
```
That runs `migrate`, then creates the baseline categories, the baseline tags and the
super admin. Every step is idempotent, so re-running it is always safe. See
[Seeding](#-seeding) for the individual commands and for the sample-content seed.

With `DEBUG=True` and no `ADMIN_EMAIL` configured, the admin seed uses a development
default and prints it:

| | |
| --- | --- |
| **Email** | `admin@example.com` |
| **Username** | `admin` (either one works — sign-in accepts email *or* username) |
| **Password** | `MindfulAdmin!2024` |

Set `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env` to choose your own instead. With
`DEBUG=False` there is no default at all — see [Deploying to Render](#-deploying-to-render).

> **Upgrading an existing database?** Migrations are now tracked in git (they used to be
> gitignored). If your database already has the old schema, run
> `python manage.py migrate --fake-initial` once, then `seed_all --no-migrate`.

### 5️⃣ Add sample content (optional)
```bash
python manage.py seed_demo
```
Five demo accounts, eight posts across every status, a series, comment threads with a
report waiting in the moderation queue, reactions, follows and subscribers — so the
frontend and the dashboard have something to render. The command prints the shared demo
password, refuses to run with `DEBUG=False`, and `seed_demo --undo` removes all of it.

### 6️⃣ Run the app
```bash
python manage.py runserver
```
The API is then at http://localhost:8000 and the admin at http://localhost:8000/admin/.

## 🌱 Seeding

Two different things get called "seeding" here, and the distinction matters:

- **Reference data** — categories, tags, the owner account. A real site needs these to
  work at all, so they belong in the deploy.
- **Sample content** — fake users, posts and comments, for looking at the frontend
  before anybody has written anything. This must never reach a live site.

| Command | What it does | Safe in production |
| --- | --- | --- |
| `seed_all` | `migrate`, then all three reference seeds below | ✅ every deploy |
| `seed_categories` | The eight baseline categories the editor files posts under | ✅ |
| `seed_tags` | ~27 starting tags, so tag pages are not empty | ✅ |
| `seed_admin` | The super admin, from the environment, with no prompt | ✅ |
| `seed_demo` | Demo accounts, posts, threads, reactions, subscribers | ❌ refuses unless forced |

### Logins the seeds create (development)

| Account | Email | Password | Role |
| --- | --- | --- | --- |
| Admin (`seed_admin`) | `admin@example.com` | `MindfulAdmin!2024` | super_admin |
| Editor (`seed_demo`) | `editor@example.com` | `MindfulDemo!2024` | editor |
| Author (`seed_demo`) | `author@example.com` | `MindfulDemo!2024` | author |
| Designer (`seed_demo`) | `designer@example.com` | `MindfulDemo!2024` | author |
| Contributor (`seed_demo`) | `contributor@example.com` | `MindfulDemo!2024` | contributor |
| Reader (`seed_demo`) | `reader@example.com` | `MindfulDemo!2024` | member |

Sign-in accepts the email **or** the username (`admin`, `demo-editor`, `demo-author`,
`demo-designer`, `demo-contributor`, `demo-reader`). All of these are development
conveniences: the admin default only applies with `DEBUG=True`, and `seed_demo` refuses
to run with `DEBUG=False`.

Everything is idempotent — matched on email, name or slug — so re-running adds what is
missing and changes nothing else.

### The admin account

`createsuperuser` asks questions, which makes it unusable in the one place an admin is
hardest to create by hand: a deploy's build step. `seed_admin` takes the same values from
the environment instead:

```bash
ADMIN_EMAIL=you@example.com
ADMIN_USERNAME=admin          # optional; derived from the email if omitted
ADMIN_PASSWORD=a-long-one     # must pass Django's password validators
```

```bash
python manage.py seed_admin
```

With nothing configured the behaviour splits on `DEBUG`, which is the difference between
a laptop and a deploy:

- **`DEBUG=True`** — falls back to `admin@example.com` / `MindfulAdmin!2024` (username
  `admin`) and prints the credentials, so a fresh clone has a working admin login in one
  command. Handing out a known password is the right trade for `runserver` against a
  throwaway SQLite file; the alternative is every contributor inventing one and losing it.
- **`DEBUG=False`** — prints "skipped" and exits **0**, so a build script can always call
  it, and a published password can never become a live site's admin login.

Other behaviour worth knowing:

- An account that already exists is **not** given a new password. It is repaired instead:
  `is_staff`, `is_superuser`, `is_verified`, un-suspended, and `role=super_admin`. That is
  the case that actually bites — an account created before the role ladder existed, or
  before email verification was switched on, locked out of its own site.
- Rotating the password is deliberate: `python manage.py seed_admin --force-password`.
- A weak password is rejected outright. This account can publish, moderate and hand out
  roles on a site reachable from the internet.

### Sample content

```bash
python manage.py seed_demo          # create
python manage.py seed_demo --undo   # remove the demo accounts and everything they own
```

It creates five accounts — editor, two authors, contributor and member — plus posts in
every status (published, members-only, scheduled, in review, private draft), a three-part
series, comment threads with replies and mentions, an open moderation report, reactions,
bookmarks, reading history, follows and newsletter subscribers. Comments, likes and
follows go through the ORM, so the notification signals fire and the demo inbox fills up
on its own.

Addresses are all `@example.com` — a domain reserved by RFC 2606 — so a stray
notification can never reach a real person. The shared password is printed when the
command finishes. `seed_demo` refuses to run with `DEBUG=False` unless you pass `--force`.

## 🧪 Running Tests
```bash
python manage.py test
```
The suite covers registration, login, verification, permissions, drafts, post CRUD and
ownership, likes and duplicate prevention, comments and their authorization, categories,
search, filtering, sorting, pagination, view-count deduplication, HTML sanitisation and
the legacy routes.

## 📖 API Documentation
- **Swagger UI**: http://localhost:8000/api/docs/
- **ReDoc**: http://localhost:8000/api/redoc/
- **Raw schema**: http://localhost:8000/api/schema/

The schema is generated from the code, so it always matches the implementation.

### Authentication
Send `Authorization: Bearer <access token>`. `POST /api/auth/refresh/` rotates the token
and also accepts the refresh token from its httpOnly cookie, so a browser client can keep
the access token in memory and store nothing.

### Example Routes
| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/register/` | Create an account |
| `POST` | `/api/auth/login/` | Sign in with email **or** username |
| `POST` | `/api/auth/refresh/` | Rotate tokens |
| `POST` | `/api/auth/logout/` | Blacklist the refresh token and clear cookies |
| `GET`/`PATCH` | `/api/users/me/` | Read or update your profile |
| `POST` | `/api/users/me/avatar/` | Upload a profile picture (multipart, field `photo`) |
| `GET` | `/api/users/me/dashboard/` | Dashboard statistics |
| `GET` | `/api/users/{username}/` | Public author profile |
| `GET` | `/api/posts/` | List posts (`search`, `category`, `tag`, `author`, `ordering`, `page`) |
| `POST` | `/api/posts/` | Create a post or draft |
| `GET`/`PATCH`/`DELETE` | `/api/posts/{slug}/` | Read, update or delete (also accepts a UUID) |
| `POST`/`DELETE` | `/api/posts/{slug}/like/` | Like or unlike |
| `GET` | `/api/posts/trending/` | Engagement-ranked posts |
| `GET`/`POST` | `/api/posts/{slug}/comments/` | Read or add comments |
| `PATCH`/`DELETE` | `/api/comments/{id}/` | Edit or delete your own comment |
| `GET` | `/api/categories/`, `/api/tags/` | Taxonomy |
| `POST`/`DELETE` | `/api/posts/{slug}/bookmark/` | Save or unsave a post |
| `GET` | `/api/bookmarks/` | Your reading list |
| `POST` | `/api/uploads/images/` | Upload an inline editor image (multipart, field `image`) |
| `GET` | `/api/posts/{slug}/preview/?token=` | Read a draft with its share token, no account needed |
| `POST` | `/api/posts/{slug}/preview-token/` | Rotate the token, revoking every shared link |
| `POST` | `/api/comments/{id}/report/` | Flag a comment for a moderator |
| `GET` | `/api/notifications/` | Your inbox (`?unread=true` to filter) |
| `GET` | `/api/notifications/unread-count/` | The number on the bell |
| `POST` | `/api/notifications/read/` | Mark some (`ids`) or all as read |
| `POST` | `/api/auth/password-reset/` | Email a reset link |
| `POST` | `/api/auth/password-reset/confirm/` | Set a new password and sign in |
| `GET` | `/api/auth/providers/` | Social providers this deployment has credentials for |
| `POST` | `/api/auth/social/{provider}/` | Exchange an OAuth code for a session |
| `POST` | `/api/newsletter/subscribe/` | Start double opt-in |
| `POST` | `/api/newsletter/confirm/`, `/unsubscribe/` | Complete or cancel a subscription |
| `GET` | `/feed/`, `/feed/atom/` | Syndication (also `/feed/category/{slug}/`, `/feed/author/{username}/`) |
| `GET` | `/sitemap.xml`, `/robots.txt` | SEO surfaces, describing the frontend |

The original `/user/`, `/post/` and `/comment/` routes are still mounted as aliases onto
these same views, so existing clients keep working.

## 🖼️ Media storage (Cloudinary)

Render's filesystem is **ephemeral**: anything written to `media/` is lost on the
next deploy or restart. Uploads therefore go to Cloudinary in production.

Cloudinary is **opt-in**. With no credentials the app writes to `media/` exactly
as it always did, so a fresh checkout needs no account to run.

```bash
# .env — all three required; two of three stays on local storage
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
```

Find them at <https://console.cloudinary.com> under *Dashboard → Product
Environment*. `CLOUDINARY_API_SECRET` is **server-side only** — it is never sent
to the frontend, and no endpoint echoes it back.

Static files stay on the app server: `collectstatic` already handles them
reliably and there is nothing to gain from moving them.

Uploads are organised by the `upload_to` already on each model:

| Folder | Contents |
| --- | --- |
| `user_photos/` | Profile pictures |
| `user_post/` | Post cover images |
| `post_content/` | Images placed inside an article |
| `series/` | Series cover images |

### Migrating media you already have

```bash
python manage.py migrate_media_to_cloudinary            # dry run — reports only
python manage.py migrate_media_to_cloudinary --apply    # upload and repoint
python manage.py migrate_media_to_cloudinary --apply --model post.Post
```

It never deletes local files, skips anything already on Cloudinary (so it is safe
to re-run), and leaves a row untouched if its upload fails. Check the site before
removing `media/` yourself — and keep a backup.

## 📮 Email & newsletter (Brevo)

[Brevo](https://brevo.com) (formerly Sendinblue) handles delivery when
`BREVO_API_KEY` is set, and takes precedence over the SMTP settings.

It slots in as a Django email backend, so **every existing `send_mail` call**
— verification codes, password resets, newsletter confirmations — routes
through it with no call site changing.

```bash
BREVO_API_KEY=xkeysib-...
BREVO_SENDER_EMAIL=hello@yourdomain.com
BREVO_SENDER_NAME=Marginalia
BREVO_LIST_ID=2          # the contact list confirmed subscribers join
```

Backend selection is Brevo → SMTP → console, so a checkout with no credentials
still runs and prints its emails to the terminal.

### Why Brevo for open and click rates

They are not something this server can measure. Tracking an open means
embedding a pixel; tracking a click means rewriting every link — both can only
be done by whatever actually sends the mail. A plain SMTP server hands the
message to a mail server and learns nothing more.

| Endpoint | Does |
| --- | --- |
| `GET`/`POST` `/api/newsletter/campaigns/` | List or draft a campaign (staff) |
| `PATCH`/`DELETE` `/api/newsletter/campaigns/{id}/` | Edit or remove a **draft** |
| `POST` `/api/newsletter/campaigns/{id}/send/` | Send to every confirmed subscriber |
| `GET` `/api/newsletter/campaigns/{id}/stats/` | Refresh opens, clicks, bounces |

Confirming a subscription adds the address to your Brevo list; unsubscribing
removes it. A sent campaign can never be edited or deleted — the emails are
already in inboxes, and letting the record drift would make the figures
meaningless. Rates are calculated against *delivered*, not sent, because a
bounce was never an opportunity to open.

## 💳 Payments

There are none, deliberately. Members-only posts are free: **"member" means
"has an account"**, so a locked post is a reason to sign up rather than a
paywall. No gateway, no card handling, nothing to reconcile.

## 🛡️ reCAPTCHA (optional)

Guards the three unauthenticated endpoints that either create an account or
email an address the requester chose:

| Endpoint | Why |
| --- | --- |
| `POST /api/auth/register/` | Bulk fake accounts |
| `POST /api/auth/password-reset/` | Bombing somebody else's inbox |
| `POST /api/newsletter/subscribe/` | Same, plus list poisoning |

**Sign-in is deliberately not guarded.** A 20/hour throttle already covers
password guessing, and a puzzle in front of every returning reader costs more
in abandoned logins than it saves in blocked attempts.

```bash
RECAPTCHA_ENABLED=True
RECAPTCHA_SITE_KEY=6Le...        # public; served to the frontend by /api/config/
RECAPTCHA_SECRET_KEY=6Le...      # server-side only, never sent to the frontend
RECAPTCHA_MIN_SCORE=0.5          # v3 only; v2 sends no score
```

Register a site at <https://www.google.com/recaptcha/admin>. Leave the secret
blank and the guard switches off entirely, so development needs no keys and no
widget is rendered.

The same code handles **v2 and v3**: a score is checked when present and
ignored when absent, so changing key type is configuration, not code.

Two deliberate behaviours:

- **It fails open when Google is unreachable.** A CAPTCHA outage must not
  become a site outage — the throttles still apply, and locking every visitor
  out of registering is the worse failure.
- **The rejection reason goes to the log, never the response.** Telling a bot
  precisely why it failed is free tuning advice.

The frontend reads the site key from `GET /api/config/` rather than a
build-time variable, so the two halves cannot drift apart about whether the
guard is on.

## 🤖 AI assistant (optional)

Author-facing tools backed by [NVIDIA NIM](https://build.nvidia.com). Leave
`NVIDIA_API_KEY` blank and the endpoints report themselves unavailable, so the
editor hides the assistant rather than offering buttons that fail.

```bash
AI_ENABLED=True
AI_PREFERRED_PROVIDER=nvidia
NVIDIA_API_KEY=nvapi-...
NVIDIA_MODEL=openai/gpt-oss-120b
NVIDIA_FAST_MODEL=openai/gpt-oss-20b
THROTTLE_AI=40/hour
```

| Endpoint | Does |
| --- | --- |
| `GET /api/ai/status/` | Whether the assistant is available (no credentials exposed) |
| `POST /api/ai/titles/` | Title options for a draft |
| `POST /api/ai/seo/` | Search title, description and tags |
| `POST /api/ai/summary/` | A short summary |
| `POST /api/ai/outline/` | An outline from a topic |
| `POST /api/ai/rewrite/` | Rewrite a passage (clearer / shorter / friendlier / formal) |
| `POST /api/ai/proofread/` | Spelling and grammar only |
| `POST /api/ai/social/` | A short announcement post |
| `POST /api/ai/translate/` | Translate a passage |
| `POST /api/posts/{slug}/ask/` | Answer a reader's question from the article |

Every call is triggered explicitly by a signed-in author, and none of them
writes to the database — suggestions are returned for the author to accept or
ignore. They share a throttle scope of their own because each request costs
money at the provider.

**Measured limitations**, not assumed:

- The configured models reason before answering and that reasoning is billed
  against `max_tokens`, so the client budgets generously and retries once when a
  reply is truncated.
- The safety model catches harassment, threats and hate. It does **not** catch
  advertising spam — that still relies on reader reports.
- `riva-translate` returns Hindi when asked for Nepali. Verify any language
  before relying on it.

## 🚀 Deploying to Render

Render's build step is not interactive, which is why `createsuperuser` cannot be used
there and why the seeds have to run as part of the deploy rather than by hand.

`build.sh` in the repo root is the whole story. Point the service at it:

| Setting | Value |
| --- | --- |
| **Build Command** | `./build.sh` |
| **Start Command** | `gunicorn blog_server.wsgi:application` |

It installs the requirements, runs `collectstatic`, and then runs `seed_all` — migrations,
categories, tags and the admin account. Every step is idempotent, so it runs on every
deploy; nothing here needs remembering after the first one.

Set these as **environment variables on the service** (not in a committed file):

```bash
SECRET_KEY=...                # generate a fresh one, never reuse the dev key
DEBUG=False                   # also switches on Secure cookies, HSTS and the https redirect
ALLOWED_HOSTS=your-api.onrender.com
BACKEND_URL=https://your-api.onrender.com
FRONTEND_URL=https://your-site.example
CORS_ALLOWED_ORIGINS=https://your-site.example
CSRF_TRUSTED_ORIGINS=https://your-site.example

ADMIN_EMAIL=you@example.com   # the seeds create this account on the first deploy
ADMIN_PASSWORD=a-long-one

CLOUDINARY_CLOUD_NAME=...     # Render's disk is ephemeral — uploads must go here
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
CACHE_DIR=/tmp/blog-cache     # the throttle cache needs a writable path
```

Then open `https://your-api.onrender.com/admin/` and sign in as `ADMIN_EMAIL`.

**Notes**

- The build runs against your production database, so it must be reachable at build
  time. On a plan that offers a **Pre-Deploy Command**, move `python manage.py seed_all`
  there and drop it from `build.sh` — that is the more correct place for it.
- `seed_demo` is not called by `build.sh` and refuses to run with `DEBUG=False`. Sample
  content does not belong on a live site.
- Settings read `DB_ENGINE`/`DB_NAME`/`DB_USER`/… — not `DATABASE_URL`. If you attach a
  Render Postgres, map its fields to those variables and add a Postgres driver
  (`psycopg2-binary`) to `requirements.txt`; only MySQL (`PyMySQL`) ships today.

## 🚀 Deploying to PythonAnywhere (Free Tier)
1. **Create a PythonAnywhere Account**  
   Sign up for a free account at [pythonanywhere.com](https://www.pythonanywhere.com).

2. **Upload Your Project**  
   - Use the PythonAnywhere file manager or SSH to upload the `Mindful Blog-backend/` folder.  
   - Alternatively, clone the repo directly on PythonAnywhere:  
     ```bash
     git clone https://github.com/username/Mindful Blog-backend.git
     ```

3. **Set Up a Virtual Environment**  
   Create and activate a virtual environment:  
   ```bash
   mkvirtualenv --python=/usr/bin/python3.10 Mindful Blog-venv
   pip install -r requirements.txt
   ```

4. **Configure the WSGI File**  
   - Update the WSGI configuration file (under the "Web" tab in PythonAnywhere) to point to your Django project's `wsgi.py`.  
   - Example `wsgi.py` path: `/home/yourusername/Mindful Blog-backend/Mindful_Blog/wsgi.py`.

5. **Set Up Environment Variables**  
   In the PythonAnywhere "Web" tab, add environment variables from `.env.example`:  
   - `SECRET_KEY=your-django-secret-key-here`  
   - `DATABASE_URL=sqlite:////home/yourusername/Mindful_Blog/db.sqlite3` (or PostgreSQL URL)  
   - `CLOUDINARY_URL`, `SENDGRID_API_KEY`, etc., as needed.

6. **Run Migrations**  
   In the PythonAnywhere Bash console:  
   ```bash
   cd /home/yourusername/Mindful_Blog
   python manage.py makemigrations
   python manage.py migrate
   ```

7. **Serve Static Files**  
   - Run `python manage.py collectstatic` to collect static files.  
   - Configure the static files mapping in the PythonAnywhere "Web" tab (e.g., `/static/` → `/home/yourusername/Mindful Blog-backend/static/`).

8. **Reload the Web App**  
   Click the "Reload" button in the PythonAnywhere "Web" tab to apply changes.

### Notes for PythonAnywhere Free Tier
- Free tier has limited CPU and memory; use SQLite for simplicity or a lightweight PostgreSQL setup.  
- HTTPS is provided automatically for `*.pythonanywhere.com` domains.  
- Static file serving is supported, but ensure `collectstatic` is run after updates.  
- No WebSocket support on the free tier; avoid real-time features like live commenting.

## 👨‍💻 Contributing
We ❤️ contributions! Please follow these steps to ensure a smooth contribution process:

### How to Contribute
1. **Fork the Repository**  
   Click the "Fork" button on the Mindful Blog Backend GitHub repository.  
   Clone your forked repository to your local machine:  
   ```bash
   git clone https://github.com/your-username/Mindful_Blog.git
   cd Mindful_Blog
   ```

2. **Set Up the Development Environment**  
   Follow the setup instructions above to install dependencies and configure environment variables.  
   Ensure you have the required tools (Python 3.8+, PostgreSQL/SQLite, etc.) installed.

3. **Create a Feature Branch**  
   Create a new branch for your changes:  
   ```bash
   git checkout -b feature/your-feature-name
   ```  
   Use descriptive branch names (e.g., `fix/auth-bug`, `feature/comment-replies`, `docs/update-readme`).

4. **Make Changes**  
   Work on your feature, bug fix, or documentation improvement.  
   Follow the project's coding standards:  
   - **Backend**: Follow Django best practices, use class-based views, and modularize code in apps/models/views.  
   - **Tests**: Write unit/integration tests for new features or bug fixes using Pytest.  

   Ensure your changes align with the project's roadmap or open an issue to discuss new ideas.

5. **Test Your Changes**  
   Run tests to ensure your changes don't break existing functionality:  
   ```bash
   pytest
   ```  
   Test manually to verify API functionality.

6. **Commit Your Changes**  
   Write clear, concise commit messages using the Conventional Commits format:  
   ```
   feat: add comment reply functionality
   fix: resolve session authentication issue
   docs: update README with PythonAnywhere deployment
   ```  
   Example:  
   ```bash
   git commit -m "feat: add comment reply functionality"
   ```

7. **Push and Open a Pull Request**  
   Push your branch to your forked repository:  
   ```bash
   git push origin feature/your-feature-name
   ```  
   Open a Pull Request (PR) on the main Mindful Blog Backend repository.  
   In the PR description, include:  
   - A summary of your changes.  
   - Any related issue numbers (e.g., `Closes #123`).  
   - Screenshots or logs for API changes (if applicable).  

   Ensure your PR passes CI checks (GitHub Actions).

8. **Code Review**  
   Maintainers will review your PR and provide feedback.  
   Be responsive to comments and make requested changes.  
   Once approved, your PR will be merged!

### Development Guidelines
- **Code Style**: Run `python manage.py makemigrations` for model changes and ensure code follows PEP 8.  
- **Testing**: Write tests for new features using Pytest.  
- **API Changes**: Update the Swagger/Postman documentation in `docs/` for any new or modified endpoints.  
- **Commits**: Keep commits small and focused to make reviews easier.  
- **Dependencies**: Avoid adding unnecessary dependencies; discuss in an issue if needed.

### Reporting Bugs
- Check the Issues page to avoid duplicates.  
- Open a new issue with:  
  - A clear title (e.g., "Session expires prematurely on login").  
  - Steps to reproduce, expected behavior, and actual behavior.  
  - Screenshots or logs (if applicable).

### Suggesting Features
- Open an issue with the `[Feature Request]` prefix in the title.  
- Describe the feature, its use case, and any implementation ideas.  
- Tag it with the `enhancement` label.

## 📜 Code of Conduct

### Our Pledge
We, as contributors and maintainers of Mindful Blog Backend, pledge to make participation in our project and community a harassment-free experience for everyone, regardless of age, body size, disability, ethnicity, gender identity and expression, level of experience, nationality, personal appearance, race, religion, or sexual identity and orientation.

### Our Standards
Examples of behavior that contributes to a positive environment include:  
- Using welcoming and inclusive language.  
- Being respectful of differing viewpoints and experiences.  
- Gracefully accepting constructive criticism.  
- Focusing on what is best for the community.  
- Showing empathy towards other community members.  

Examples of unacceptable behavior include:  
- The use of sexualized language or imagery and unwelcome sexual attention or advances.  
- Trolling, insulting/derogatory comments, and personal or political attacks.  
- Public or private harassment.  
- Publishing others' private information, such as physical or electronic addresses, without explicit permission.  
- Other conduct which could reasonably be considered inappropriate in a professional setting.

### Our Responsibilities
Project maintainers are responsible for clarifying the standards of acceptable behavior and are expected to take appropriate and fair corrective action in response to any instances of unacceptable behavior.  
Maintainers have the right and responsibility to remove, edit, or reject comments, commits, code, issues, and other contributions that are not aligned with this Code of Conduct, or to ban temporarily or permanently any contributor for behaviors deemed inappropriate, threatening, offensive, or harmful.

### Scope
This Code of Conduct applies within all project spaces, including GitHub repositories, issue trackers, and any other communication channels related to Mindful Blog Backend. It also applies when an individual is representing the project or its community in public spaces.

### Enforcement
Instances of abusive, harassing, or otherwise unacceptable behavior may be reported by contacting the project team at your.email@example.com. All complaints will be reviewed and investigated promptly and fairly.  
All maintainers are obligated to respect the privacy and security of the reporter of any incident.

### Enforcement Guidelines
Maintainers will follow these Community Impact Guidelines in determining the consequences for any action deemed in violation of this Code of Conduct:  
- **Correction**: A private, written warning from a maintainer, providing clarity around the nature of the violation and an explanation of why the behavior was inappropriate.  
- **Warning**: A public or private warning with a request for a public apology for more severe or repeated violations.  
- **Temporary Ban**: A temporary ban from contributing to the project for a specified period.  
- **Permanent Ban**: A permanent ban from any sort of interaction with the project community.

### Attribution
This Code of Conduct is adapted from the Contributor Covenant, version 2.1, available at https://www.contributor-covenant.org/version/2/1/code_of_conduct.html.  
For answers to common questions about this Code of Conduct, see the FAQ at https://www.contributor-covenant.org/faq.

## 🛡️ Security Policy

### Supported Versions
The Mindful Blog Backend project actively maintains security updates for the following versions:

| Version  | Supported          |
|----------|--------------------|
| main     | ✅                 |
| v1.x.x   | ✅                 |

### Reporting a Vulnerability
If you discover a security vulnerability in Mindful Blog Backend, we encourage responsible disclosure. Please follow these steps:  
- Do not report security issues publicly via GitHub issues or other public forums.  
- Send a detailed report to your.email@example.com. Include:  
  - A description of the vulnerability.  
  - Steps to reproduce the issue.  
  - Potential impact (e.g., data exposure, unauthorized access).  
  - Any suggested fixes (optional).  

Allow the project maintainers up to 14 days to respond and assess the issue.  
We will acknowledge receipt of your report within 48 hours and work with you to validate and address the vulnerability.

### Disclosure Process
Once a vulnerability is reported, maintainers will:  
- Validate the issue and assess its severity.  
- Develop and test a fix.  
- Release the fix in a new version or patch.  
- Credit the reporter (unless anonymity is requested) in release notes.  

We aim to resolve critical vulnerabilities within 30 days and less severe issues within 60 days.

### Security Best Practices
To ensure the security of your Mindful Blog Backend deployment:  
- Never commit sensitive information (e.g., `.env` files, `SECRET_KEY`) to version control.  
- Use a strong, unique `SECRET_KEY` for Django (at least 50 characters, generated securely).  
- Regularly update dependencies to address known vulnerabilities:  
  ```bash
  pip install -r requirements.txt --upgrade
  ```  
- Enable HTTPS for production deployments (automatic on PythonAnywhere).  
- Monitor logs and enable security headers (e.g., CSP, X-Frame-Options) in your Django settings or PythonAnywhere web server configuration.

### Known Security Considerations
- **Authentication**: Ensure `SECRET_KEY` is secure and unique for session-based authentication. Use Django’s `check_password` for secure password handling.  
- **Database**: Restrict access to the database server and use environment-specific configurations.  
- **Image Uploads**: Validate and sanitize all user-uploaded content (e.g., via Cloudinary).  
- **API Security**: Use Django REST Framework’s throttling and input validation to prevent abuse.  
- **Session Security**: Handled by `DEBUG=False` alone — secure cookies, `SameSite=None`, the https redirect and HSTS all switch on with it, and there is no environment override that can turn them back off.

## 📜 License
Distributed under the MIT License. See `LICENSE` for details.

## 📬 Contact
- 👤 [@_charitraa_](https://www.instagram.com/_charitraa_/)
- 📧 stharabi9862187405@gmail.com
- 🌐 [Portfolio/Website](https://www.charitrashrestha.com.np)

⭐ If you like this project, don’t forget to star the repo!
