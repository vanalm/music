"""Kits AI adapter tests."""

import os
import tempfile
import unittest

from fakes import FakeTransport, Sequence
from music_stack import http
from music_stack.adapters import kits as kits_module
from music_stack.adapters.kits import KitsClient
from music_stack.errors import JobError, MusicStackError

KEY = "test-kits-key"


def wav(tmp, name="take.wav", data=b"RIFFfake"):
    path = os.path.join(tmp, name)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


class KitsAuthTests(unittest.TestCase):
    def test_uses_bearer_scheme(self):
        # Unlike Music.AI, Kits documents a Bearer token.
        transport = FakeTransport({("GET", "/voice-models"): []})
        KitsClient(KEY, transport=transport).voice_models()
        self.assertEqual(
            transport.api_calls()[0][3]["Authorization"], "Bearer " + KEY
        )

    def test_credential_scoped_to_arpeggi_host(self):
        transport = FakeTransport({("GET", "/voice-models"): []})
        client = KitsClient(KEY, transport=transport, base="https://api.music.ai/v1")
        # Pointing the Kits client at another vendor's host must be refused
        # before the Kits key is transmitted.
        with self.assertRaises(Exception) as ctx:
            client.voice_models()
        self.assertIn("credentials", str(ctx.exception).lower())

    def test_voice_models_accepts_wrapped_or_bare_list(self):
        bare = FakeTransport({("GET", "/voice-models"): [{"id": 1}]})
        self.assertEqual(len(KitsClient(KEY, transport=bare).voice_models()), 1)
        wrapped = FakeTransport({("GET", "/voice-models"): {"data": [{"id": 1}, {"id": 2}]}})
        self.assertEqual(len(KitsClient(KEY, transport=wrapped).voice_models()), 2)


class KitsValidationTests(unittest.TestCase):
    def test_rejects_unsupported_format_with_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = wav(tmp, "demo.mov")
            with self.assertRaises(MusicStackError) as ctx:
                KitsClient.validate_input(bad)
            self.assertIn("audio normalize", str(ctx.exception))

    def test_rejects_oversized_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            big = os.path.join(tmp, "big.wav")
            with open(big, "wb") as fh:
                fh.truncate(kits_module.MAX_UPLOAD_BYTES + 1)
            with self.assertRaises(MusicStackError) as ctx:
                KitsClient.validate_input(big)
            self.assertIn("caps uploads", str(ctx.exception))

    def test_accepts_supported_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(KitsClient.validate_input(wav(tmp)))

    def test_missing_file(self):
        with self.assertRaises(MusicStackError):
            KitsClient.validate_input("/nope/missing.wav")


class KitsRoundTripTests(unittest.TestCase):
    def test_voice_conversion_posts_multipart_and_downloads(self):
        transport = FakeTransport(
            {
                ("POST", "/voice-conversions"): {"id": 77, "status": "running"},
                ("GET", "/voice-conversions/77"): Sequence(
                    {"id": 77, "status": "running"},
                    {
                        "id": 77,
                        "status": "success",
                        "outputFileUrl": "https://cdn.arpeggi.io/out/77.wav?sig=x",
                    },
                ),
            }
        )
        client = KitsClient(KEY, transport=transport, min_post_interval=0)
        with tempfile.TemporaryDirectory() as tmp:
            result = client.convert_voice(
                path=wav(tmp),
                voice_model_id=1014961,
                dest_dir=os.path.join(tmp, "out"),
                sleep=lambda _s: None,
            )

        self.assertEqual(result["job"]["status"], "success")
        self.assertIn("outputFileUrl", result["files"])

        post = [c for c in transport.api_calls() if c[1] == "POST"][0]
        self.assertTrue(post[3]["Content-Type"].startswith("multipart/form-data"))

        # The signed CDN download carried no credential.
        downloads = [c for c in transport.storage_calls() if c[0] == "download"]
        self.assertEqual(len(downloads), 1)
        self.assertEqual(len(downloads[0]), 3)

    def test_failed_job_raises(self):
        transport = FakeTransport(
            {
                ("POST", "/voice-separations"): {"id": 5},
                ("GET", "/voice-separations/5"): {
                    "id": 5,
                    "status": "error",
                    "error": "input too short",
                },
            }
        )
        client = KitsClient(KEY, transport=transport, min_post_interval=0)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(JobError) as ctx:
                client.separate_vocals(
                    path=wav(tmp), dest_dir=tmp, sleep=lambda _s: None
                )
            self.assertIn("input too short", str(ctx.exception))

    def test_job_without_outputs_is_an_error_not_a_silent_success(self):
        transport = FakeTransport({})
        client = KitsClient(KEY, transport=transport, min_post_interval=0)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(JobError) as ctx:
                client.download_outputs({"id": 3, "status": "success"}, tmp)
            self.assertIn("no downloadable output", str(ctx.exception))


class KitsUnverifiedEndpointTests(unittest.TestCase):
    def test_404_on_unverified_path_explains_the_one_line_fix(self):
        transport = FakeTransport(
            {("POST", "/stem-splits"): http.HttpError("HTTP 404", status=404)}
        )
        client = KitsClient(KEY, transport=transport, min_post_interval=0)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(JobError) as ctx:
                client.split_stems(path=wav(tmp), dest_dir=tmp, sleep=lambda _s: None)
        message = str(ctx.exception)
        self.assertIn("unverified", message)
        self.assertIn("kits.py", message)

    def test_404_on_verified_path_is_not_rewritten(self):
        # A 404 on a confirmed path means "no such job", not "wrong path".
        transport = FakeTransport(
            {("GET", "/voice-models"): http.HttpError("HTTP 404", status=404)}
        )
        client = KitsClient(KEY, transport=transport)
        with self.assertRaises(http.HttpError):
            client.voice_models()

    def test_verified_flags_are_declared_for_every_endpoint(self):
        for key, (path, verified) in kits_module.ENDPOINTS.items():
            self.assertTrue(path.startswith("/"), key)
            self.assertIsInstance(verified, bool, key)


class KitsRateLimitTests(unittest.TestCase):
    def test_spaces_out_consecutive_posts(self):
        """Kits' alpha allows ~1 job-creating POST per account per minute."""
        now = [1000.0]
        slept = []

        def clock():
            return now[0]

        def sleep(seconds):
            slept.append(seconds)
            now[0] += seconds

        transport = FakeTransport(
            {
                ("POST", "/voice-separations"): {"id": 1},
                ("GET", "/voice-separations/1"): {
                    "id": 1,
                    "status": "success",
                    "outputFileUrl": "https://cdn.arpeggi.io/1.wav",
                },
            }
        )
        client = KitsClient(
            KEY, transport=transport, min_post_interval=60, clock=clock
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = wav(tmp)
            client.separate_vocals(path=path, dest_dir=tmp, sleep=sleep)
            client.separate_vocals(path=path, dest_dir=tmp, sleep=sleep)

        # The first POST does not wait; the second is held for the interval.
        self.assertIn(60, [round(s) for s in slept])

    def test_interval_zero_disables_the_spacer(self):
        slept = []
        transport = FakeTransport(
            {
                ("POST", "/voice-separations"): {"id": 1},
                ("GET", "/voice-separations/1"): {
                    "id": 1,
                    "status": "success",
                    "outputFileUrl": "https://cdn.arpeggi.io/1.wav",
                },
            }
        )
        client = KitsClient(KEY, transport=transport, min_post_interval=0)
        with tempfile.TemporaryDirectory() as tmp:
            path = wav(tmp)
            client.separate_vocals(path=path, dest_dir=tmp, sleep=slept.append)
            client.separate_vocals(path=path, dest_dir=tmp, sleep=slept.append)
        self.assertNotIn(60, [round(s) for s in slept])


if __name__ == "__main__":
    unittest.main()
