"""Suno adapter — deliberately inert until you supply the official contract.

Suno's platform page confirms a REST API exists for songs, covers, and
mashups, but the endpoint and authentication detail sits behind an
authenticated account. This adapter therefore ships **fail-closed**: it will
not run until you paste the real base URL out of the docs you can see when
signed in.

What this module will never contain, and what you should refuse if any tool
offers it:

* an unofficial third-party wrapper standing in for the real API
* cookie or bearer-token extraction from a logged-in browser session
* a captcha workaround
* an invented endpoint path guessed from URL patterns

All four of those are terms-of-service violations and account-ban risks, and
they break silently the moment the vendor changes anything. Reading the real
schema once, from your own signed-in account, is both safer and less work.
"""

from ..errors import NotConfiguredError

#: Filled in from SUNO_API_BASE once you have read the authenticated docs.
CONFIG_VARS = ("SUNO_API_KEY", "SUNO_API_BASE")

STATUS_UNCONFIGURED = "unconfigured"
STATUS_READY = "ready"


def status(settings):
    """Report whether Suno is usable, and precisely what is missing."""
    missing = [name for name in CONFIG_VARS if not settings.get(name)]
    if missing:
        return {
            "status": STATUS_UNCONFIGURED,
            "missing": missing,
            "detail": (
                "Suno stays disabled until {} are set. Sign in at "
                "suno.com/platform, open the API reference, and copy the "
                "documented base URL into SUNO_API_BASE and your key into "
                "SUNO_API_KEY.".format(" and ".join(missing))
            ),
        }
    return {
        "status": STATUS_READY,
        "missing": [],
        "base": settings.get("SUNO_API_BASE"),
        "detail": (
            "Credentials are present. Implement the documented endpoints in "
            "src/music_stack/adapters/suno.py against the schema you read while "
            "signed in — this adapter intentionally ships without guessed paths."
        ),
    }


class SunoClient:
    """Placeholder that refuses to invent an API.

    Constructed only to give a clear, single failure point if some future
    code path assumes Suno is wired up.
    """

    def __init__(self, settings):
        state = status(settings)
        if state["status"] != STATUS_READY:
            raise NotConfiguredError(state["detail"])
        self.base = state["base"]

    def __getattr__(self, name):
        raise NotConfiguredError(
            "Suno endpoint {!r} is not implemented. Add it from the official, "
            "signed-in API reference — do not substitute an unofficial "
            "wrapper.".format(name)
        )
