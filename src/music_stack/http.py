"""Minimal HTTP layer built entirely on the standard library.

The package has no third-party runtime dependencies on purpose (see
``docs/architecture.md``): the bootstrap on a new machine then cannot be
broken by a yanked release or a pinned alpha that disappeared.

Two deliberately separate call paths live here:

``api_request``
    Talks to a first-party API host and attaches the service credential.
    The destination host is checked against an allow-list *before* the
    credential is attached.

``storage_request``
    Talks to signed-storage hosts (Google Cloud Storage, S3, a CDN) and
    attaches **no** credential, ever.

Keeping them apart is a security boundary, not a stylistic one. A signed URL
already carries its own short-lived authorisation in the query string, so
forwarding a service API key to that host would hand a long-lived secret to
an origin with no business seeing it. :func:`api_request` raises
:class:`CredentialLeakError` rather than send a key somewhere unexpected.
"""

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .errors import CredentialLeakError, HttpError

DEFAULT_TIMEOUT = 60
USER_AGENT = "music-stack/0.1 (+https://github.com/vanalm/music)"

# Streaming chunk size for uploads/downloads. Large enough to be efficient,
# small enough that a long file never has to sit in memory whole.
CHUNK = 1024 * 256


class Response:
    """A completed HTTP response with the body already read."""

    def __init__(self, status, headers, body, url):
        self.status = status
        self.headers = headers
        self.body = body
        self.url = url

    def json(self):
        """Decode the body as JSON, raising :class:`HttpError` if it is not."""
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise HttpError(
                "Expected a JSON response but could not decode one: {}".format(exc),
                status=self.status,
                url=self.url,
                body=self.body[:2000],
            ) from exc

    def __repr__(self):  # pragma: no cover - debugging aid
        return "<Response {} {}>".format(self.status, self.url)


def host_of(url):
    """Return the lowercased hostname of *url*, or ``""`` if it has none."""
    return (urllib.parse.urlparse(url).hostname or "").lower()


def _host_allowed(host, allowed):
    """True if *host* equals an allowed host or is a subdomain of one.

    Subdomain matching is anchored on a dot so that ``evil-music.ai`` does
    not match an allow-list entry of ``music.ai``.
    """
    host = host.lower()
    for candidate in allowed:
        candidate = candidate.lower()
        if host == candidate or host.endswith("." + candidate):
            return True
    return False


def _send(request, timeout, stream_to=None):
    """Execute *request*, translating urllib's exceptions into HttpError."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            if stream_to is not None:
                total = 0
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    stream_to.write(chunk)
                    total += len(chunk)
                return Response(resp.status, headers, b"", request.full_url), total
            return Response(resp.status, headers, resp.read(), request.full_url)
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read()
        except Exception:  # pragma: no cover - body already consumed
            pass
        raise HttpError(
            "HTTP {} from {}".format(exc.code, request.full_url),
            status=exc.code,
            url=request.full_url,
            body=body[:2000],
        ) from exc
    except urllib.error.URLError as exc:
        raise HttpError(
            "Could not reach {}: {}".format(request.full_url, exc.reason),
            url=request.full_url,
        ) from exc


def api_request(
    method,
    url,
    *,
    allowed_hosts,
    headers=None,
    json_body=None,
    data=None,
    timeout=DEFAULT_TIMEOUT,
):
    """Call a first-party API endpoint with credentials attached.

    *allowed_hosts* is the allow-list the caller's credential is scoped to.
    If *url* points anywhere else the call is refused before a single byte —
    credential included — leaves the process.
    """
    host = host_of(url)
    if not _host_allowed(host, allowed_hosts):
        raise CredentialLeakError(
            "Refusing to send credentials to {!r}; this call is only allowed to "
            "reach {}. A signed-storage or redirected URL must go through "
            "storage_request(), which attaches no credentials.".format(
                host or url, ", ".join(sorted(allowed_hosts))
            )
        )

    send_headers = {"User-Agent": USER_AGENT}
    send_headers.update(headers or {})

    body = data
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        send_headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(
        url, data=body, headers=send_headers, method=method
    )
    return _send(request, timeout)


def storage_request(method, url, *, data=None, headers=None, timeout=DEFAULT_TIMEOUT):
    """Call a signed-storage URL. Never attaches credentials.

    Deliberately takes no allow-list: signed URLs point at whatever bucket or
    CDN the service chose, and they authorise themselves through the query
    string. The security property here is the *absence* of a credential.
    """
    send_headers = {"User-Agent": USER_AGENT}
    send_headers.update(headers or {})
    for name in list(send_headers):
        if name.lower() in ("authorization", "x-api-key", "cookie"):
            raise CredentialLeakError(
                "Refusing to attach {!r} to a signed-storage request; signed URLs "
                "carry their own authorisation.".format(name)
            )
    request = urllib.request.Request(
        url, data=data, headers=send_headers, method=method
    )
    return _send(request, timeout)


def upload_file(url, path, *, content_type=None, timeout=None):
    """PUT a local file to a signed upload URL, streaming from disk.

    Returns the response. No credential is attached — see module docstring.
    """
    size = os.path.getsize(path)
    guessed = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as handle:
        request = urllib.request.Request(
            url,
            data=handle,
            method="PUT",
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": guessed,
                "Content-Length": str(size),
            },
        )
        return _send(request, timeout or _timeout_for(size))


def download_file(url, dest, *, timeout=None):
    """GET a signed download URL straight to *dest*. Returns bytes written.

    Writes to a temporary sibling first and renames on success, so an
    interrupted download never leaves a half-written file that later looks
    like a valid result.
    """
    dest = str(dest)
    parent = os.path.dirname(dest) or "."
    os.makedirs(parent, exist_ok=True)
    partial = "{}.part-{}".format(dest, uuid.uuid4().hex[:8])
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with open(partial, "wb") as handle:
            _, written = _send(request, timeout or DEFAULT_TIMEOUT * 5, stream_to=handle)
        os.replace(partial, dest)
        return written
    except BaseException:
        if os.path.exists(partial):
            os.unlink(partial)
        raise


def _timeout_for(size_bytes):
    """Scale the timeout with file size so long uploads are not cut off."""
    minutes = max(2, size_bytes // (1024 * 1024) // 2)
    return min(60 * 30, int(minutes * 60))


def encode_multipart(fields, files):
    """Build a ``multipart/form-data`` body.

    *fields* maps names to scalar values; *files* maps names to local paths.
    Returns ``(body_bytes, content_type_header)``. Kits requires multipart
    for every job-creating POST.
    """
    boundary = "----music-stack-{}".format(uuid.uuid4().hex)
    out = bytearray()
    for name, value in fields.items():
        if value is None:
            continue
        out += "--{}\r\n".format(boundary).encode()
        out += 'Content-Disposition: form-data; name="{}"\r\n\r\n'.format(name).encode()
        out += "{}\r\n".format(value).encode("utf-8")
    for name, path in files.items():
        filename = os.path.basename(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        out += "--{}\r\n".format(boundary).encode()
        out += (
            'Content-Disposition: form-data; name="{}"; filename="{}"\r\n'.format(
                name, filename
            ).encode()
        )
        out += "Content-Type: {}\r\n\r\n".format(ctype).encode()
        with open(path, "rb") as handle:
            out += handle.read()
        out += b"\r\n"
    out += "--{}--\r\n".format(boundary).encode()
    return bytes(out), "multipart/form-data; boundary={}".format(boundary)


def poll(fetch, is_terminal, *, timeout=900, interval=5, max_interval=30, sleep=time.sleep):
    """Call *fetch* until *is_terminal* accepts its result or time runs out.

    Backs off gently so a long render does not hammer the API. *sleep* is
    injectable so tests run instantly. Returns the final fetched value, or
    ``None`` if the deadline passed — callers raise their own JobTimeout with
    a service-specific message.
    """
    deadline = time.monotonic() + timeout
    wait = interval
    while True:
        value = fetch()
        if is_terminal(value):
            return value
        if time.monotonic() >= deadline:
            return None
        sleep(min(wait, max(0.0, deadline - time.monotonic())))
        wait = min(max_interval, wait * 1.5)
