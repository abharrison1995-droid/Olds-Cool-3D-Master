"""Allow ``python -m am3d.ui`` to launch the editor.

Uses an absolute import (not ``from .app import main``): PyInstaller's
bootstrap runs this script as ``__main__`` without preserving
``__package__``, so a relative import raises "attempted relative import
with no known parent package" in the packaged build even though it works
fine under ``python -m am3d.ui``. (Same root cause as am3d/recipes/__main__.py;
see am3d.spec's Analysis entry point.) A windowed (console=False) build
crashing here doesn't visibly exit -- it can sit in a hung/crash-dialog
state indefinitely, which is why this was not caught by a shallow
"process didn't exit after N seconds" check.
"""

from am3d.ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())