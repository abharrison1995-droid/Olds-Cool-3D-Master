"""Allows ``python -m am3d.recipes --recipe asset.json``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())