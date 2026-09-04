#!/usr/bin/env python3
"""
Write and publish one post a day, unattended.

The job is deliberately a client of the public API rather than a management
command: the blog runs on Render's free tier, which has no cron and no shell,
so the scheduler lives in GitHub Actions and talks to the deployed site over
HTTPS exactly as a browser would.

    BLOG_API_BASE=https://api.example.com \
    BLOG_EMAIL=you@example.com BLOG_PASSWORD=... NVIDIA_API_KEY=nvapi-... \
    python automation/daily_post.py

Nothing here is specific to Actions; the same command works from cron or by
hand. `--dry-run` does everything except the final POST, which is the cheap way
to see what tomorrow's post would look like.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
TOPICS_FILE = Path(os.environ.get('TOPICS_FILE', HERE / 'topics.txt'))
STATE_FILE = Path(os.environ.get('STATE_FILE', HERE / 'posted.json'))

# The blog sanitises HTML server-side and drops anything not on its allowlist
# (apps/post/utils.py). Asking for the allowed subset up front means the post
# that lands is the post the model wrote, rather than a silently stripped one.
ALLOWED_HTML = 'p, h2, h3, ul, ol, li, strong, em, blockquote, pre, code, a, hr'

# Two very different waits. The blog answers in a second or so, except on the
# first request of the day: Render's free tier stops the container when it is
# idle and a cold start costs the best part of a minute. Writing a thousand
# words is slower still — several minutes is normal for a reasoning model
# asked for one long non-streamed answer, so it gets its own budget rather
# than sharing the API one.
TIMEOUT = int(os.environ.get('HTTP_TIMEOUT', 120))
AI_TIMEOUT = int(os.environ.get('AI_TIMEOUT', 900))


class Failed(RuntimeError):
    """Anything that should end the run with a red build and a clear reason."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def env(name, default=None, required=False):
    """
    An environment variable, treating empty as absent.

    That distinction matters here. A workflow step lists every variable it
    passes, so an unset repository variable still arrives — as an empty
    string. `os.environ.get(name, default)` would hand back that empty string
    and skip the default, which is how an unset NVIDIA_MODEL once reached the
    provider as `"model": ""` and came back "model field is required".
    """
    value = os.environ.get(name)
    if value is None or not value.strip():
        value = default
    if required and not value:
        raise Failed(
            f'{name} is not set. In GitHub Actions add it under '
            f'Settings > Secrets and variables > Actions.'
        )
    return value


# ---------------------------------------------------------------------------
# Blog API
# ---------------------------------------------------------------------------

class Blog:
    def __init__(self, base, session=None):
        self.base = base.rstrip('/')
        self.http = session or requests.Session()
        self.token = None

    def url(self, path):
        return f'{self.base}/{path.lstrip("/")}'

    def headers(self):
        return {'Authorization': f'Bearer {self.token}'} if self.token else {}

    def login(self, identifier, password):
        response = self.http.post(
            self.url('/api/auth/login/'),
            # The serializer reads an email *or* a username out of `email`.
            json={'email': identifier, 'password': password},
            timeout=TIMEOUT,
        )
        if response.status_code == 401:
            raise Failed(
                'The blog rejected those credentials. If this account signs in '
                'with GitHub it has no password yet — run the password reset '
                'flow once (see automation/README.md).'
            )
        if response.status_code >= 400:
            raise Failed(f'Login failed ({response.status_code}): {response.text[:300]}')

        body = response.json()
        if body.get('requires_verification'):
            # The server answers 200 with a code emailed to the account, which
            # no unattended job can complete.
            raise Failed(
                'The account is not verified, so login returned an email code '
                'instead of a token. Verify the account once in the browser.'
            )
        self.token = body.get('access')
        if not self.token:
            raise Failed(f'Login succeeded but returned no access token: {body}')
        return body.get('user', {})

    def my_titles(self):
        """Every title this account has already used, drafts included."""
        titles, page = set(), 1
        while page <= 20:  # a guard, not a real limit: 50/page is 1000 posts
            response = self.http.get(
                self.url('/api/posts/mine/'),
                params={'page': page, 'page_size': 50},
                headers=self.headers(),
                timeout=TIMEOUT,
            )
            if response.status_code >= 400:
                raise Failed(f'Could not list existing posts: {response.text[:200]}')
            body = response.json()
            for post in body.get('results', []):
                titles.add(post.get('title', '').strip().lower())
            if not body.get('next'):
                break
            page += 1
        return titles

    def categories(self):
        response = self.http.get(self.url('/api/categories/'), timeout=TIMEOUT)
        if response.status_code >= 400:
            return []
        body = response.json()
        rows = body if isinstance(body, list) else body.get('results', [])
        return [{'slug': row['slug'], 'name': row['name']} for row in rows if row.get('slug')]

    def create_post(self, payload):
        response = self.http.post(
            self.url('/api/posts/'),
            json=payload,
            headers=self.headers(),
            timeout=TIMEOUT,
        )
        if response.status_code == 429:
            raise Failed('Rate limited by the blog (THROTTLE_WRITE). Try again later.')
        if response.status_code >= 400:
            raise Failed(f'Publishing failed ({response.status_code}): {response.text[:500]}')
        return response.json()


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

def thinking_knobs(model):
    """
    How to ask this model to stop thinking and start writing.

    Every model on the endpoint reasons before answering, and that reasoning is
    billed against `max_tokens`. Left alone, a request for a thousand words
    spends the entire budget on the monologue and returns empty `content` —
    measured, not guessed: gpt-oss-20b burned 6000 tokens and answered nothing.
    The knob differs by family and neither model accepts the other's, so it is
    chosen here rather than sent speculatively.
    """
    if model.startswith('openai/gpt-oss'):
        return {'reasoning_effort': os.environ.get('REASONING_EFFORT', 'low')}
    return {'chat_template_kwargs': {'thinking': False}}


class Writer:
    """A thin client for the same NVIDIA endpoint the blog's own AI app uses."""

    def __init__(self, api_key, base_url, model):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.knobs = thinking_knobs(model)

    def chat(self, messages, max_tokens=4000, temperature=0.7, _retry=True):
        payload = {'model': self.model, 'messages': messages,
                   'max_tokens': max_tokens, 'temperature': temperature}
        response = requests.post(
            f'{self.base_url}/chat/completions',
            headers={'Authorization': f'Bearer {self.api_key}',
                     'Content-Type': 'application/json'},
            json=dict(payload, **self.knobs),
            timeout=AI_TIMEOUT,
        )
        if (response.status_code == 400 and self.knobs
                and any(knob in response.text for knob in self.knobs)):
            # A model that does not know the knob rejects the whole request.
            # Losing the knob costs speed, not correctness, so drop it and
            # carry on rather than failing the day's post over it.
            #
            # The error has to actually name the knob. Retrying on any 400 at
            # all made an unrelated rejection ("model field is required") look
            # like a knob problem, and reported the wrong cause in the log.
            print(f'  {self.model} rejected {list(self.knobs)}; retrying without',
                  file=sys.stderr)
            self.knobs = {}
            response = requests.post(
                f'{self.base_url}/chat/completions',
                headers={'Authorization': f'Bearer {self.api_key}',
                         'Content-Type': 'application/json'},
                json=payload,
                timeout=AI_TIMEOUT,
            )
        if response.status_code == 401:
            raise Failed('The AI provider rejected NVIDIA_API_KEY.')
        if response.status_code == 410:
            raise Failed(
                f'The provider has retired "{self.model}". Pick another from '
                f'{self.base_url}/models and set NVIDIA_MODEL to it.'
            )
        if response.status_code >= 400:
            raise Failed(f'AI provider returned {response.status_code}: {response.text[:300]}')
        try:
            choice = response.json()['choices'][0]
            message = choice['message']
        except (ValueError, KeyError, IndexError) as exc:
            raise Failed(f'Unexpected AI response: {response.text[:300]}') from exc

        # `reasoning_content` is the model thinking aloud; the answer is
        # `content`. An empty answer next to a full monologue means the budget
        # ran out mid-thought, which more room usually fixes.
        text = (message.get('content') or '').strip()
        if not text and _retry:
            thought = bool(message.get('reasoning_content') or message.get('reasoning'))
            if thought or choice.get('finish_reason') == 'length':
                print('  answer was empty (all budget went on reasoning); '
                      'retrying with double the room', file=sys.stderr)
                return self.chat(messages, max_tokens=max_tokens * 2,
                                 temperature=temperature, _retry=False)
        return text

    def json_chat(self, messages, max_tokens=4000, attempts=3):
        for attempt in range(1, attempts + 1):
            raw = self.chat(
                [{'role': 'system',
                  'content': 'Reply with one valid JSON object only. '
                             'No prose, no markdown, no code fences.'}] + messages,
                max_tokens=max_tokens,
                # Cooler on each retry: if it could not hold the format, it is
                # unlikely to do better with more freedom.
                temperature=max(0.2, 0.7 - 0.2 * (attempt - 1)),
            )
            parsed = extract_json(raw)
            if parsed is not None:
                return parsed
            print(f'  model did not return usable JSON (attempt {attempt}/{attempts})',
                  file=sys.stderr)
            time.sleep(2 * attempt)
        raise Failed('The model never returned parseable JSON.')


def extract_json(raw):
    if not raw:
        return None
    text = re.sub(r'^```(?:json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    # A model may still wrap the object in a sentence; take the outermost pair.
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Topic selection
# ---------------------------------------------------------------------------

def read_topics(path):
    if not path.exists():
        return []
    lines = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            lines.append(line)
    return lines


def read_state(path):
    if not path.exists():
        return {'posts': []}
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        return {'posts': []}
    state.setdefault('posts', [])
    return state


def choose_topic(topics, state, recent_titles, writer, strict):
    used = {entry.get('topic', '').strip().lower() for entry in state['posts']}
    for topic in topics:
        if topic.strip().lower() not in used:
            return topic, 'queue'

    if strict:
        raise Failed(
            f'Every topic in {TOPICS_FILE.name} has been used and STRICT_TOPICS '
            f'is set. Add more topics to resume.'
        )

    print('  topic queue is empty — asking the model for a fresh one')
    recent = '\n'.join(f'- {title}' for title in sorted(recent_titles)[-40:])
    invented = writer.json_chat([{
        'role': 'user',
        'content': (
            'Propose one fresh blog post topic for a working software '
            'engineer\'s personal blog. It must not repeat or paraphrase any '
            f'of these existing posts:\n{recent}\n\n'
            'Answer as {"topic": "..."} — a specific, concrete angle, not a '
            'broad survey.'
        ),
    }], max_tokens=800)
    topic = (invented.get('topic') or '').strip()
    if not topic:
        raise Failed('The model failed to invent a topic.')
    return topic, 'invented'


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

# A post shorter than this reads as a stub next to the rest of the blog. It is
# a target, not a gate: the run asks once for a fuller draft and publishes the
# better of the two rather than skipping the day over a word count.
MIN_WORDS = int(os.environ.get('MIN_WORDS', 700))


def write_post(writer, topic, categories, recent_titles):
    """Draft the post, asking once for more if the first attempt comes back thin."""
    article = draft(writer, topic, categories, recent_titles)
    if article['_words'] < MIN_WORDS:
        print(f'  first draft was {article["_words"]} words; asking for a fuller one')
        longer = draft(writer, topic, categories, recent_titles, short=article['_words'])
        if longer['_words'] > article['_words']:
            article = longer
    return article


def draft(writer, topic, categories, recent_titles, short=None):
    category_list = ', '.join(f'{c["name"]} ({c["slug"]})' for c in categories) or 'none'
    avoid = '\n'.join(f'- {title}' for title in sorted(recent_titles)[-30:]) or '(none yet)'
    more = ''
    if short is not None:
        more = (f' A previous attempt came back at only {short} words, which is '
                f'too thin — develop the examples and go deeper this time.')

    article = writer.json_chat([{
        'role': 'user',
        'content': f"""Write a complete blog post about: {topic}

Audience: working software engineers. Voice: plain, specific, first person
where it helps. No filler, no "in today's fast-paced world", no restating the
title in the first sentence. Prefer a concrete example over an abstraction.

Length: 800-1200 words of body text.{more}

Return exactly this JSON object:
{{
  "title": "under 70 characters, no trailing period",
  "subtitle": "one clarifying line, under 140 characters",
  "excerpt": "1-2 sentences, under 280 characters, no HTML",
  "content": "the post body as HTML",
  "tags": ["3 to 6 short lowercase tags"],
  "category": "one slug from the list below, or null",
  "seo_title": "under 70 characters",
  "seo_description": "under 160 characters"
}}

Rules for "content":
- HTML only, using nothing but these tags: {ALLOWED_HTML}
- No <h1>: the site renders the title as the page heading.
- No markdown syntax anywhere, no code fences around the HTML.
- Code samples go in <pre><code class="language-x">...</code></pre>.
- Open with a paragraph, not a heading.

Available categories: {category_list}

Do not repeat or paraphrase these existing posts:
{avoid}
"""
    }], max_tokens=8000)

    return normalise(article, categories)


def normalise(article, categories):
    """Turn a model's best effort into something the API will accept."""
    title = collapse(article.get('title'))
    content = (article.get('content') or '').strip()

    # Models sometimes fence the HTML despite being told not to.
    content = re.sub(r'^```(?:html)?\s*|\s*```$', '', content, flags=re.MULTILINE).strip()
    # The site's own layout supplies the h1; a second one hurts the outline.
    content = re.sub(r'<(/?)h1\b', r'<\1h2', content, flags=re.IGNORECASE)

    if len(title) < 3:
        raise Failed('The model returned no usable title.')
    body_text = re.sub(r'<[^>]+>', ' ', content)
    words = len(body_text.split())
    if words < 120:
        raise Failed(f'The generated body is too short ({words} words) to publish.')

    valid_slugs = {c['slug'] for c in categories}
    category = article.get('category')
    if category not in valid_slugs:
        category = None

    tags = []
    for tag in article.get('tags') or []:
        tag = collapse(str(tag))[:40]
        if tag and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag)

    return {
        'title': title[:200],
        'subtitle': collapse(article.get('subtitle'))[:300],
        'excerpt': collapse(article.get('excerpt'))[:300],
        'content': content,
        'tags': tags[:8],           # the serializer rejects a ninth
        'category': category,
        'seo_title': collapse(article.get('seo_title'))[:70],
        'seo_description': collapse(article.get('seo_description'))[:200],
        '_words': words,
    }


def collapse(value):
    return ' '.join(str(value or '').split())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def summarise(lines):
    """Write to the Actions run summary when there is one, always to stdout."""
    text = '\n'.join(lines)
    print(text)
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if path:
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write(text + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true',
                        help='Generate and print the post without publishing.')
    parser.add_argument('--topic', help='Write about this instead of the queue.')
    parser.add_argument('--status', default=os.environ.get('POST_STATUS', 'published'),
                        choices=['published', 'draft'],
                        help='What to create the post as (default: published).')
    args = parser.parse_args()

    api_base = env('BLOG_API_BASE', required=True)
    blog = Blog(api_base)

    print(f'-> signing in to {blog.base}')
    user = blog.login(env('BLOG_EMAIL', required=True), env('BLOG_PASSWORD', required=True))
    print(f'   authenticated as {user.get("username", "?")} ({user.get("role", "?")})')

    writer = Writer(
        env('NVIDIA_API_KEY', required=True),
        env('NVIDIA_BASE_URL', 'https://integrate.api.nvidia.com/v1'),
        # gpt-oss-120b reached end of life on the endpoint on 2026-09-03;
        # 20b is what the blog already uses as its fast model and answers a
        # full article in about 90 seconds with reasoning turned down.
        env('NVIDIA_MODEL', 'openai/gpt-oss-20b'),
    )

    titles = blog.my_titles()
    categories = blog.categories()
    state = read_state(STATE_FILE)
    print(f'   {len(titles)} existing post(s), {len(categories)} categories')

    if args.topic:
        topic, source = args.topic, 'argument'
    else:
        topic, source = choose_topic(
            read_topics(TOPICS_FILE), state, titles, writer,
            strict=env('STRICT_TOPICS', '') not in ('', '0', 'false', 'False'),
        )
    print(f'-> topic ({source}): {topic}')

    print('-> writing')
    article = write_post(writer, topic, categories, titles)
    words = article.pop('_words')
    print(f'   "{article["title"]}" — {words} words, tags: {", ".join(article["tags"]) or "none"}')

    if article['title'].strip().lower() in titles:
        raise Failed(f'A post titled "{article["title"]}" already exists; skipping.')

    if args.dry_run:
        summarise([f'### Dry run — nothing published',
                   f'**Topic:** {topic}',
                   f'**Title:** {article["title"]}',
                   f'**Words:** {words}', '', '<details><summary>Body</summary>', '',
                   article['content'][:4000], '', '</details>'])
        return 0

    payload = dict(article, status=args.status)
    print(f'-> publishing as {args.status}')
    created = blog.create_post(payload)

    slug = created.get('slug', '')
    site = env('BLOG_SITE_URL', '').rstrip('/')
    link = f'{site}/post/{slug}' if site else f'{blog.base}/api/posts/{slug}/'

    state['posts'].append({
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'topic': topic,
        'title': created.get('title', article['title']),
        'slug': slug,
        'id': created.get('id'),
        'words': words,
        'source': source,
    })
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + '\n',
                          encoding='utf-8')

    summarise([f'### Published: {created.get("title")}',
               f'- **Topic:** {topic}',
               f'- **Words:** {words}',
               f'- **Tags:** {", ".join(article["tags"]) or "none"}',
               f'- **Link:** {link}'])
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Failed as exc:
        print(f'\nFAILED: {exc}', file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as exc:
        print(f'\nFAILED: network error talking to the API: {exc}', file=sys.stderr)
        sys.exit(1)
