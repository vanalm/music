# Security

## What the repository must never contain

`.env` is gitignored and must stay that way. Nothing else in the tree holds a
credential. Before the first push to any remote, confirm:

```bash
git ls-files | grep -E '(^|/)\.env$'    # must print nothing
git log -p | grep -iE 'sk-|api[_-]?key.*=.*[A-Za-z0-9]{16}'
```

If a key ever does land in a commit, rotate it at the vendor first and rewrite
history second. Rotation is the fix; history rewriting is cleanup. A key that
reached a remote is compromised regardless of what you do to the branch.

## Keys are never printed

`doctor` reports presence and an 8-character SHA-256 prefix:

```
  music-ai  MUSIC_AI_API_KEY   configured   305fd8a4
```

The fingerprint is one-way and truncated — enough to confirm two machines hold
the same key, useless for replay. There is a test asserting that `doctor`'s
full output never contains the secret it was given.

No command echoes a credential, and errors from `http` truncate response bodies
to 2 KB so a verbose upstream error cannot dump something sensitive into a
terminal scrollback.

## The storage boundary

The single most important property in this codebase: **an API key is never sent
to a signed-storage host.**

Both vendors hand you a signed URL pointing at Google Cloud Storage, S3, or a
CDN, and expect you to PUT or GET the bytes there. Those URLs authorise
themselves through a signature in the query string. They need no header from
you, and the host on the other end is not your vendor.

The common failure is a shared HTTP session with a default `Authorization`
header — every request inherits it, including the ones going to a third party.

`http.py` makes that shape impossible to write by accident:

- `api_request` refuses any URL outside the calling adapter's `ALLOWED_HOSTS`,
  and the check runs *before* the request object is constructed, so nothing
  leaves the process.
- `storage_request` refuses to carry `Authorization`, `X-Api-Key`, or `Cookie`
  headers at all.
- Host matching is dot-anchored, so a lookalike domain (`evil-music.ai`
  against an allow-list of `music.ai`) does not pass.

Each adapter carries its own allow-list, so a Kits credential cannot reach a
Music.AI endpoint even through a coding mistake.

## What leaves your machine

Running a job uploads your audio to the vendor. That is the point of the tool,
but be deliberate about it:

- `audio normalize` strips metadata (`-map_metadata -1`) and drops embedded
  cover art, so tags and artwork do not ride along with a demo.
- `music-ai process --delete-remote` deletes the remote job and its stored
  outputs once results are downloaded. Use it for anything you would rather
  not leave sitting in a vendor's bucket.
- Kits result links are short-lived, so outputs are downloaded immediately
  when a job resolves rather than deferred to a later command.

Nothing is uploaded by any read-only command. `doctor`, `workflows`, `models`,
`project`, and `audio` never transmit audio.

## Suno, and why it stays off

Suno's REST API exists but its endpoint and auth detail sit behind an
authenticated account. The adapter therefore ships inert.

It will not, and should not, gain any of these:

- an unofficial third-party wrapper standing in for the real API
- cookie or bearer-token extraction from a logged-in browser session
- a captcha workaround
- an endpoint path guessed from URL patterns

Each is a terms-of-service violation and an account-ban risk, and each breaks
silently the moment the vendor changes anything. Reading the real schema once,
from your own signed-in account, is safer and less work than maintaining a
scraper. If some tool offers to do any of the above for you, decline.

## Rotating a key

1. Revoke and reissue at the vendor dashboard.
2. Update `.env`.
3. `music-stack doctor` — the fingerprint should change.

No other file needs touching; nothing caches credentials on disk.
