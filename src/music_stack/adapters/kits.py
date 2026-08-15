"""Kits AI adapter.

Documented contract:

* Base URL ``https://arpeggi.io/api/kits/v1`` (Kits is an Arpeggi Labs product;
  the API is served from the arpeggi.io host, not kits.ai)
* ``Authorization: Bearer <api-key>``
* Every job-creating POST is ``multipart/form-data`` — not JSON
* Voice conversion: ``POST /voice-conversions`` with fields ``voiceModelId``
  and ``soundFile``

Endpoint paths carry an explicit verification flag in :data:`ENDPOINTS`.
Voice models and voice conversion are confirmed against Kits' published
reference; the separation paths follow the same documented naming pattern but
were not readable at build time (docs.kits.ai sits behind an egress block in
the environment this was written in). They are marked ``verified=False`` and,
if the service 404s them, the error tells you exactly which line to correct
rather than failing vaguely. Nothing here is a scraped or reverse-engineered
endpoint.
"""

import time
from pathlib import Path

from .. import http
from ..errors import JobError, JobTimeout, MusicStackError

API_BASE = "https://arpeggi.io/api/kits/v1"

#: The only host this adapter's credential may ever reach.
ALLOWED_HOSTS = ("arpeggi.io",)

#: Endpoint path → whether the path is confirmed against published docs.
ENDPOINTS = {
    "voice_models": ("/voice-models", True),
    "voice_conversion": ("/voice-conversions", True),
    "vocal_separation": ("/voice-separations", False),
    "stem_split": ("/stem-splits", False),
}

#: Kits' documented input restrictions.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
ALLOWED_SUFFIXES = (".wav", ".mp3", ".flac", ".m4a", ".aiff", ".aif", ".ogg")

#: Kits' alpha API is documented as allowing roughly one job-creating POST per
#: account per minute. The client-side spacer below keeps us from tripping it;
#: set KITS_MIN_POST_INTERVAL=0 to disable if your plan lifts the limit.
DEFAULT_MIN_POST_INTERVAL = 60

TERMINAL_STATUSES = ("success", "succeeded", "complete", "completed", "error", "failed")
FAILED_STATUSES = ("error", "failed")


class KitsClient:
    """Client for the Kits AI (Arpeggi) REST API."""

    def __init__(self, api_key, *, base=API_BASE, transport=None,
                 min_post_interval=DEFAULT_MIN_POST_INTERVAL, clock=time.monotonic):
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self.base = base.rstrip("/")
        self._t = transport or http
        self._min_post_interval = min_post_interval
        self._clock = clock
        self._last_post_at = None

    # -- plumbing ---------------------------------------------------------

    def _headers(self):
        return {"Authorization": "Bearer {}".format(self._api_key)}

    def _path(self, key):
        try:
            return ENDPOINTS[key]
        except KeyError:  # pragma: no cover - programming error
            raise MusicStackError("Unknown Kits endpoint {!r}".format(key))

    def _call(self, method, key_or_path, *, verified=True, headers=None, **kwargs):
        path = key_or_path
        # The auth header is always ours; callers may add to it (multipart
        # Content-Type) but must not be able to displace it.
        merged = dict(headers or {})
        merged.update(self._headers())
        try:
            return self._t.api_request(
                method,
                "{}{}".format(self.base, path),
                allowed_hosts=ALLOWED_HOSTS,
                headers=merged,
                **kwargs
            )
        except http.HttpError as exc:
            if exc.status == 404 and not verified:
                raise JobError(
                    "Kits returned 404 for {}. This endpoint path is marked "
                    "unverified in ENDPOINTS (src/music_stack/adapters/kits.py) "
                    "— open the authenticated reference at docs.kits.ai, copy the "
                    "real path, and correct that one entry.".format(path)
                ) from exc
            raise

    def _respect_rate_limit(self, sleep=time.sleep):
        """Space out job-creating POSTs to stay inside the documented limit."""
        if not self._min_post_interval:
            return
        if self._last_post_at is not None:
            elapsed = self._clock() - self._last_post_at
            remaining = self._min_post_interval - elapsed
            if remaining > 0:
                sleep(remaining)
        self._last_post_at = self._clock()

    @staticmethod
    def validate_input(path):
        """Check *path* against Kits' documented size and format limits."""
        path = Path(path)
        if not path.exists():
            raise MusicStackError("No such audio file: {}".format(path))
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise MusicStackError(
                "Kits does not accept {} files. Convert first:\n"
                "  music-stack audio normalize {} out.wav".format(path.suffix, path)
            )
        size = path.stat().st_size
        if size > MAX_UPLOAD_BYTES:
            raise MusicStackError(
                "{} is {:.1f} MB; Kits caps uploads at {} MB.".format(
                    path, size / 1024 / 1024, MAX_UPLOAD_BYTES // 1024 // 1024
                )
            )
        return path

    # -- API surface ------------------------------------------------------

    def voice_models(self):
        """List the voice models available to this account."""
        path, verified = self._path("voice_models")
        payload = self._call("GET", path, verified=verified).json()
        # The API has returned both a bare list and a wrapped object across
        # versions; accept either rather than break on the wrapper.
        if isinstance(payload, dict):
            return payload.get("data") or payload.get("voiceModels") or []
        return payload

    def _create_job(self, key, *, files, fields=None, sleep=time.sleep):
        path, verified = self._path(key)
        body, content_type = self._t.encode_multipart(fields or {}, files)
        self._respect_rate_limit(sleep=sleep)
        payload = self._call(
            "POST",
            path,
            verified=verified,
            data=body,
            headers={"Content-Type": content_type},
        ).json()
        job_id = payload.get("id") or payload.get("jobId")
        if not job_id:
            raise JobError(
                "Kits accepted the job but returned no id", detail=payload
            )
        return payload

    def get_job(self, key, job_id):
        path, verified = self._path(key)
        return self._call("GET", "{}/{}".format(path, job_id), verified=verified).json()

    def wait(self, key, job_id, *, timeout=900, interval=10, sleep=None):
        """Poll a Kits job until it succeeds, fails, or times out."""
        kwargs = {"timeout": timeout, "interval": interval}
        if sleep is not None:
            kwargs["sleep"] = sleep
        final = self._t.poll(
            lambda: self.get_job(key, job_id),
            lambda job: str(job.get("status", "")).lower() in TERMINAL_STATUSES,
            **kwargs
        )
        if final is None:
            raise JobTimeout(
                "Kits job {} did not finish within {}s.".format(job_id, timeout),
                job_id=job_id,
            )
        status = str(final.get("status", "")).lower()
        if status in FAILED_STATUSES:
            raise JobError(
                "Kits job {} failed: {}".format(
                    job_id, final.get("error") or "no reason given"
                ),
                job_id=job_id,
                status=status,
                detail=final,
            )
        return final

    def download_outputs(self, job, dest_dir):
        """Download every signed output URL on a finished Kits job.

        Kits' result links are short-lived, so this runs immediately after
        the job resolves rather than being deferred to a later command.
        """
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        written = {}
        for name, value in job.items():
            if not isinstance(value, str):
                continue
            if not value.startswith(("http://", "https://")):
                continue
            if not name.lower().endswith(("url", "file", "audio")):
                continue
            suffix = Path(value.split("?", 1)[0]).suffix or ".wav"
            target = dest / "{}{}".format(name, suffix)
            self._t.download_file(value, str(target))
            written[name] = str(target)
        if not written:
            raise JobError(
                "Kits job finished but exposed no downloadable output URLs; "
                "fields were {}".format(sorted(job)),
                detail=job,
            )
        return written

    # -- convenience ------------------------------------------------------

    def convert_voice(self, *, path, voice_model_id, dest_dir, timeout=900,
                      sleep=None):
        self.validate_input(path)
        job = self._create_job(
            "voice_conversion",
            files={"soundFile": str(path)},
            fields={"voiceModelId": voice_model_id},
            sleep=sleep or time.sleep,
        )
        final = self.wait("voice_conversion", job["id"], timeout=timeout, sleep=sleep)
        return {"job": final, "files": self.download_outputs(final, dest_dir)}

    def separate_vocals(self, *, path, dest_dir, timeout=900, sleep=None):
        self.validate_input(path)
        job = self._create_job(
            "vocal_separation",
            files={"soundFile": str(path)},
            sleep=sleep or time.sleep,
        )
        final = self.wait("vocal_separation", job["id"], timeout=timeout, sleep=sleep)
        return {"job": final, "files": self.download_outputs(final, dest_dir)}

    def split_stems(self, *, path, dest_dir, timeout=900, sleep=None):
        self.validate_input(path)
        job = self._create_job(
            "stem_split",
            files={"soundFile": str(path)},
            sleep=sleep or time.sleep,
        )
        final = self.wait("stem_split", job["id"], timeout=timeout, sleep=sleep)
        return {"job": final, "files": self.download_outputs(final, dest_dir)}
