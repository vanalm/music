"""A recording transport double, used by the adapter tests.

It deliberately re-uses the *real* host allow-list check from
``music_stack.http`` and the real ``poll`` loop, so the adapter tests exercise
the actual security boundary and the actual backoff logic rather than a
simplified stand-in. Only the socket is faked.
"""

import json

from music_stack import http
from music_stack.errors import CredentialLeakError


class Sequence:
    """Marks a route that returns different payloads on successive calls.

    Needed because a bare ``list`` is itself a legitimate JSON payload (Kits
    returns one from ``/voice-models``), so a list cannot double as "these are
    my successive responses".
    """

    def __init__(self, *payloads):
        self.payloads = list(payloads)

    def next(self):
        return self.payloads.pop(0) if len(self.payloads) > 1 else self.payloads[0]


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status
        self.headers = {}
        self.url = "fake://"
        self.body = json.dumps(payload).encode() if payload is not None else b""

    def json(self):
        return self._payload


class FakeTransport:
    """Routes ``(METHOD, url-suffix)`` to canned payloads and records calls.

    ``calls`` holds one tuple per request:
      ``("api", method, url, headers)`` for credentialed API calls
      ``("upload", url, path)`` / ``("download", url, dest)`` for storage
    """

    HttpError = http.HttpError

    def __init__(self, routes=None):
        # routes: {(method, suffix): payload | list-of-payloads | Exception}
        self.routes = dict(routes or {})
        self.calls = []
        self.downloads = {}

    # -- credentialed path -------------------------------------------------

    def api_request(self, method, url, *, allowed_hosts, headers=None, **kwargs):
        # Exercise the genuine boundary: an adapter pointing a credentialed
        # call at the wrong host must fail here, in tests too.
        if not http._host_allowed(http.host_of(url), allowed_hosts):
            raise CredentialLeakError(
                "refusing to send credentials to {}".format(http.host_of(url))
            )
        self.calls.append(("api", method, url, dict(headers or {})))
        return FakeResponse(self._resolve(method, url))

    def _resolve(self, method, url):
        for (route_method, suffix), payload in self.routes.items():
            if route_method != method or not url.endswith(suffix):
                continue
            if isinstance(payload, Sequence):
                # Lets a test model a job that is QUEUED, then STARTED, then
                # SUCCEEDED across successive polls.
                return payload.next()
            if isinstance(payload, Exception):
                raise payload
            return payload
        raise AssertionError("no fake route for {} {}".format(method, url))

    # -- uncredentialed storage path ---------------------------------------

    def upload_file(self, url, path, **kwargs):
        self.calls.append(("upload", url, str(path)))
        return FakeResponse(None)

    def download_file(self, url, dest, **kwargs):
        self.calls.append(("download", url, str(dest)))
        self.downloads[str(dest)] = url
        return 1234

    # -- pass-throughs to the real implementations -------------------------

    def encode_multipart(self, fields, files):
        return http.encode_multipart(fields, files)

    def poll(self, fetch, is_terminal, **kwargs):
        kwargs.setdefault("sleep", lambda _seconds: None)
        kwargs.setdefault("interval", 0)
        return http.poll(fetch, is_terminal, **kwargs)

    # -- assertions helpers ------------------------------------------------

    def storage_calls(self):
        return [c for c in self.calls if c[0] in ("upload", "download")]

    def api_calls(self):
        return [c for c in self.calls if c[0] == "api"]
