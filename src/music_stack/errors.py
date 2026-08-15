"""Exception types shared across the stack.

Every failure a user can plausibly cause — a missing credential, a rejected
file, a job that failed upstream — gets its own type so the CLI can print a
short, actionable message instead of a traceback.
"""


class MusicStackError(Exception):
    """Base class for every error this package raises deliberately."""


class ConfigError(MusicStackError):
    """A credential or setting is missing or malformed."""


class NotConfiguredError(ConfigError):
    """A service was used before it was configured.

    Distinct from :class:`ConfigError` because it is the expected state of a
    fresh checkout, not a mistake — the CLI reports it as guidance rather
    than as a failure.
    """


class AudioError(MusicStackError):
    """ffmpeg/ffprobe is missing, or an audio file could not be processed."""


class HttpError(MusicStackError):
    """A request failed at the transport or HTTP-status level."""

    def __init__(self, message, *, status=None, url=None, body=None):
        super().__init__(message)
        self.status = status
        self.url = url
        self.body = body


class CredentialLeakError(MusicStackError):
    """A credential was about to be sent to a host that must never see it.

    Raised by the HTTP layer's host allow-listing. This is a programming
    error, not a user error: it means an adapter tried to attach an API key
    to a signed-storage or otherwise third-party URL.
    """


class JobError(MusicStackError):
    """A remote processing job failed, was rejected, or timed out."""

    def __init__(self, message, *, job_id=None, status=None, detail=None):
        super().__init__(message)
        self.job_id = job_id
        self.status = status
        self.detail = detail


class JobTimeout(JobError):
    """A job did not reach a terminal state within the allotted time."""
