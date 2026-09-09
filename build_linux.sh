#!/usr/bin/env bash
#
# Build the 3D MASTER:2005 Linux x86-64 distribution and stage a release
# folder: an isolated build venv, the full test suite, both PyInstaller
# entry points (windowed GUI + headless recipe CLI), a packaged smoke run,
# a relocation check from a path with spaces and non-ASCII characters, a
# reproducible tarball, its SHA-256, and a build-provenance file.
#
# The Linux counterpart of build_windows.ps1, step for step, so the two
# platforms are verified the same way rather than one being trusted.
#
#   ./build_linux.sh              full build
#   ./build_linux.sh --skip-tests skip step 3 (for iterating on packaging)
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

SKIP_TESTS=0
for arg in "$@"; do
    case "$arg" in
        --skip-tests) SKIP_TESTS=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

APP_NAME="3D MASTER 2005"
RELEASE_NAME="3D MASTER 2005 Beta"
BUILD_DIR="$REPO_ROOT/build/linux"
VENV_DIR="$BUILD_DIR/venv"
DIST_DIR="$BUILD_DIR/dist"
WORK_DIR="$BUILD_DIR/work"
RELEASE_DIR="$REPO_ROOT/release/$RELEASE_NAME"
SMOKE_TIMEOUT=120

info()  { printf '\033[36m%s\033[0m\n' "$*"; }
step()  { printf '\n\033[33m%s\033[0m\n' "$*"; }
ok()    { printf '\033[32m  %s\033[0m\n' "$*"; }
die()   { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

info "=== 3D MASTER:2005 Linux Build ==="

# ---- 1. Isolated build environment ----------------------------------------
# A dedicated venv under build/, never the developer's own .venv: a release
# payload must be built from the pinned set in requirements-dev.txt and
# nothing else, so a stray locally-installed package cannot slip in.
step "Step 1: Preparing an isolated build environment..."
command -v python3 >/dev/null || die "python3 not found"
PY_VERSION="$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
python3 - <<'PY' || die "Python 3.11+ is required (see docs/SUPPORTED_PLATFORMS.md, ENV-01)"
import sys
raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)
PY
ok "Python: $PY_VERSION"
rm -rf "$VENV_DIR"
PY="$VENV_DIR/bin/python"
# Debian-family systems commonly ship python3 without ensurepip (the
# python3-venv package is separate), so `python3 -m venv` cannot bootstrap
# pip there -- the reference machine is one of them. uv creates a working
# environment without ensurepip, so it is used when present and the stock
# venv module is the fallback.
VENV_TOOL=""
if python3 -m venv "$VENV_DIR" >/dev/null 2>&1 && "$PY" -m pip --version >/dev/null 2>&1; then
    VENV_TOOL="venv"
elif command -v uv >/dev/null 2>&1; then
    rm -rf "$VENV_DIR"
    # Absolute path, not the bare name: `--python python3` lets uv pick one
    # of its own managed interpreters, which silently built the release on a
    # different Python version than the one the tests were verified against.
    uv venv --python "$(command -v python3)" "$VENV_DIR" >/dev/null \
        || die "uv venv failed"
    VENV_TOOL="uv"
else
    die "cannot create a build venv: python3 -m venv has no pip (install python3-venv) and uv is not on PATH"
fi
ok "Build venv: $VENV_DIR (via $VENV_TOOL)"

pip_install() {
    if [ "$VENV_TOOL" = "uv" ]; then
        uv pip install --quiet --python "$PY" "$@"
    else
        "$PY" -m pip install --quiet "$@"
    fi
}

pip_freeze() {
    if [ "$VENV_TOOL" = "uv" ]; then
        uv pip freeze --python "$PY"
    else
        "$PY" -m pip freeze
    fi
}

step "Step 2: Installing pinned build dependencies..."
pip_install -r "$REPO_ROOT/requirements-dev.txt" \
    || die "dependency installation failed"
ok "$(pip_freeze | wc -l) packages installed from requirements-dev.txt"

# ---- 2. Tests --------------------------------------------------------------
step "Step 3: Running the test suite..."
if [ "$SKIP_TESTS" -eq 1 ]; then
    ok "SKIPPED (--skip-tests): this build is not release-qualified"
else
    QT_QPA_PLATFORM=offscreen "$PY" -m pytest "$REPO_ROOT/am3d" -q \
        || die "tests failed -- aborting the build"
    ok "All tests passed."
fi

# ---- 3. Freeze both entry points ------------------------------------------
step "Step 4: Building the windowed GUI with PyInstaller..."
rm -rf "$DIST_DIR" "$WORK_DIR"
"$PY" -m PyInstaller --clean --noconfirm \
    --distpath "$DIST_DIR" --workpath "$WORK_DIR" \
    "$REPO_ROOT/am3d.spec" || die "PyInstaller GUI build failed"
ok "GUI build completed."

step "Step 4b: Building the headless recipe CLI with PyInstaller..."
"$PY" -m PyInstaller --clean --noconfirm \
    --distpath "$DIST_DIR" --workpath "$WORK_DIR" \
    "$REPO_ROOT/am3d_recipe.spec" || die "PyInstaller recipe CLI build failed"
ok "Recipe CLI build completed."

# ---- 4. Qt platform plugins ------------------------------------------------
# The reference system runs KDE Plasma on Wayland, and the documented
# fallback route is QT_QPA_PLATFORM=xcb (XWayland). A bundle missing either
# plugin starts on the build machine and dies on the user's, so this is a
# hard check rather than a warning.
step "Step 5: Verifying the bundled Qt platform plugins..."
GUI_DIST="$DIST_DIR/$RELEASE_NAME"
[ -d "$GUI_DIST" ] || die "expected GUI bundle at $GUI_DIST"
# PySide6's wheel names its Wayland platform plugin libqwayland.so, where a
# distro Qt build splits it into libqwayland-generic.so and friends; accept
# either so the check tracks the capability rather than one packaging's
# filename.
check_plugin() {
    local label="$1"; shift
    local found=""
    for candidate in "$@"; do
        found="$(find "$GUI_DIST" -name "$candidate" -print -quit)"
        [ -n "$found" ] && break
    done
    [ -n "$found" ] || die "the bundle has no $label platform plugin (looked for: $*)"
    ok "$label -> ${found#$GUI_DIST/}"
}
check_plugin "Wayland" libqwayland.so libqwayland-generic.so
check_plugin "xcb (X11/XWayland)" libqxcb.so
check_plugin "offscreen" libqoffscreen.so
# The Wayland platform plugin is useless without a shell integration: the
# app starts, finds no shell, and exits with "could not find a Qt platform
# plugin" on exactly the reference machine's KDE/Wayland session.
check_plugin "Wayland shell integration" "libqt-shell.so" "libxdg-shell.so"

# ---- 5. Stage the release folder ------------------------------------------
step "Step 6: Staging the release folder..."
rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
cp -a "$GUI_DIST/." "$RELEASE_DIR/"
[ -f "$DIST_DIR/am3d-recipe" ] || die "recipe CLI executable not found"
cp -f "$DIST_DIR/am3d-recipe" "$RELEASE_DIR/am3d-recipe"
chmod +x "$RELEASE_DIR/am3d-recipe" "$RELEASE_DIR/$APP_NAME"
cp -a "$REPO_ROOT/assets" "$RELEASE_DIR/examples"
cp -f "$REPO_ROOT/README.md" "$RELEASE_DIR/README.txt"
cp -f "$REPO_ROOT/docs/SUPPORTED_PLATFORMS.md" "$RELEASE_DIR/SUPPORTED_PLATFORMS.md"

# Launcher covering the three documented graphics routes, so a user whose
# session cannot run the default does not have to know the environment
# variables by heart.
cat > "$RELEASE_DIR/3D-MASTER-2005.sh" <<'LAUNCHER'
#!/usr/bin/env bash
# 3D MASTER:2005 launcher.
#
#   ./3D-MASTER-2005.sh            native session (Wayland or X11)
#   ./3D-MASTER-2005.sh --xcb      force the xcb/XWayland route
#   ./3D-MASTER-2005.sh --software force software rendering (no GPU)
#
# See SUPPORTED_PLATFORMS.md for when to use which.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for arg in "$@"; do
    case "$arg" in
        --xcb)      export QT_QPA_PLATFORM=xcb; shift ;;
        --software) export LIBGL_ALWAYS_SOFTWARE=1; shift ;;
    esac
done
exec "$HERE/3D MASTER 2005" "$@"
LAUNCHER
chmod +x "$RELEASE_DIR/3D-MASTER-2005.sh"

mkdir -p "$RELEASE_DIR/LICENSES"
cat > "$RELEASE_DIR/LICENSES/NOTICE.txt" <<'NOTICE'
3D MASTER:2005 Beta
Copyright (c) 2026

This software uses:
- PySide6 (LGPL-3.0)
- NumPy (BSD-3-Clause)
- msgpack (Apache-2.0)
- Pillow (MIT-CMU)
- ModernGL (MIT)

See the respective packages for full license terms.
NOTICE
ok "Release staged at: $RELEASE_DIR"

# ---- 6. Packaged smoke test ------------------------------------------------
# Drives the packaged executable through a real workflow via its own
# --smoke-test flag (am3d/ui/smoke.py), and requires every step in the
# manifest to be "ok" -- an exit code alone would let a partially-run smoke
# test ship as silent missing evidence.
step "Step 7: Running the packaged GUI smoke test..."
MANIFEST="$RELEASE_DIR/smoke_manifest.json"
rm -f "$MANIFEST"
set +e
QT_QPA_PLATFORM=offscreen timeout "$SMOKE_TIMEOUT" \
    "$RELEASE_DIR/$APP_NAME" --smoke-test --out "$MANIFEST" \
    > "$RELEASE_DIR/smoke_stdout.txt" 2> "$RELEASE_DIR/smoke_stderr.txt"
SMOKE_RC=$?
set -e
[ "$SMOKE_RC" -eq 124 ] && die "packaged smoke test timed out after ${SMOKE_TIMEOUT}s"
[ -f "$MANIFEST" ] || { cat "$RELEASE_DIR/smoke_stderr.txt" >&2; \
    die "packaged smoke test produced no manifest (exit $SMOKE_RC)"; }
"$PY" - "$MANIFEST" "$SMOKE_RC" <<'PY' || die "packaged smoke test failed or is incomplete"
import json, sys
manifest = json.load(open(sys.argv[1]))
bad = [s for s in manifest.get("steps", []) if s.get("status") != "ok"]
if int(sys.argv[2]) != 0 or not manifest.get("ok") or bad:
    print(json.dumps(manifest, indent=2))
    raise SystemExit(1)
print(f"  Smoke test passed: {len(manifest['steps'])} steps, all ok.")
PY

step "Step 7b: Validating a recipe with the packaged CLI..."
"$RELEASE_DIR/am3d-recipe" --recipe "$REPO_ROOT/docs/recipes/examples/minimal.json" \
    --validate-only || die "packaged recipe CLI could not validate the bundled example"
ok "Recipe CLI validated the bundled example recipe."

# ---- 7. Archive, checksum, provenance -------------------------------------
step "Step 8: Packaging the release archive and checksum..."
VERSION="$("$PY" -c 'import am3d; print(am3d.__version__)')"
ARCHIVE_NAME="3D-MASTER-2005-Beta-$VERSION-linux-x86_64.tar.gz"
ARCHIVE_PATH="$REPO_ROOT/release/$ARCHIVE_NAME"
rm -f "$ARCHIVE_PATH" "$ARCHIVE_PATH.sha256"
# --sort=name and a fixed mtime keep the archive byte-reproducible across
# builds of the same tree; the payload itself is whatever PyInstaller made.
SOURCE_EPOCH="$(git -C "$REPO_ROOT" log -1 --format=%ct 2>/dev/null || echo 0)"
tar --sort=name --owner=0 --group=0 --numeric-owner \
    --mtime="@$SOURCE_EPOCH" \
    -czf "$ARCHIVE_PATH" -C "$REPO_ROOT/release" "$RELEASE_NAME"
( cd "$REPO_ROOT/release" && sha256sum "$ARCHIVE_NAME" > "$ARCHIVE_NAME.sha256" )
ok "Archive: $ARCHIVE_PATH"
ok "SHA-256: $(cut -d' ' -f1 < "$ARCHIVE_PATH.sha256")"

step "Step 8b: Writing build provenance..."
{
    echo "3D MASTER:2005 -- Linux build provenance"
    echo "archive          : $ARCHIVE_NAME"
    echo "sha256           : $(cut -d' ' -f1 < "$ARCHIVE_PATH.sha256")"
    echo "am3d version     : $VERSION"
    echo "git commit       : $(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "git status       : $(if [ -z "$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null)" ]; then echo clean; else echo "DIRTY -- built from uncommitted changes"; fi)"
    echo "built on         : $(uname -srmo)"
    echo "distribution     : $( (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || echo unknown)"
    echo "python (host)    : $PY_VERSION"
    echo "python (build)   : $("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
    echo "pyinstaller      : $("$PY" -m PyInstaller --version 2>/dev/null)"
    echo "tests            : $( [ "$SKIP_TESTS" -eq 1 ] && echo "SKIPPED -- not release-qualified" || echo "full suite passed" )"
    echo
    echo "pinned build set (pip freeze):"
    pip_freeze | sed 's/^/  /'
} > "$REPO_ROOT/release/BUILD_PROVENANCE-linux.txt"
ok "release/BUILD_PROVENANCE-linux.txt"

# ---- 8. Relocation check ---------------------------------------------------
# Unpacks the archive somewhere with a space and a non-ASCII character in
# the path and re-runs both entry points there, so a bundle that secretly
# depends on a build-machine path fails here instead of on a user's system.
step "Step 9: Verifying the archive from a relocated path..."
VERIFY_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/am3d verify éé XXXXXX")"
cleanup() { rm -rf "$VERIFY_ROOT"; }
trap cleanup EXIT
tar -xzf "$ARCHIVE_PATH" -C "$VERIFY_ROOT"
VERIFY_DIR="$VERIFY_ROOT/$RELEASE_NAME"
[ -x "$VERIFY_DIR/$APP_NAME" ] || die "extracted release has no GUI executable"
[ -x "$VERIFY_DIR/am3d-recipe" ] || die "extracted release has no recipe CLI"

cp -f "$REPO_ROOT/docs/recipes/examples/minimal.json" "$VERIFY_ROOT/standalone_recipe.json"
"$VERIFY_DIR/am3d-recipe" --recipe "$VERIFY_ROOT/standalone_recipe.json" --validate-only \
    || die "relocated recipe CLI failed on a source-independent recipe"

VERIFY_MANIFEST="$VERIFY_ROOT/verify_smoke_manifest.json"
set +e
QT_QPA_PLATFORM=offscreen timeout "$SMOKE_TIMEOUT" \
    "$VERIFY_DIR/$APP_NAME" --smoke-test --out "$VERIFY_MANIFEST" >/dev/null 2>&1
VERIFY_RC=$?
set -e
[ "$VERIFY_RC" -eq 124 ] && die "relocated smoke test timed out after ${SMOKE_TIMEOUT}s"
"$PY" - "$VERIFY_MANIFEST" "$VERIFY_RC" <<'PY' || die "relocated smoke test failed or is incomplete"
import json, sys
manifest = json.load(open(sys.argv[1]))
bad = [s for s in manifest.get("steps", []) if s.get("status") != "ok"]
if int(sys.argv[2]) != 0 or not manifest.get("ok") or bad:
    print(json.dumps(manifest, indent=2))
    raise SystemExit(1)
PY
ok "Relocated recipe CLI and GUI smoke test both passed."

info ""
info "=== Build complete! ==="
echo "Release folder : $RELEASE_DIR"
echo "Archive        : $ARCHIVE_PATH"
echo "Checksum       : $ARCHIVE_PATH.sha256"
echo "Provenance     : $REPO_ROOT/release/BUILD_PROVENANCE-linux.txt"
echo
echo "Launch with:  \"$RELEASE_DIR/3D-MASTER-2005.sh\""
echo "  --xcb       force the xcb/XWayland route"
echo "  --software  force software rendering"
