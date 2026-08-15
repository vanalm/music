"""Music.AI adapter.

Documented contract this is written against (see ``docs/architecture.md`` for
verification status):

* Base URL ``https://api.music.ai/v1``
* ``Authorization: <api-key>`` — the raw key, **not** ``Bearer <key>``
* ``GET  /upload``    → ``{"uploadUrl": ..., "downloadUrl": ...}``
* ``PUT  <uploadUrl>`` — the file bytes, sent to signed storage with no key
* ``POST /job``       → ``{"name", "workflow", "params": {"inputUrl": ...}}``
* ``GET  /job/{id}``  → ``status`` in QUEUED / STARTED / SUCCEEDED / FAILED,
  with ``result`` a mapping of output name → signed download URL, and
  ``error`` an object of ``{code, title, message}`` when it failed
* ``DELETE /job/{id}`` — removes the remote job and its stored outputs

The three-step upload is the reason ``http`` splits API calls from storage
calls: step 1 is authenticated to ``api.music.ai``, step 2 goes to whatever
bucket the service nominated and must carry no credential at all.
"""

from pathlib import Path

from .. import http
from ..errors import JobError, JobTimeout

API_BASE = "https://api.music.ai/v1"

#: The only host this adapter's credential may ever reach.
ALLOWED_HOSTS = ("api.music.ai",)

TERMINAL_STATUSES = ("SUCCEEDED", "FAILED")


class MusicAIClient:
    """Thin, explicit client over the Music.AI REST API."""

    def __init__(self, api_key, *, base=API_BASE, transport=None):
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self.base = base.rstrip("/")
        # Injected in tests; production uses the module's real functions.
        self._t = transport or http

    # -- plumbing ---------------------------------------------------------

    def _headers(self):
        return {"Authorization": self._api_key}

    def _call(self, method, path, **kwargs):
        return self._t.api_request(
            method,
            "{}{}".format(self.base, path),
            allowed_hosts=ALLOWED_HOSTS,
            headers=self._headers(),
            **kwargs
        )

    # -- API surface ------------------------------------------------------

    def application(self):
        """Return the account/application record, including its workflows."""
        return self._call("GET", "/application").json()

    def workflows(self, contains=None):
        """List the account's workflows, optionally filtered by substring.

        Workflow slugs are account-specific — there is no universal list — so
        this is the command to run *before* spending credits on a job.
        """
        payload = self.application()
        items = payload.get("workflows") or []
        if contains:
            needle = contains.lower()
            items = [
                w
                for w in items
                if needle in str(w.get("slug", "")).lower()
                or needle in str(w.get("name", "")).lower()
            ]
        return items

    def upload(self, path):
        """Upload a local file, returning the ``downloadUrl`` to feed a job.

        Two hops: ask the API for a signed pair, then PUT the bytes to the
        signed URL *without* the API key.
        """
        signed = self._call("GET", "/upload").json()
        upload_url = signed.get("uploadUrl")
        download_url = signed.get("downloadUrl")
        if not upload_url or not download_url:
            raise JobError(
                "Music.AI did not return an upload/download URL pair; got keys "
                "{}".format(sorted(signed))
            )
        self._t.upload_file(upload_url, str(path))
        return download_url

    def create_job(self, *, name, workflow, input_url, params=None):
        """Create a workflow job over an already-uploaded input URL."""
        body = {
            "name": name,
            "workflow": workflow,
            "params": dict(params or {}, inputUrl=input_url),
        }
        payload = self._call("POST", "/job", json_body=body).json()
        job_id = payload.get("id")
        if not job_id:
            raise JobError("Music.AI accepted the job but returned no id", detail=payload)
        return payload

    def get_job(self, job_id):
        return self._call("GET", "/job/{}".format(job_id)).json()

    def delete_job(self, job_id):
        """Delete the remote job and its stored outputs."""
        return self._call("DELETE", "/job/{}".format(job_id))

    def wait(self, job_id, *, timeout=900, interval=5, sleep=None):
        """Poll until the job reaches a terminal status.

        Raises :class:`JobTimeout` on the deadline and :class:`JobError` if
        the service reports FAILED, so callers never have to inspect status
        strings themselves.
        """
        kwargs = {"timeout": timeout, "interval": interval}
        if sleep is not None:
            kwargs["sleep"] = sleep
        final = self._t.poll(
            lambda: self.get_job(job_id),
            lambda job: str(job.get("status", "")).upper() in TERMINAL_STATUSES,
            **kwargs
        )
        if final is None:
            raise JobTimeout(
                "Music.AI job {} did not finish within {}s. It may still be "
                "running — check `music-stack music-ai job {}`.".format(
                    job_id, timeout, job_id
                ),
                job_id=job_id,
            )
        status = str(final.get("status", "")).upper()
        if status == "FAILED":
            err = final.get("error") or {}
            raise JobError(
                "Music.AI job {} failed: {}".format(
                    job_id, err.get("message") or err.get("title") or "no reason given"
                ),
                job_id=job_id,
                status=status,
                detail=err,
            )
        return final

    def download_results(self, job, dest_dir):
        """Download every output URL in ``job['result']`` into *dest_dir*.

        Result values that are not URLs (Music.AI returns inline JSON for some
        analysis workflows) are written out as ``.json`` instead of fetched.
        """
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        written = {}
        for name, value in (job.get("result") or {}).items():
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                suffix = _suffix_from_url(value)
                target = dest / "{}{}".format(name, suffix)
                self._t.download_file(value, str(target))
            else:
                import json as _json

                target = dest / "{}.json".format(name)
                target.write_text(
                    _json.dumps(value, indent=2) + "\n", encoding="utf-8"
                )
            written[name] = str(target)
        return written

    # -- convenience ------------------------------------------------------

    def process(self, *, path, workflow, dest_dir, name=None, params=None,
                timeout=900, sleep=None):
        """Upload → job → poll → download, the whole round trip."""
        input_url = self.upload(path)
        job = self.create_job(
            name=name or Path(path).stem,
            workflow=workflow,
            input_url=input_url,
            params=params,
        )
        final = self.wait(job["id"], timeout=timeout, sleep=sleep)
        files = self.download_results(final, dest_dir)
        return {"job": final, "files": files}


def _suffix_from_url(url):
    """Best-effort file extension from a signed URL's path component."""
    from urllib.parse import urlparse

    suffix = Path(urlparse(url).path).suffix
    return suffix if 1 < len(suffix) <= 6 else ".bin"
