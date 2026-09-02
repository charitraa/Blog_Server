"""
The individual AI tasks.

Each one is a pure function over text: it takes what the author wrote and
returns a suggestion. Nothing here writes to the database or edits a post —
the author always applies the result themselves, because a tool that silently
rewrites someone's work is not an assistant.
"""

import logging

from django.conf import settings

from .client import chat, chat_json
from .utils import plain_text_excerpt

logger = logging.getLogger('apps.ai')

# The house style every task inherits, so suggestions do not read like an
# assistant talking about the article instead of writing it.
VOICE = (
    'You help a blog author. Write in clear, plain language. '
    'Never invent facts that are not in the supplied text. '
    'Do not use marketing hype or filler.'
)


def suggest_titles(content, count=5):
    """Title options for a finished draft."""
    data = chat_json([
        {'role': 'system', 'content': VOICE},
        {'role': 'user', 'content':
            f'Return JSON {{"titles": [string]}} with {count} title options for this '
            f'article. Each under 70 characters, specific rather than clickbait.\n\n'
            f'{plain_text_excerpt(content, 6000)}'},
    ], max_tokens=1600)

    titles = data.get('titles') or []
    return [str(t).strip() for t in titles if str(t).strip()][:count]


def suggest_seo(content, title=''):
    """A search title, meta description and tags in one pass."""
    data = chat_json([
        {'role': 'system', 'content': VOICE},
        {'role': 'user', 'content':
            'Return JSON {"seo_title": string, "seo_description": string, '
            '"tags": [string]}. seo_title at most 60 characters. '
            'seo_description at most 155 characters, describing what the reader '
            'learns. 3 to 6 lowercase tags, each one or two words.\n\n'
            f'Current title: {title or "(none)"}\n\n{plain_text_excerpt(content, 6000)}'},
    ], max_tokens=1800)

    return {
        'seo_title': str(data.get('seo_title', ''))[:70].strip(),
        'seo_description': str(data.get('seo_description', ''))[:200].strip(),
        'tags': [str(t).strip().lower() for t in (data.get('tags') or []) if str(t).strip()][:8],
    }


def summarize(content, sentences=3):
    """A short summary, for the author or for a reader who wants the gist."""
    return chat([
        {'role': 'system', 'content': VOICE},
        {'role': 'user', 'content':
            f'Summarise this article in at most {sentences} sentences. '
            f'Plain prose, no bullet points, no preamble.\n\n'
            f'{plain_text_excerpt(content, 8000)}'},
    ], max_tokens=1500, temperature=0.3)


def outline(topic, audience=''):
    """A starting structure for something not written yet."""
    data = chat_json([
        {'role': 'system', 'content': VOICE},
        {'role': 'user', 'content':
            'Return JSON {"sections": [{"heading": string, "points": [string]}]} — '
            'an outline of 4 to 7 sections, each with 2 to 4 points.\n\n'
            f'Topic: {topic}\n'
            f'Audience: {audience or "general readers"}'},
    ], max_tokens=2500, temperature=0.5)

    sections = []
    for entry in (data.get('sections') or [])[:8]:
        heading = str(entry.get('heading', '')).strip()
        if not heading:
            continue
        sections.append({
            'heading': heading,
            'points': [str(p).strip() for p in (entry.get('points') or []) if str(p).strip()][:5],
        })
    return sections


TONES = {
    'clearer': 'Make it clearer and easier to follow.',
    'shorter': 'Make it shorter without losing meaning.',
    'friendlier': 'Make the tone warmer and more conversational.',
    'formal': 'Make the tone more formal and precise.',
}


def rewrite(text, tone='clearer'):
    """
    Rewrite a passage the author selected.

    The instruction is explicit that facts must not change — a rewrite that
    quietly invents a detail is worse than no rewrite at all.
    """
    instruction = TONES.get(tone, TONES['clearer'])
    return chat([
        {'role': 'system', 'content':
            f'{VOICE} Rewrite the passage you are given. {instruction} '
            'Keep every fact and claim exactly as it is. '
            'Return only the rewritten passage.'},
        {'role': 'user', 'content': plain_text_excerpt(text, 4000)},
    ], max_tokens=2500, temperature=0.4)


def proofread(text):
    """Spelling, grammar and punctuation only — never a rewrite in disguise."""
    return chat([
        {'role': 'system', 'content':
            'Correct spelling, grammar and punctuation only. '
            'Do not reword, restructure, or change the author\'s voice. '
            'Return only the corrected text.'},
        {'role': 'user', 'content': plain_text_excerpt(text, 4000)},
    ], model=settings.NVIDIA_FAST_MODEL, max_tokens=2500, temperature=0.1)


def social_post(content, title='', network='general'):
    """A short post announcing the article."""
    limits = {'twitter': 260, 'linkedin': 700, 'general': 400}
    limit = limits.get(network, 400)

    return chat([
        {'role': 'system', 'content': VOICE},
        {'role': 'user', 'content':
            f'Write a {limit}-character-or-less post announcing this article. '
            'No hashtag spam — at most two, only if they are genuinely useful. '
            'Return only the post text.\n\n'
            f'Title: {title}\n\n{plain_text_excerpt(content, 4000)}'},
    ], model=settings.NVIDIA_FAST_MODEL, max_tokens=1200, temperature=0.6)


def translate(text, target_language):
    """
    Translate with the provider's dedicated translation model.

    A general chat model will translate too, but a purpose-built one is faster
    and cheaper.

    Known limitation, measured rather than assumed: asking for Nepali returns
    Hindi. The model appears to collapse related Devanagari languages, so
    Nepali output from this endpoint is not trustworthy. Use it for the
    languages you have actually verified, and fall back to NVIDIA_MODEL for
    anything it handles badly.
    """
    return chat([
        {'role': 'user', 'content': f'Translate to {target_language}: {plain_text_excerpt(text, 4000)}'},
    ], model=settings.NVIDIA_TRANSLATE_MODEL, max_tokens=1500, temperature=0.1)


def answer_question(content, question):
    """
    Answer a reader's question from the article, and only from the article.

    Being told to say so when the answer is not present is what keeps this from
    confidently making things up about someone else's writing.
    """
    return chat([
        {'role': 'system', 'content':
            'Answer using only the article provided. '
            'If the article does not answer the question, say so plainly '
            'instead of guessing. Keep it to a short paragraph.'},
        {'role': 'user', 'content':
            f'Article:\n{plain_text_excerpt(content, 8000)}\n\nQuestion: {question}'},
    ], max_tokens=1600, temperature=0.2)


def screen_text(text):
    """
    Run text past the provider's safety model.

    Scope, measured rather than assumed: this catches harassment, threats,
    violence and hate. It does **not** catch advertising spam — plain
    "buy cheap watches, visit example.com" comes back `safe`. Spam still needs
    reader reports or a separate heuristic.

    It never hides anything by itself. An unsafe verdict files a report for a
    human moderator, which is the same path a reader's report takes.
    """
    try:
        verdict = chat(
            [{'role': 'user', 'content': plain_text_excerpt(text, 2000)}],
            model=settings.NVIDIA_SAFETY_MODEL,
            max_tokens=400,
            temperature=0,
        )
    except Exception:
        # Screening is an enhancement; if it fails the comment posts as normal.
        logger.exception('Comment screening failed')
        return {'safe': True, 'categories': [], 'checked': False}

    lowered = verdict.lower()
    safe = '"unsafe"' not in lowered and "'unsafe'" not in lowered
    return {'safe': safe, 'raw': verdict[:200], 'checked': True}
