# One post a day, unattended

`daily_post.py` picks the next unused topic from `topics.txt`, has a model
write the post, and publishes it to the live blog through the public API. The
schedule lives in `.github/workflows/daily-post.yml`, so GitHub runs it — the
blog itself is on Render's free tier, which has no cron and no shell.

Nothing about the script is specific to Actions. The same command works from
your own machine or from a cron entry.

---

## 1. Give the posting account a password

The API signs the job in with an email and a password. **An account created by
"Sign in with GitHub" has no password at all** — `user_from_social()` calls
`set_unusable_password()`, so every login attempt comes back 401 no matter what
you type. GitHub's OAuth flow itself can't be automated: it hands back a
one-time `code` that only a browser can obtain.

So the account needs a password once. Pick one of these:

**Use the GitHub account (posts are authored by your public identity).**
Open <https://marginalia.charitrashrestha.com.np/forgot-password>, enter the
email your GitHub account uses, and follow the emailed link. This works fine on
an account with an unusable password — `set_password()` simply replaces it.
Signing in with GitHub keeps working afterwards; the password is just a second
way in.

**Or use the seeded admin instead.** `ADMIN_EMAIL` / `ADMIN_PASSWORD` in
Render's environment already describe an account with a real password, created
by `seed_admin` on every deploy. Nothing to set up — but posts are authored by
that account.

Either way the account must be able to publish. Roles from `author` upward can
(`User.can_publish`), and `author` is the default for a new account, so a
GitHub sign-in already qualifies. A `contributor` or below can only save
drafts, and the API says so explicitly rather than silently downgrading the
post.

## 2. Add the secrets

In the GitHub repo: **Settings → Secrets and variables → Actions**.

Secrets (hidden after saving):

| Name | Value |
| --- | --- |
| `BLOG_API_BASE` | `https://blog-server-akdq.onrender.com` |
| `BLOG_EMAIL` | the posting account's email |
| `BLOG_PASSWORD` | the password from step 1 |
| `NVIDIA_API_KEY` | the `nvapi-…` key, same one Render uses |

Variables (visible, on the *Variables* tab):

| Name | Value |
| --- | --- |
| `BLOG_SITE_URL` | `https://marginalia.charitrashrestha.com.np` |
| `NVIDIA_MODEL` | `openai/gpt-oss-20b` |

`BLOG_SITE_URL` only builds the link in the run summary. `NVIDIA_MODEL` is
optional — see *Choosing a model* below for why you should still set it.

## 3. Try it without publishing

Actions → **Daily post** → *Run workflow* → tick **dry_run**. The post is
written and printed to the run summary, and nothing is created. That first run
also proves the credentials, which is the part most likely to be wrong.

Then run it once for real, and leave the schedule to it.

---

## How it decides what to write

`topics.txt` is a plain list, top to bottom. The job takes the first line that
does not already appear in `posted.json`, which is committed back to the repo
after each successful run — that file is the queue's memory, so a run that
publishes but fails to push would repeat itself the next day.

When the list runs out the job asks the model for a fresh topic rather than
stopping, giving it your recent titles so it doesn't circle back. Set
`STRICT_TOPICS=1` if you would rather it fail loudly and wait for you to add
more.

Titles are checked against everything the account has already published,
drafts included, so the same post cannot land twice under a different topic.

## Choosing a model

**Set `NVIDIA_MODEL` explicitly and check it occasionally.** NVIDIA retires
models on a schedule and the endpoint then answers `410 Gone` — this is not
theoretical: `openai/gpt-oss-120b`, which both this script and
`settings.NVIDIA_MODEL` used to default to, reached end of life on
2026-09-03. The script names the retired model in the failure so the fix is
obvious. `GET /v1/models` lists what is currently available.

Two known-good choices, both measured against a full-length article:

| Model | Time | Notes |
| --- | --- | --- |
| `openai/gpt-oss-20b` | ~90 s | The blog's own `NVIDIA_FAST_MODEL`. |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | ~25 s | Faster, picks categories less reliably. |

Every model on the endpoint reasons before answering, and that reasoning is
billed against `max_tokens`. Left alone, a request for a thousand words spends
the whole budget thinking and returns **empty** content — gpt-oss-20b burned
6000 tokens and produced nothing. `thinking_knobs()` turns that down, and the
knob differs by family: `reasoning_effort` for gpt-oss, `chat_template_kwargs`
for everything else. A model that rejects its knob is retried without it, and
an empty answer is retried with double the room, the same way
`apps/ai/client.py` handles it.

These models also write short — 450 to 600 words against a brief asking for
800 to 1200, and turning reasoning *up* does not change that. A draft under
`MIN_WORDS` (700) is asked for once more and the longer of the two is
published.

## Running it yourself

```bash
source venv/bin/activate
pip install -r automation/requirements.txt

export BLOG_API_BASE=https://blog-server-akdq.onrender.com
export BLOG_EMAIL=you@example.com BLOG_PASSWORD=...
export NVIDIA_API_KEY=nvapi-...

python automation/daily_post.py --dry-run          # write it, publish nothing
python automation/daily_post.py --topic "..."      # jump the queue
python automation/daily_post.py --status draft     # publish nowhere public
```

Other knobs, all environment variables: `NVIDIA_MODEL`, `MIN_WORDS`,
`STRICT_TOPICS`, `REASONING_EFFORT`, `HTTP_TIMEOUT`, `AI_TIMEOUT`,
`TOPICS_FILE`, `STATE_FILE`.

## When it fails

Every failure ends the run red with a sentence naming the cause. The ones you
are most likely to meet:

- **`The blog rejected those credentials`** — step 1 was skipped, or the
  account signs in with GitHub and still has no password.
- **`login returned an email code instead of a token`** — the account is
  unverified. Sign in once in a browser. Accounts created through GitHub are
  verified on creation, so this means the account was registered by email.
- **`410 … end of life`** — pick a new `NVIDIA_MODEL`, above.
- **`Rate limited by the blog`** — `THROTTLE_WRITE` is 120/hour; a once-a-day
  job only meets this if something else is posting too.
- **A schedule that runs late** — GitHub's cron is best effort and queues under
  load. `30 2 * * *` is a little after 08:15 in Kathmandu, not a deadline.

The first request of the day also pays for a Render cold start, which is why
the HTTP timeout is 120 seconds rather than something tighter.
