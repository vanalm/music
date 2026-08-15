"""Music.AI adapter tests, including the full mocked round trip."""

import pathlib
import tempfile
import unittest

from fakes import FakeTransport, Sequence
from music_stack.adapters.music_ai import MusicAIClient
from music_stack.errors import JobError, JobTimeout

KEY = "test-music-ai-key"
UPLOAD_PAIR = {
    "uploadUrl": "https://storage.googleapis.com/upload/signed?sig=abc",
    "downloadUrl": "https://storage.googleapis.com/download/signed?sig=def",
}


def succeeded_job(job_id="job-1"):
    return {
        "id": job_id,
        "status": "SUCCEEDED",
        "workflow": "stems-v2",
        "result": {
            "vocals": "https://storage.googleapis.com/out/vocals.wav?sig=1",
            "accompaniments": "https://storage.googleapis.com/out/inst.wav?sig=2",
        },
        "error": None,
    }


class MusicAIRoundTripTests(unittest.TestCase):
    def _client(self, routes):
        transport = FakeTransport(routes)
        return MusicAIClient(KEY, transport=transport), transport

    def test_process_uploads_runs_and_downloads(self):
        client, transport = self._client(
            {
                ("GET", "/upload"): UPLOAD_PAIR,
                ("POST", "/job"): {"id": "job-1", "status": "QUEUED"},
                ("GET", "/job/job-1"): Sequence(
                    {"id": "job-1", "status": "QUEUED"},
                    {"id": "job-1", "status": "STARTED"},
                    succeeded_job(),
                ),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = "{}/demo.wav".format(tmp)
            pathlib.Path(src).write_bytes(b"RIFF")
            result = client.process(
                path=src, workflow="stems-v2", dest_dir=tmp + "/out", sleep=lambda _s: None
            )

        self.assertEqual(result["job"]["status"], "SUCCEEDED")
        self.assertEqual(sorted(result["files"]), ["accompaniments", "vocals"])
        self.assertTrue(result["files"]["vocals"].endswith("vocals.wav"))

    def test_api_key_never_reaches_storage_hosts(self):
        """The security property this stack exists to get right."""
        client, transport = self._client(
            {
                ("GET", "/upload"): UPLOAD_PAIR,
                ("POST", "/job"): {"id": "job-1"},
                ("GET", "/job/job-1"): succeeded_job(),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = "{}/demo.wav".format(tmp)
            pathlib.Path(src).write_bytes(b"RIFF")
            client.process(path=src, workflow="w", dest_dir=tmp, sleep=lambda _s: None)

        # Every credentialed call went to api.music.ai and nowhere else.
        for _kind, _method, url, headers in transport.api_calls():
            self.assertIn("api.music.ai", url)
            self.assertEqual(headers["Authorization"], KEY)

        # Storage traffic happened, and carried no headers at all.
        storage = transport.storage_calls()
        self.assertTrue(storage, "expected upload + downloads")
        for call in storage:
            self.assertNotIn("api.music.ai", call[1])
            self.assertIn("storage.googleapis.com", call[1])
            self.assertEqual(len(call), 3)  # (kind, url, path) -- no headers slot

    def test_uses_raw_key_not_bearer(self):
        # Music.AI documents the bare key; sending "Bearer <key>" 401s.
        client, transport = self._client({("GET", "/application"): {"workflows": []}})
        client.application()
        header = transport.api_calls()[0][3]["Authorization"]
        self.assertEqual(header, KEY)
        self.assertFalse(header.startswith("Bearer"))

    def test_failed_job_raises_with_service_message(self):
        client, _ = self._client(
            {
                ("GET", "/job/job-9"): {
                    "id": "job-9",
                    "status": "FAILED",
                    "error": {"code": "BAD_INPUT", "message": "unsupported sample rate"},
                }
            }
        )
        with self.assertRaises(JobError) as ctx:
            client.wait("job-9", sleep=lambda _s: None)
        self.assertIn("unsupported sample rate", str(ctx.exception))
        self.assertEqual(ctx.exception.job_id, "job-9")

    def test_timeout_raises_job_timeout(self):
        client, _ = self._client(
            {("GET", "/job/job-5"): {"id": "job-5", "status": "STARTED"}}
        )
        with self.assertRaises(JobTimeout) as ctx:
            client.wait("job-5", timeout=0, sleep=lambda _s: None)
        self.assertIn("job-5", str(ctx.exception))

    def test_upload_rejects_incomplete_signed_pair(self):
        client, _ = self._client({("GET", "/upload"): {"uploadUrl": "https://x/y"}})
        with self.assertRaises(JobError):
            client.upload("/tmp/whatever.wav")

    def test_non_url_results_are_written_as_json(self):
        """Analysis workflows return inline data, not links."""
        client, transport = self._client({})
        job = {"result": {"chords": [{"time": 0.0, "chord": "Am"}], "key": "A minor"}}
        with tempfile.TemporaryDirectory() as tmp:
            files = client.download_results(job, tmp)
            self.assertTrue(files["chords"].endswith("chords.json"))
            with open(files["chords"]) as fh:
                self.assertIn("Am", fh.read())
        # Nothing was fetched over the network for inline results.
        self.assertEqual(transport.storage_calls(), [])

    def test_workflows_filter_matches_slug_and_name(self):
        client, _ = self._client(
            {
                ("GET", "/application"): {
                    "workflows": [
                        {"slug": "stems-v2", "name": "Stem separation"},
                        {"slug": "lyrics-v1", "name": "Lyric transcription"},
                    ]
                }
            }
        )
        self.assertEqual(len(client.workflows(contains="stem")), 1)
        self.assertEqual(len(client.workflows(contains="transcription")), 1)
        self.assertEqual(len(client.workflows()), 2)


if __name__ == "__main__":
    unittest.main()
