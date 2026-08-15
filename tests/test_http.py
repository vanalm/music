"""Tests for the HTTP layer, concentrating on the credential boundary."""

import os
import tempfile
import unittest

from music_stack import http
from music_stack.errors import CredentialLeakError


class HostAllowListTests(unittest.TestCase):
    def test_exact_host_allowed(self):
        self.assertTrue(http._host_allowed("api.music.ai", ("api.music.ai",)))

    def test_subdomain_allowed(self):
        self.assertTrue(http._host_allowed("eu.arpeggi.io", ("arpeggi.io",)))

    def test_lookalike_domain_rejected(self):
        # The dot anchor is the whole point: a domain merely *ending in* the
        # allowed string must not pass.
        self.assertFalse(http._host_allowed("evil-music.ai", ("music.ai",)))
        self.assertFalse(http._host_allowed("notarpeggi.io", ("arpeggi.io",)))

    def test_case_insensitive(self):
        self.assertTrue(http._host_allowed("API.Music.AI", ("api.music.ai",)))


class ApiRequestGuardTests(unittest.TestCase):
    def test_refuses_credentialed_call_to_foreign_host(self):
        with self.assertRaises(CredentialLeakError) as ctx:
            http.api_request(
                "GET",
                "https://storage.googleapis.com/bucket/file.wav",
                allowed_hosts=("api.music.ai",),
                headers={"Authorization": "secret-key"},
            )
        self.assertIn("storage.googleapis.com", str(ctx.exception))

    def test_error_names_the_safe_alternative(self):
        with self.assertRaises(CredentialLeakError) as ctx:
            http.api_request(
                "PUT",
                "https://s3.amazonaws.com/x",
                allowed_hosts=("arpeggi.io",),
            )
        self.assertIn("storage_request", str(ctx.exception))

    def test_guard_runs_before_any_network_attempt(self):
        # A blocked host must raise CredentialLeakError, never a socket error.
        with self.assertRaises(CredentialLeakError):
            http.api_request(
                "GET",
                "https://192.0.2.1/unroutable",
                allowed_hosts=("api.music.ai",),
                timeout=0.001,
            )


class StorageRequestGuardTests(unittest.TestCase):
    def test_refuses_authorization_header(self):
        with self.assertRaises(CredentialLeakError):
            http.storage_request(
                "PUT",
                "https://storage.googleapis.com/bucket/f",
                headers={"Authorization": "Bearer leak"},
            )

    def test_refuses_api_key_header_any_case(self):
        with self.assertRaises(CredentialLeakError):
            http.storage_request(
                "GET", "https://cdn.example/f", headers={"X-Api-Key": "leak"}
            )

    def test_refuses_cookie_header(self):
        with self.assertRaises(CredentialLeakError):
            http.storage_request(
                "GET", "https://cdn.example/f", headers={"Cookie": "session=leak"}
            )


class MultipartTests(unittest.TestCase):
    def test_encodes_fields_and_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "take.wav")
            with open(path, "wb") as fh:
                fh.write(b"RIFFfake")
            body, ctype = http.encode_multipart({"voiceModelId": 1014961}, {"soundFile": path})

        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        boundary = ctype.split("boundary=", 1)[1]
        self.assertIn(b'name="voiceModelId"', body)
        self.assertIn(b"1014961", body)
        self.assertIn(b'name="soundFile"; filename="take.wav"', body)
        self.assertIn(b"RIFFfake", body)
        # A well-formed body ends with the closing boundary.
        self.assertTrue(body.endswith("--{}--\r\n".format(boundary).encode()))

    def test_skips_none_fields(self):
        body, _ = http.encode_multipart({"a": None, "b": "x"}, {})
        self.assertNotIn(b'name="a"', body)
        self.assertIn(b'name="b"', body)


class PollTests(unittest.TestCase):
    def test_returns_first_terminal_value(self):
        values = iter([{"s": "QUEUED"}, {"s": "STARTED"}, {"s": "SUCCEEDED"}])
        result = http.poll(
            lambda: next(values),
            lambda v: v["s"] == "SUCCEEDED",
            interval=0,
            sleep=lambda _s: None,
        )
        self.assertEqual(result["s"], "SUCCEEDED")

    def test_returns_none_on_timeout(self):
        result = http.poll(
            lambda: {"s": "QUEUED"},
            lambda v: v["s"] == "SUCCEEDED",
            timeout=0,
            interval=0,
            sleep=lambda _s: None,
        )
        self.assertIsNone(result)

    def test_backs_off_between_attempts(self):
        waits = []
        values = iter([{"d": False}, {"d": False}, {"d": False}, {"d": True}])
        http.poll(
            lambda: next(values),
            lambda v: v["d"],
            interval=2,
            max_interval=10,
            sleep=waits.append,
        )
        # Strictly increasing: 2, 3, 4.5 -- never hammers a slow render.
        self.assertEqual(len(waits), 3)
        self.assertLess(waits[0], waits[1])
        self.assertLess(waits[1], waits[2])


class DownloadTests(unittest.TestCase):
    def test_partial_file_removed_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.wav")
            with self.assertRaises(Exception):
                http.download_file("https://192.0.2.1/nope", dest, timeout=0.01)
            # Neither the target nor a stray .part file survives a failure.
            self.assertEqual(os.listdir(tmp), [])


if __name__ == "__main__":
    unittest.main()
