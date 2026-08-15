"""A programmable songwriting pipeline over Music.AI, Kits AI, and ffmpeg.

The package deliberately has **no third-party runtime dependencies** — every
HTTP call, multipart body, and poll loop is built on the standard library.
See ``docs/architecture.md`` for why.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
