"""Allow ``python -m am3d.ui`` to launch the editor."""

from .app import main

if __name__ == "__main__":
    raise SystemExit(main())