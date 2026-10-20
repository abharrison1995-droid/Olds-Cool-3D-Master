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

import sys


# The AI recipe worker is a fixed, hidden child entry point. Keep this check
# above every UI import: frozen GUI builds may be console=False and must never
# initialize Qt for an internal data-only worker launch.
if len(sys.argv) >= 2 and sys.argv[1] == "--internal-ai-worker":
    from am3d.ai.worker import internal_worker_main

    raise SystemExit(internal_worker_main(sys.argv[2:]))

# The earlier M3 local-generation worker remains namespaced so it can coexist
# with the V1 AI workflow under am3d.ai.
if len(sys.argv) >= 2 and sys.argv[1] == "--am3d-generation-worker":
    from am3d.ai.m3.worker import main as generation_worker_main

    raise SystemExit(generation_worker_main(sys.argv[2:]))

# The build's fixed AI acceptance harness is also data-only and must start
# before importing the Qt application. It accepts only a host output folder;
# the implementation owns its provider mock, prompts, recipes and checks.
if len(sys.argv) >= 2 and sys.argv[1] == "--ai-self-test":
    from am3d.ai.frozen_acceptance import main as frozen_acceptance_main

    raise SystemExit(frozen_acceptance_main(sys.argv[2:]))

from am3d.ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
