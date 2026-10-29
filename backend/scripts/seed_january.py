"""Seed the January 2026 study window. Equivalent to ``python -m app.cli seed``."""

import sys

from app.cli import main

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "seed", *sys.argv[1:]]
    main()
