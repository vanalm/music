"""Configuration and credential handling.

Credentials come from the environment, optionally seeded from a gitignored
``.env`` at the repo root. Real environment variables always win over ``.env``
so a shell export can override a file without editing it.

Nothing in this module ever returns a secret to a caller that only wants to
*report* on it: :func:`describe` deliberately yields presence and a fingerprint,
never the value.
"""

import hashlib
import os
from pathlib import Path

from .errors import ConfigError, NotConfiguredError

ENV_FILENAME = ".env"


def repo_root(start=None):
    """Walk upward from *start* looking for the project root.

    Falls back to the current working directory so the CLI still works when
    invoked from outside a checkout.
    """
    here = Path(start or os.getcwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
    return here


def parse_env(text):
    """Parse ``KEY=value`` lines into a dict.

    Supports ``export`` prefixes, ``#`` comments, blank lines, and single or
    double quoted values. Anything else is ignored rather than raising — a
    stray line in a hand-edited .env should not break the whole CLI.
    """
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def load_env(root=None, environ=None):
    """Merge ``.env`` under *root* into a copy of *environ*, env winning.

    Returns the merged mapping; the process environment is left untouched so
    tests and library callers stay isolated from one another.
    """
    environ = dict(os.environ if environ is None else environ)
    env_path = Path(root or repo_root()) / ENV_FILENAME
    if env_path.exists():
        file_values = parse_env(env_path.read_text(encoding="utf-8"))
        for key, value in file_values.items():
            environ.setdefault(key, value)
    return environ


def fingerprint(secret):
    """Return a short, non-reversible fingerprint of *secret*.

    Lets `doctor` prove two machines hold the *same* key without ever showing
    it. Truncated SHA-256 — enough to compare, useless to replay.
    """
    if not secret:
        return "—"
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]


class Settings:
    """Resolved settings for one CLI invocation."""

    #: Environment variable names, grouped by the service that needs them.
    SERVICES = {
        # Moises is the self-serve door to this engine; Music.AI is the same
        # company's enterprise-gated REST platform. Either key works on its own.
        "moises": ("MOISES_API_KEY",),
        "music-ai": ("MUSIC_AI_API_KEY",),
        "kits": ("KITS_API_KEY",),
        # Suno needs both a key *and* an explicitly confirmed base URL before
        # it will run at all — see adapters/suno.py for why.
        "suno": ("SUNO_API_KEY", "SUNO_API_BASE"),
    }

    def __init__(self, environ=None, root=None):
        self.root = Path(root or repo_root())
        self.environ = load_env(self.root, environ)

    def get(self, name, default=None):
        value = self.environ.get(name, default)
        if isinstance(value, str):
            value = value.strip()
        return value or default

    def require(self, name, *, service):
        """Return the value of *name* or explain how to set it."""
        value = self.get(name)
        if not value:
            raise NotConfiguredError(
                "{} is not set, so the {} commands cannot run.\n"
                "Add it to {}/.env (see .env.example) or export it in your "
                "shell, then re-run `music-stack doctor`.".format(
                    name, service, self.root
                )
            )
        return value

    @property
    def projects_dir(self):
        configured = self.get("MUSIC_STACK_PROJECTS_DIR")
        if configured:
            return Path(configured).expanduser()
        return self.root / "projects"

    def poll_timeout(self, default=900):
        raw = self.get("MUSIC_STACK_POLL_TIMEOUT")
        if not raw:
            return default
        try:
            return max(1, int(raw))
        except ValueError as exc:
            raise ConfigError(
                "MUSIC_STACK_POLL_TIMEOUT must be a whole number of seconds, "
                "got {!r}".format(raw)
            ) from exc

    def describe(self):
        """Report which credentials are configured — never their values.

        Returns a list of ``(service, variable, configured, fingerprint)``.
        """
        rows = []
        for service, names in self.SERVICES.items():
            for name in names:
                value = self.get(name)
                rows.append((service, name, bool(value), fingerprint(value)))
        return rows
