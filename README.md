# Mindful Blog Backend

## About the Project
Mindful Blog Backend is the server-side component of the Mindful Blog platform: a
publishing system with posts, drafts, categories, tags, likes, threaded comments,
author profiles and dashboard statistics. It is built with Django and Django REST
Framework and is consumed by the [Mindful Blog](https://github.com/charitraa/Mindful_Blog)
React frontend.

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
│   │   └── management/commands/seed_categories.py
│   ├── comment/            # Comments, replies and moderation reports
│   ├── notification/       # Signal-driven notification inbox
│   └── newsletter/         # Double opt-in mailing list
├── media/                  # User uploads
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

### 4️⃣ Run database migrations
```bash
python manage.py migrate
```
> **Upgrading an existing database?** Migrations are now tracked in git (they used to be
> gitignored). If your database already has the old schema, run
> `python manage.py migrate --fake-initial` once, then migrate normally.

### 5️⃣ Seed the baseline categories
```bash
python manage.py seed_categories
```
Categories are reference data the post editor needs. The command is idempotent.

### 6️⃣ Create an admin user and run the app
```bash
python manage.py createsuperuser
python manage.py runserver
```
The API is then at http://localhost:8000 and the admin at http://localhost:8000/admin/.

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
- **Session Security**: Set `SESSION_COOKIE_SECURE=True` and `CSRF_COOKIE_SECURE=True` in production.

## 📜 License
Distributed under the MIT License. See `LICENSE` for details.

## 📬 Contact
- 👤 [@_charitraa_](https://www.instagram.com/_charitraa_/)
- 📧 stharabi9862187405@gmail.com
- 🌐 [Portfolio/Website](https://www.charitrashrestha.com.np)

⭐ If you like this project, don’t forget to star the repo!
