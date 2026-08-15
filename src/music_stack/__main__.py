"""Allow ``python -m music_stack`` as well as the ``music-stack`` script."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
