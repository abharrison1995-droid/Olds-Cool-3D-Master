#!/usr/bin/env bash
#
# Build the 3D MASTER:2005 Linux x86-64 distribution and stage a release
# folder: an isolated build venv, the full test suite, both PyInstaller
# entry points (windowed GUI + headless recipe CLI), a packaged smoke run,
# a relocation check from a path with spaces and non-ASCII characters, a
# normalized archive, its SHA-256, and a build-provenance file.
#
# The Linux counterpart of build_windows.ps1, step for step, so the two
# platforms are verified the same way rather than one being trusted.
#
#   ./build_linux.sh              full build
#   ./build_linux.sh --skip-tests skip step 3 (for iterating on packaging)
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
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

safe_remove_repo_dir() {
    local target="$1" allowed_root="$2" current target_abs
    target_abs="$(realpath -m -- "$target")"
    [ "$target" = "$target_abs" ] \
        || die "refusing a non-canonical or linked recursive-removal path: $target"
    case "$target_abs" in "$allowed_root"/*) ;; *) die "refusing recursive removal outside its intended root: $target" ;; esac
    current="$target_abs"
    while [ "$current" != "$allowed_root" ]; do
        [ ! -L "$current" ] || die "refusing recursive removal through a symlink: $current"
        current="$(dirname -- "$current")"
    done
    [ ! -L "$allowed_root" ] || die "refusing recursive removal from a symlink root: $allowed_root"
    [ -e "$target_abs" ] || return 0
    [ -d "$target_abs" ] && [ ! -L "$target_abs" ] || die "refusing to recursively remove a non-directory: $target"
    [ -z "$(find -P "$target_abs" -type l -print -quit)" ] \
        || die "refusing to recursively remove a tree containing links: $target"
    rm -rf -- "$target_abs"
}

safe_remove_repo_file() {
    local target="$1" allowed_root="$2" target_abs
    target_abs="$(realpath -m -- "$target")"
    [ "$target" = "$target_abs" ] \
        || die "refusing a non-canonical or linked file-removal path: $target"
    case "$target_abs" in "$allowed_root"/*) ;; *) die "refusing file removal outside its intended root: $target" ;; esac
    [ ! -L "$target_abs" ] || die "refusing to remove a linked file: $target"
    [ -e "$target_abs" ] || return 0
    [ -f "$target_abs" ] || die "refusing to remove a non-regular file: $target"
    rm -f -- "$target_abs"
}

safe_remove_fresh_temp_dir() {
    local target="$1" prefix="$2" temp_root target_abs
    temp_root="$(realpath -m -- "${TMPDIR:-/tmp}")"
    target_abs="$(realpath -m -- "$target")"
    [ "$target" = "$target_abs" ] \
        || die "refusing a non-canonical or linked temporary path: $target"
    [ "$(dirname -- "$target_abs")" = "$temp_root" ] \
        || die "refusing to remove a path outside the temporary root: $target"
    [[ "$(basename -- "$target_abs")" == "$prefix"* ]] \
        || die "refusing to remove a temporary path with an unexpected name: $target"
    [ ! -L "$target" ] || die "refusing to remove a linked temporary directory: $target"
    [ -e "$target" ] || return 0
    [ -d "$target" ] || die "refusing to recursively remove a non-directory: $target"
    [ -z "$(find -P "$target" -type l -print -quit)" ] \
        || die "refusing to remove a temporary tree containing links: $target"
    rm -rf -- "$target_abs"
}

info "=== 3D MASTER:2005 Linux Build ==="

# ---- 1. Isolated build environment ----------------------------------------
# A dedicated venv under build/, never the developer's own .venv: a release
# payload must be built from the platform's fully resolved lock file and
# nothing else, so a stray locally-installed package cannot slip in.
step "Step 1: Preparing an isolated build environment..."
command -v python3 >/dev/null || die "python3 not found"
PY_VERSION="$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
python3 - <<'PY' || die "Python 3.11+ is required (see docs/SUPPORTED_PLATFORMS.md, ENV-01)"
import sys
raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)
PY
ok "Python: $PY_VERSION"
safe_remove_repo_dir "$VENV_DIR" "$REPO_ROOT"
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
    safe_remove_repo_dir "$VENV_DIR" "$REPO_ROOT"
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

step "Step 2: Installing locked build dependencies..."
[ -f "$REPO_ROOT/requirements-lock-linux.txt" ] || die "requirements-lock-linux.txt is required"
pip_install -r "$REPO_ROOT/requirements-lock-linux.txt" \
    || die "dependency installation failed"
LOCK_FREEZE="$(pip_freeze)"
AM3D_PHASE10_FREEZE="$LOCK_FREEZE" "$PY" - "$REPO_ROOT/requirements-lock-linux.txt" <<'PY' \
    || die "installed dependency versions do not exactly match requirements-lock-linux.txt"
import os, re, sys
from pathlib import Path
def normalize(lines):
    result = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^;\s]+)", line)
        if not match:
            raise SystemExit(f"unsupported non-pinned lock entry: {line}")
        name = re.sub(r"[-_.]+", "-", match.group(1)).casefold()
        result[name] = match.group(2)
    return result
locked = normalize(Path(sys.argv[1]).read_text(encoding="utf-8").splitlines())
resolved = normalize(os.environ["AM3D_PHASE10_FREEZE"].splitlines())
for bootstrap in ("pip", "setuptools", "wheel"):
    locked.pop(bootstrap, None)
    resolved.pop(bootstrap, None)
if locked != resolved:
    for name in sorted(set(locked) | set(resolved)):
        if locked.get(name) != resolved.get(name):
            print(f"{name}: locked={locked.get(name)} resolved={resolved.get(name)}")
    raise SystemExit(1)
print(f"{len(resolved)} pinned packages exactly match the Linux lock.")
PY
ok "$(printf '%s\n' "$LOCK_FREEZE" | wc -l) resolved packages installed from requirements-lock-linux.txt"

SOURCE_DIGEST_BEFORE="$("$PY" "$REPO_ROOT/scripts/build_input_digest.py" \
    --root "$REPO_ROOT" --digest-only)"
[ "${#SOURCE_DIGEST_BEFORE}" -eq 64 ] || die "could not capture the complete starting build-input digest"
ok "Build input digest: $SOURCE_DIGEST_BEFORE"
"$PY" "$REPO_ROOT/scripts/write_build_identity.py" --root "$REPO_ROOT" \
    --platform linux --digest "$SOURCE_DIGEST_BEFORE" \
    || die "could not write the compact Linux bundle identity"
export AM3D_BUILD_IDENTITY_PATH="$BUILD_DIR/build_identity.json"

# ---- 2. Tests --------------------------------------------------------------
step "Step 3: Running the test suite..."
if [ "$SKIP_TESTS" -eq 1 ]; then
    ok "SKIPPED (--skip-tests): this build is not release-qualified"
else
    QT_QPA_PLATFORM=offscreen "$PY" -m pytest "$REPO_ROOT/am3d" -q --maxfail=1 --tb=short \
        || die "tests failed -- aborting the build"
    ok "All tests passed."
fi

# ---- 3. Freeze both entry points ------------------------------------------
step "Step 4: Building the windowed GUI with PyInstaller..."
safe_remove_repo_dir "$DIST_DIR" "$REPO_ROOT"
safe_remove_repo_dir "$WORK_DIR" "$REPO_ROOT"
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
safe_remove_repo_dir "$RELEASE_DIR" "$REPO_ROOT"
mkdir -p "$RELEASE_DIR"
cp -a "$GUI_DIST/." "$RELEASE_DIR/"
[ -f "$DIST_DIR/am3d-recipe" ] || die "recipe CLI executable not found"
cp -f "$DIST_DIR/am3d-recipe" "$RELEASE_DIR/am3d-recipe"
chmod +x "$RELEASE_DIR/am3d-recipe" "$RELEASE_DIR/$APP_NAME"
cp -a "$REPO_ROOT/assets" "$RELEASE_DIR/examples"
# Finding PKG-04: examples/ carried recipe *outputs* but no recipe, so the
# bundle could not perform the documented "run a recipe with the shipped
# CLI, then open its output in the GUI" journey on its own.
mkdir -p "$RELEASE_DIR/examples/recipes"
cp -f "$REPO_ROOT/docs/recipes/examples/"*.json "$RELEASE_DIR/examples/recipes/"
cp -f "$REPO_ROOT/docs/recipes/recipe-v1.schema.json" \
      "$RELEASE_DIR/examples/recipes/"
cp -f "$REPO_ROOT/README.md" "$RELEASE_DIR/README.txt"
cp -f "$REPO_ROOT/docs/SUPPORTED_PLATFORMS.md" "$RELEASE_DIR/SUPPORTED_PLATFORMS.md"
cp -f "$REPO_ROOT/docs/QUICK_START.md" "$RELEASE_DIR/QUICK_START.md"
cp -f "$REPO_ROOT/docs/CAPABILITY_MATRIX.md" "$RELEASE_DIR/CAPABILITY_MATRIX.md"
cp -f "$REPO_ROOT/docs/USER_GUIDE.md" "$RELEASE_DIR/USER_GUIDE.md"

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
"$PY" "$REPO_ROOT/scripts/write_runtime_licenses.py" --root "$REPO_ROOT" \
    --output "$RELEASE_DIR" --platform linux \
    || die "could not write truthful runtime dependency license notices"
ok "Release staged at: $RELEASE_DIR"

# ---- 6. Packaged smoke test ------------------------------------------------
# Drives the packaged executable through a real workflow via its own
# --smoke-test flag (am3d/ui/smoke.py), and requires every step in the
# manifest to be "ok" -- an exit code alone would let a partially-run smoke
# test ship as silent missing evidence.
step "Step 7: Running the packaged GUI smoke test..."
# The manifest and the files the run produces go to a scratch directory,
# never into the payload: they name absolute build-machine paths, and the
# release folder must contain only what a user is meant to receive.
SMOKE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/am3d_build_smoke_XXXXXX")"
MANIFEST="$SMOKE_DIR/smoke_manifest.json"
set +e
QT_QPA_PLATFORM=offscreen timeout "$SMOKE_TIMEOUT" \
    "$RELEASE_DIR/$APP_NAME" --smoke-test --out "$MANIFEST" \
    > "$SMOKE_DIR/smoke_stdout.txt" 2> "$SMOKE_DIR/smoke_stderr.txt"
SMOKE_RC=$?
set -e
[ "$SMOKE_RC" -eq 124 ] && die "packaged smoke test timed out after ${SMOKE_TIMEOUT}s"
[ -f "$MANIFEST" ] || { cat "$SMOKE_DIR/smoke_stderr.txt" >&2; \
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

step "Step 7a: Running the fixed offline AI acceptance flow..."
AI_TEST_HOST="$SMOKE_DIR/ai-self-test-host"
mkdir -p "$AI_TEST_HOST"
set +e
timeout "$SMOKE_TIMEOUT" "$RELEASE_DIR/$APP_NAME" --ai-self-test \
    --out "$AI_TEST_HOST" > "$SMOKE_DIR/ai_self_test.stdout" \
    2> "$SMOKE_DIR/ai_self_test.stderr"
AI_TEST_RC=$?
set -e
[ "$AI_TEST_RC" -eq 124 ] && die "fixed AI acceptance timed out after ${SMOKE_TIMEOUT}s"
[ "$AI_TEST_RC" -eq 0 ] || { cat "$SMOKE_DIR/ai_self_test.stdout" "$SMOKE_DIR/ai_self_test.stderr" >&2; \
    die "fixed offline AI acceptance failed (exit $AI_TEST_RC)"; }
"$PY" - "$AI_TEST_HOST/phase10-ai-self-test/acceptance.json" <<'PY' \
    || die "fixed AI acceptance did not produce truthful evidence"
import json, sys
report = json.loads(open(sys.argv[1], encoding="utf-8").read())
if (report.get("ok") is not True or report.get("mode") != "frozen"
        or report.get("qualification") != "offline-fixed-mock-transport"
        or report.get("live_network_used") is not False
        or report.get("provider_requests") != 4
        or report.get("credential_sentinel_written") is not False
        or report.get("worker_and_checks") != "passed"
        or report.get("refinement") != "passed"):
    print(json.dumps(report, indent=2)); raise SystemExit(1)
print("  Fixed mock-transport AI acceptance passed; no live provider/network qualification is claimed.")
PY

step "Step 7b: Running a recipe with the packaged CLI..."
"$RELEASE_DIR/am3d-recipe" --recipe "$RELEASE_DIR/examples/recipes/minimal.json" \
    --validate-only || die "packaged recipe CLI could not validate the bundled example"

RELOCATED_RECIPE_OUT="$VERIFY_ROOT/relocated_recipe_output"
mkdir -p "$RELOCATED_RECIPE_OUT"
"$VERIFY_DIR/am3d-recipe" --recipe "$VERIFY_ROOT/standalone_recipe.json" \
    --out "$RELOCATED_RECIPE_OUT" > "$VERIFY_ROOT/relocated_recipe_report.json" \
    || die "relocated recipe CLI could not build the external example"
"$PY" - "$VERIFY_ROOT/relocated_recipe_report.json" "$RELOCATED_RECIPE_OUT" <<'PY' \
    || die "relocated recipe CLI did not produce its promised artifacts"
import json, pathlib, sys
report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
out = pathlib.Path(sys.argv[2])
written = [path for path in out.rglob("*") if path.is_file()]
if report.get("ok") is not True or not written:
    raise SystemExit("relocated CLI reported success without output files")
print(f"  Relocated recipe CLI built {len(written)} artifact(s).")
PY

MALFORMED_RECIPE="$VERIFY_ROOT/malformed_recipe.json"
printf '{"version":1,' > "$MALFORMED_RECIPE"
set +e
"$VERIFY_DIR/am3d-recipe" --recipe "$MALFORMED_RECIPE" --validate-only \
    > "$VERIFY_ROOT/malformed_recipe.stdout" 2> "$VERIFY_ROOT/malformed_recipe.stderr"
MALFORMED_RC=$?
set -e
[ "$MALFORMED_RC" -eq 1 ] || die "relocated recipe CLI did not reject malformed JSON with exit 1"
"$PY" - "$VERIFY_ROOT/malformed_recipe.stdout" <<'PY' \
    || die "relocated recipe CLI did not return its structured parse error"
import json, pathlib, sys
report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
records = report.get("error_records", [])
if (report.get("ok") is not False or not records
        or records[0].get("code") != "recipe_read_error"
        or records[0].get("stage") != "parse"):
    raise SystemExit("relocated CLI parse error record is incomplete")
print("  Relocated recipe CLI returned the structured parse-error record.")
PY

# The packaged error path is part of the agent contract too: a caller must
# receive parseable structured errors and a failing exit code, not a traceback.
INVALID_RECIPE="$SMOKE_DIR/invalid_recipe.json"
cat > "$INVALID_RECIPE" <<'INVALID'
{
  "version": 1,
INVALID
set +e
"$RELEASE_DIR/am3d-recipe" --recipe "$INVALID_RECIPE" --validate-only \
    > "$SMOKE_DIR/invalid_recipe.stdout" \
    2> "$SMOKE_DIR/invalid_recipe.stderr"
INVALID_RC=$?
set -e
[ "$INVALID_RC" -eq 1 ] || die "packaged recipe CLI did not reject malformed JSON with exit 1"
"$PY" - "$SMOKE_DIR/invalid_recipe.stdout" <<'PY' \
    || die "packaged recipe CLI did not return a structured parse error"
import json, sys
report = json.loads(open(sys.argv[1], encoding="utf-8").read())
records = report.get("error_records", [])
if (report.get("ok") is not False or not records
        or records[0].get("code") != "recipe_read_error"
        or records[0].get("stage") != "parse"):
    print(json.dumps(report, indent=2))
    raise SystemExit(1)
print("  Packaged CLI returned its structured parse-error record.")
PY
# Validation alone never touches the geometry, exporter or writer, so the
# bundled recipe is also actually built (journey 6) into a scratch directory
# outside the payload.
RECIPE_OUT="$(realpath -- "$(mktemp -d "${TMPDIR:-/tmp}/am3d_recipe_run_XXXXXX")")"
"$RELEASE_DIR/am3d-recipe" --recipe "$RELEASE_DIR/examples/recipes/minimal.json" \
    --out "$RECIPE_OUT" > "$RECIPE_OUT/report.json" \
    || { cat "$RECIPE_OUT/report.json"; die "packaged recipe CLI failed to build the bundled example"; }
"$PY" - "$RECIPE_OUT" <<'PY' || die "the packaged recipe produced no openable project"
import json, pathlib, sys
out = pathlib.Path(sys.argv[1])
report = json.loads((out / "report.json").read_text())
if report.get("errors"):
    print(json.dumps(report, indent=2)); raise SystemExit(1)
written = [p for p in out.rglob("*") if p.is_file() and p.name != "report.json"]
if not written:
    raise SystemExit("the recipe reported success but wrote nothing")
print(f"  Recipe CLI built {len(written)} file(s) from the bundled example.")
PY
safe_remove_fresh_temp_dir "$RECIPE_OUT" "am3d_recipe_run_"
ok "Recipe CLI validated and built the bundled example recipe."

# ---- 7. Archive, checksum, provenance -------------------------------------
# The payload must contain only what a user receives. A build-machine path
# inside it means a build artefact leaked into the release folder (this
# caught the smoke manifest, which used to be written straight into it).
step "Step 7c: Checking the payload for build-machine references..."
"$PY" "$REPO_ROOT/scripts/audit_build_payload.py" --payload "$RELEASE_DIR" \
    --forbidden-root "$REPO_ROOT" || die "complete release payload path audit failed"

step "Step 7d: Verifying and recording the complete build input set..."
SOURCE_DIGEST_AFTER="$("$PY" "$REPO_ROOT/scripts/build_input_digest.py" \
    --root "$REPO_ROOT" --digest-only)"
[ "$SOURCE_DIGEST_BEFORE" = "$SOURCE_DIGEST_AFTER" ] \
    || die "build inputs changed during the candidate build"
"$PY" "$REPO_ROOT/scripts/build_input_digest.py" --root "$REPO_ROOT" \
    --write-manifest "$REPO_ROOT/release/BUILD_INPUTS-linux.json" \
    --digest-only >/dev/null
ok "Tracked and untracked build inputs match the starting digest."

step "Step 8: Packaging the release archive and checksum..."
VERSION="$("$PY" -c 'import am3d; print(am3d.__version__)')"
ARCHIVE_NAME="3D-MASTER-2005-Beta-$VERSION-linux-x86_64.tar.gz"
ARCHIVE_PATH="$REPO_ROOT/release/$ARCHIVE_NAME"
safe_remove_repo_file "$ARCHIVE_PATH" "$REPO_ROOT"
safe_remove_repo_file "$ARCHIVE_PATH.sha256" "$REPO_ROOT"
# --sort=name and fixed ownership/timestamps keep packaging byte-stable when
# given the same staged folder. PyInstaller may emit different frozen payload
# bytes across separate builds from identical source inputs; the checksum
# below identifies the exact candidate produced by this run.
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
    echo "build inputs sha256: $SOURCE_DIGEST_AFTER"
    echo "input manifest   : release/BUILD_INPUTS-linux.json"
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
VERIFY_ROOT="$(realpath -- "$(mktemp -d "${TMPDIR:-/tmp}/am3d verify éé XXXXXX")")"
cleanup() {
    chmod -R u+w "$VERIFY_ROOT" 2>/dev/null || true
    safe_remove_fresh_temp_dir "$VERIFY_ROOT" "am3d verify éé "
}
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

step "Step 9b: Checking relocated payload write protection..."
READ_ONLY_STATUS="UNPASSED: running as root; root bypasses Unix mode bits"
READ_ONLY_WORKFLOW_STATUS="UNPASSED: payload write denial could not be proven"
if [ "$(id -u)" -ne 0 ]; then
    READ_ONLY_AI_HOST="$VERIFY_ROOT/readonly_ai_self_test_host"
    READ_ONLY_AI_REPORT="$READ_ONLY_AI_HOST/phase10-ai-self-test/acceptance.json"
    [ ! -e "$READ_ONLY_AI_HOST" ] || die "read-only AI acceptance output path already exists"
    mkdir -p -- "$READ_ONLY_AI_HOST"
    READ_ONLY_AI_HOST_REAL="$(realpath -- "$READ_ONLY_AI_HOST")"
    case "$READ_ONLY_AI_HOST_REAL" in
        "$VERIFY_DIR"|"$VERIFY_DIR"/*) die "read-only workflow output must stay outside the payload" ;;
    esac
    if ! chmod -R a-w -- "$VERIFY_DIR"; then
        READ_ONLY_STATUS="UNPASSED: could not apply read-only permissions"
        READ_ONLY_WORKFLOW_STATUS="UNPASSED: write denial was not proven"
        printf '  Relocated payload read-only check: %s\n' "$READ_ONLY_STATUS"
        printf '  Read-only frozen AI workflow: %s\n' "$READ_ONLY_WORKFLOW_STATUS"
        die "could not apply read-only permissions to the relocated payload"
    fi
    set +e
    "$PY" - "$VERIFY_DIR/README.txt" "$VERIFY_DIR/phase10-write-probe.txt" <<'PY'
import pathlib, sys
existing, created = map(pathlib.Path, sys.argv[1:])
def is_denied(operation):
    try:
        operation()
    except PermissionError:
        return True
    return False
if not is_denied(lambda: existing.open("ab").close()):
    raise SystemExit("existing payload file remained writable")
if not is_denied(lambda: created.write_text("probe", encoding="utf-8")):
    raise SystemExit("new payload file could still be created")
print("  Existing-file write and new-file creation were denied.")
PY
    READ_ONLY_RC=$?
    if [ "$READ_ONLY_RC" -eq 0 ]; then
        timeout "$SMOKE_TIMEOUT" "$VERIFY_DIR/$APP_NAME" --ai-self-test \
            --out "$READ_ONLY_AI_HOST" \
            > "$VERIFY_ROOT/readonly_ai_self_test.stdout" \
            2> "$VERIFY_ROOT/readonly_ai_self_test.stderr"
        READ_ONLY_AI_RC=$?
        if [ "$READ_ONLY_AI_RC" -eq 0 ] && [ -f "$READ_ONLY_AI_REPORT" ]; then
            "$PY" - "$READ_ONLY_AI_REPORT" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)
if (report.get("ok") is not True or report.get("mode") != "frozen"
        or report.get("qualification") != "offline-fixed-mock-transport"
        or report.get("live_network_used") is not False
        or report.get("provider_requests") != 4
        or report.get("credential_sentinel_written") is not False
        or report.get("worker_and_checks") != "passed"
        or report.get("refinement") != "passed"):
    raise SystemExit("fixed offline AI report was incomplete")
PY
            READ_ONLY_REPORT_RC=$?
        else
            READ_ONLY_REPORT_RC=1
        fi
        if [ "$READ_ONLY_AI_RC" -eq 0 ] && [ "$READ_ONLY_REPORT_RC" -eq 0 ]; then
            READ_ONLY_WORKFLOW_STATUS="passed"
        else
            READ_ONLY_WORKFLOW_STATUS="UNPASSED: fixed offline AI workflow failed under write-denied payload"
        fi
    else
        READ_ONLY_WORKFLOW_STATUS="UNPASSED: write-denial probe failed before workflow"
    fi
    set -e
    chmod -R u+w -- "$VERIFY_DIR" || die "could not restore temporary extraction write permissions"
    if [ "$READ_ONLY_RC" -ne 0 ]; then
        printf '  Relocated payload read-only check: %s\n' "$READ_ONLY_STATUS"
        printf '  Read-only frozen AI workflow: %s\n' "$READ_ONLY_WORKFLOW_STATUS"
        die "relocated payload write-protection probe failed"
    fi
    READ_ONLY_STATUS="passed"
    printf '  Relocated payload read-only check: %s\n' "$READ_ONLY_STATUS"
    printf '  Read-only frozen AI workflow: %s\n' "$READ_ONLY_WORKFLOW_STATUS"
    [ "$READ_ONLY_WORKFLOW_STATUS" = "passed" ] \
        || die "fixed offline AI workflow failed while the relocated payload was write-denied"
fi

# Recompute after every acceptance and relocation check, then retain the
# complete repository-relative input inventory beside (outside) the payload.
SOURCE_DIGEST_FINAL="$($PY "$REPO_ROOT/scripts/build_input_digest.py" --root "$REPO_ROOT" --digest-only)"
[ "$SOURCE_DIGEST_BEFORE" = "$SOURCE_DIGEST_FINAL" ] \
    || die "build inputs changed during relocated acceptance"
INPUT_MANIFEST="$REPO_ROOT/release/BUILD_INPUTS-linux.json"
"$PY" "$REPO_ROOT/scripts/build_input_digest.py" --root "$REPO_ROOT" \
    --write-manifest "$INPUT_MANIFEST" --digest-only >/dev/null
LOCK_SHA256="$(sha256sum "$REPO_ROOT/requirements-lock-linux.txt" | cut -d' ' -f1)"
cat >> "$REPO_ROOT/release/BUILD_PROVENANCE-linux.txt" <<EOF
relocated CLI    : validation/build/malformed structured error passed
relocated read-only write-denial: $READ_ONLY_STATUS
read-only frozen AI workflow: $READ_ONLY_WORKFLOW_STATUS
build inputs sha256: $SOURCE_DIGEST_FINAL
input manifest   : release/BUILD_INPUTS-linux.json
captured Linux lock sha256: $LOCK_SHA256
qualification   : candidate build evidence only; no live provider, Windows 11, native Mint, or physical GPU claim
candidate status: development candidate evidence; no release, store, or publication qualification
EOF
ok "Final source digest verified after relocation and read-only checks."

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
