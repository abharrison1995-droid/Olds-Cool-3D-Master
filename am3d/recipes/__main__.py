"""Allows ``python -m am3d.recipes --recipe asset.json``.

Uses an absolute import (not ``from .cli import main``): PyInstaller's
onefile bootstrap (see am3d_recipe.spec) runs this script as ``__main__``
without preserving ``__package__``, so a relative import raises
"attempted relative import with no known parent package" in the packaged
build even though it works fine under ``python -m am3d.recipes``.
"""

from am3d.recipes.cli import main

if __name__ == "__main__":
    raise SystemExit(main())