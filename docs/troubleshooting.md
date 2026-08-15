# Troubleshooting

Start with `music-stack doctor`. It reports local tooling, which credentials
are present, and any endpoint paths still flagged unverified.

## Install and tooling

**`ffmpeg was not found on PATH`**
`brew install ffmpeg`, or run `./scripts/bootstrap-macos.sh`. Then re-run
`doctor` — both `ffmpeg` and `ffprobe` must resolve.

**`command not found: music-stack`**
The virtualenv is not active. `source .venv/bin/activate`. Every shell needs
this; it does not persist across terminal windows.

**`pip install -e .` fails**
This package has no dependencies, so the failure is local — usually Python
older than 3.9 (`python3 --version`) or a `.venv` built by a Python that has
since been upgraded by Homebrew. Delete `.venv` and recreate it.

**Homebrew missing**
The bootstrap script stops rather than piping a remote installer into your
shell. Install Homebrew yourself from brew.sh, then re-run.

## Credentials

**`MUSIC_AI_API_KEY is not set`**
The key is missing from both the environment and `.env`. Note that `doctor`
prints the path it read `.env` from — if that is not the directory you edited,
you are running from a different working directory.

**A key is set but requests 401**
Check the fingerprint in `doctor` against a freshly copied key; a truncated
paste is the usual cause. Then check the auth *scheme*, which differs by
vendor and is a common source of confusion:

| Service | Header |
|---|---|
| Music.AI | `Authorization: <key>` — the raw key |
| Kits | `Authorization: Bearer <key>` |

Sending `Bearer` to Music.AI, or omitting it for Kits, produces a 401 that
looks like a bad key.

**`CredentialLeakError`**
Not a configuration problem — a bug. An adapter tried to send a credential to
a host outside its allow-list. The message names the host. See
[security.md](security.md); do not "fix" it by widening the allow-list.

## Jobs

**`did not finish within 900s`**
The job may still be running. Fetch it directly:

```bash
music-stack music-ai job <job-id>
```

Raise the ceiling with `MUSIC_STACK_POLL_TIMEOUT=3600` in `.env` for long
files. The timeout is a client-side patience limit, not a cancellation — a
timed-out job keeps processing on the vendor's side.

**`Kits returned 404 ... marked unverified in ENDPOINTS`**
Expected for vocal separation and stem splitting until confirmed. Open the
authenticated reference at `docs.kits.ai`, copy the real path, and correct the
one entry in `src/music_stack/adapters/kits.py`:

```python
"vocal_separation": ("/the-real-path", True),   # flip the flag too
```

Nothing else needs changing — the flag exists precisely so this is a one-line
fix rather than an investigation.

**Kits requests seem to hang for a minute**
That is the deliberate rate-limit spacer; Kits' alpha allows about one
job-creating POST per account per minute. Set `KITS_MIN_POST_INTERVAL=0` if
your plan has no such limit.

**`Kits job finished but exposed no downloadable output URLs`**
The job succeeded but the response shape was not what the adapter expected —
likely a field naming change. The error lists the fields that *were* present;
adjust the filter in `download_outputs`.

**`job failed: unsupported sample rate` (or similar)**
Normalize first:

```bash
music-stack audio normalize input.m4a normalized.wav
```

**A downloaded file is zero bytes or truncated**
Downloads write to a `.part` file and rename only on success, so this should
be impossible — a partial file is deleted on failure. If you see one, the job
itself returned an empty result; check `music-stack music-ai job <id>`.

## Suno

**`suno: unconfigured`**
Working as intended. Suno stays disabled until both `SUNO_API_KEY` and
`SUNO_API_BASE` are set from the authenticated documentation. The adapter
contains no guessed endpoints and should not be given any — see
[security.md](security.md).

## Tests

**Five tests skipped**
The ffmpeg round trips, on a machine without ffmpeg. Install it and they run.

**Tests pass but a real call fails**
Expected in principle: the suite is fully mocked, so it verifies *this* code's
logic, not the vendor's live behaviour. No live API call has ever been made
from this repository. If a real response shape differs from the mock, the mock
is wrong — fix the adapter and update the fixture together.
