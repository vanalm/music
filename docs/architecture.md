# Architecture

## Shape

```
cli.py            argparse surface; one command group per stage
├── config.py     .env + environment, credential presence, never values
├── audio.py      ffmpeg / ffprobe subprocess wrappers
├── projects.py   per-song directory scaffolding + job audit trail
├── http.py       the only place a socket is opened
└── adapters/
    ├── music_ai.py   api.music.ai
    ├── kits.py       arpeggi.io
    └── suno.py       fail-closed placeholder
```

Adapters never open sockets themselves; they call `http`. `http` never knows
what a job is. That split is what makes the security boundary testable in
isolation.

## Why zero third-party dependencies

The package installs nothing from PyPI. `urllib.request` does the HTTP,
`encode_multipart` builds the multipart bodies by hand, and `poll` is twenty
lines of backoff.

The reason is concrete. The most likely way this project breaks six months
from now is not an API change — it is a dependency that was renamed, yanked,
or pinned to a prerelease that no longer resolves. A pinned
`1.0.25-alpha.0` is a time bomb: alphas get deleted. Everything here runs on
a Python that Apple ships and Homebrew maintains.

The trade is real and small: about 150 lines of transport code that would
otherwise be `requests`. In exchange, `pip install -e .` cannot fail for a
reason outside this repository.

Vendor SDKs stay available under the `vendor` extra for anyone who wants
them. The CLI does not import them, so an SDK breaking cannot break the CLI.

## The credential boundary

This is the part worth understanding before changing anything.

Both services use the same three-step upload:

1. **Ask the API** for a signed URL pair — authenticated, goes to the vendor.
2. **PUT the bytes** to that signed URL — goes to Google Cloud Storage, S3, or
   a CDN. That host is not the vendor.
3. **Reference the download URL** in a job — authenticated again.

Step 2 is where a naive implementation leaks. If you build one HTTP session,
set a default `Authorization` header on it, and reuse it for every request,
then step 2 sends your long-lived API key to a third-party storage host that
has no business seeing it — and signed URLs are frequently logged.

So `http` exposes two functions that cannot be confused for each other:

| | `api_request` | `storage_request` / `upload_file` / `download_file` |
|---|---|---|
| Destination | allow-listed vendor host only | wherever the signed URL points |
| Credentials | attached | **refused** — raises `CredentialLeakError` |
| Guard | host checked *before* the request is built | auth-ish headers rejected |

The allow-list is anchored on a dot, so `evil-music.ai` does not match an
entry of `music.ai`. Each adapter declares its own `ALLOWED_HOSTS`, which
means a Kits key cannot be sent to a Music.AI endpoint even by accident —
there is a test for exactly that.

## Endpoint verification flags

`adapters/kits.py` declares each path with a boolean:

```python
ENDPOINTS = {
    "voice_models":     ("/voice-models",      True),
    "voice_conversion": ("/voice-conversions", True),
    "vocal_separation": ("/voice-separations", False),
    "stem_split":       ("/stem-splits",       False),
}
```

`True` means the path was read off Kits' published reference. `False` means it
follows the documented naming pattern but could not be confirmed at build time
(`docs.kits.ai` was unreachable from the build environment).

This is not decoration. A 404 on a `False` path produces an error that names
the file and the line to fix; a 404 on a `True` path is passed through
unchanged, because there it means "no such job", not "wrong URL". `doctor`
lists any remaining unverified paths on every run.

When you confirm one against the signed-in docs, flip the flag in the same
commit.

## Testing strategy

`tests/fakes.py` provides a recording transport that fakes **only the socket**.
It reuses the real `_host_allowed` check and the real `poll` loop, so the
adapter tests exercise the genuine security boundary and the genuine backoff
rather than a simplified stand-in. If someone weakens the allow-list, the
adapter tests fail too — not just the unit test aimed at it.

The transport records every call as `("api", method, url, headers)` or
`("upload"/"download", url, path)`. The storage tuples have no headers slot at
all, which is how `test_api_key_never_reaches_storage_hosts` can assert the
absence of a credential structurally instead of by string-matching.

ffmpeg tests are guarded by `skipUnless` rather than mocked. Mocking a
subprocess proves nothing about ffmpeg's actual behaviour; skipping is honest
about what did and did not run.

## Adding a service

1. New module in `adapters/`, with its own `ALLOWED_HOSTS`.
2. Route every request through `http.api_request` or the storage helpers —
   never `urllib` directly.
3. Add credential names to `Settings.SERVICES` so `doctor` reports them.
4. Add a round-trip test with `FakeTransport`, including an assertion that the
   credential never appears in a storage call.
5. If any endpoint path is unconfirmed, declare it `verified=False`.
