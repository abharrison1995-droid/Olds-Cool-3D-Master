#!/usr/bin/env bash
#
# Phase-E acceptance run against a *frozen* Linux bundle: no Python, no
# checkout, no virtualenv on the environment. Every launch uses `env -i`
# with only the variables a desktop session genuinely provides, so a bundle
# that secretly needs the build machine's interpreter fails here.
#
#   docs/evidence/desktop-release/phase-e/frozen_acceptance.sh \
#       "release/3D MASTER 2005 Beta"
#
# Prints one line per check and exits non-zero if any failed.
set -uo pipefail

BUNDLE="${1:-release/3D MASTER 2005 Beta}"
BUNDLE="$(cd "$BUNDLE" && pwd)"
APP="$BUNDLE/3D MASTER 2005"
CLI="$BUNDLE/am3d-recipe"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/am3d_accept_XXXXXX")"
PASS=0; FAIL=0

pass() { printf '  [PASS] %s\n' "$*"; PASS=$((PASS+1)); }
fail() { printf '  [FAIL] %s\n' "$*"; FAIL=$((FAIL+1)); }
note() { printf '  [note] %s\n' "$*"; }
check() { if [ "$1" -eq 0 ]; then pass "$2"; else fail "$2${3:+ -- $3}"; fi; }

# Variables a real desktop session provides. Nothing Python-related is in
# this list, and PATH deliberately excludes any virtualenv.
session_env() {
    env -i \
        HOME="$HOME" USER="${USER:-$(id -un)}" \
        PATH=/usr/local/bin:/usr/bin:/bin \
        XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" \
        WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-}" DISPLAY="${DISPLAY:-}" \
        XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" \
        XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-}" \
        LANG="${LANG:-C.UTF-8}" \
        "$@"
}

echo "=== Frozen bundle acceptance: $BUNDLE"
echo "=== $(date -Is)  host: $(uname -srmo)"
echo

echo "1. The bundle carries its own runtime"
if ldd "$APP" 2>/dev/null | grep -qi "libpython"; then
    note "$(ldd "$APP" | grep -i libpython | head -1)"
fi
session_env "$APP" --smoke-test --out "$WORK/smoke.json" \
    > "$WORK/smoke.stdout" 2> "$WORK/smoke.stderr"
rc=$?
check $rc "packaged smoke test (all workflows) exits 0" "rc=$rc"
if [ -s "$WORK/smoke.json" ]; then
    python3 - "$WORK/smoke.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
bad = [s["name"] for s in m["steps"] if s["status"] != "ok"]
print(f"  [note] smoke steps: {len(m['steps'])}, not ok: {bad or 'none'}")
parity = m.get("artifacts", {}).get("gpu_parity")
print(f"  [note] gpu/software parity: {parity}")
PY
else
    fail "smoke manifest was not written"
fi
echo

echo "2. Graphics routes (each launched for 10 s, then TERM)"
run_route() {
    local label="$1"; shift
    ( session_env "$@" "$APP" > "$WORK/$label.out" 2>&1 & echo $! > "$WORK/$label.pid" )
    sleep 10
    local pid; pid="$(cat "$WORK/$label.pid")"
    if kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
        pass "$label: still running after 10 s, exited on TERM"
    else
        fail "$label: exited early"
        note "$(tail -3 "$WORK/$label.out" | tr '\n' ' ')"
    fi
}
run_route "native-session"
run_route "xcb-xwayland" QT_QPA_PLATFORM=xcb
run_route "forced-software" LIBGL_ALWAYS_SOFTWARE=1
echo

echo "3. Recipe CLI (journey 6)"
session_env "$CLI" --recipe "$BUNDLE/examples/recipes/minimal.json" \
    --out "$WORK/recipe_out" > "$WORK/recipe.json" 2>&1
check $? "bundled recipe builds with the packaged CLI"
[ -n "$(ls -A "$WORK/recipe_out" 2>/dev/null)" ] \
    && pass "the recipe wrote output files" || fail "the recipe wrote nothing"
session_env "$CLI" --recipe "$WORK/does-not-exist.json" \
    > "$WORK/recipe_fail.json" 2>&1
[ $? -ne 0 ] && pass "a failing recipe exits non-zero" \
             || fail "a failing recipe still exited 0"
grep -q "recipe_read_error" "$WORK/recipe_fail.json" \
    && pass "the failure names a machine-readable error code" \
    || fail "the failure report has no error record"
echo

echo "4. Unicode and space in the working paths"
UNI="$WORK/prosjekt æøå 走 test"
mkdir -p "$UNI"
cp "$BUNDLE/examples/recipes/minimal.json" "$UNI/oppskrift æøå.json"
session_env "$CLI" --recipe "$UNI/oppskrift æøå.json" --out "$UNI/ut" \
    > "$UNI/report.json" 2>&1
check $? "the CLI handles non-ASCII recipe and output paths"
echo

echo "5. Read-only installation directory"
RO="$WORK/readonly"
cp -a "$BUNDLE" "$RO"
chmod -R a-w "$RO"
session_env "$RO/$(basename "$BUNDLE")/am3d-recipe" 2>/dev/null --help >/dev/null 2>&1 \
    || true
session_env "$RO/am3d-recipe" --recipe "$RO/examples/recipes/minimal.json" \
    --out "$WORK/ro_out" > "$WORK/ro.json" 2>&1
check $? "the CLI runs from a read-only install, writing elsewhere"
session_env "$RO/3D MASTER 2005" --smoke-test --out "$WORK/ro_smoke.json" \
    > "$WORK/ro_smoke.log" 2>&1
check $? "the GUI's full workflow run works from a read-only install"
chmod -R u+w "$RO"
echo

echo "6. Relocation to a path with spaces and non-ASCII characters"
MOVED="$WORK/flyttet æøå/3D MASTER 2005 Beta"
mkdir -p "$(dirname "$MOVED")"
cp -a "$BUNDLE" "$MOVED"
session_env "$MOVED/3D MASTER 2005" --smoke-test --out "$WORK/moved.json" \
    > "$WORK/moved.log" 2>&1
check $? "the relocated bundle passes the full workflow run"
echo

echo "7. No source-tree references in the payload"
if grep -rlF "$(cd "$BUNDLE/.." && pwd)" "$BUNDLE" --include='*.py' \
        --include='*.json' --include='*.sh' 2>/dev/null | head -3 | grep -q .; then
    fail "the payload references its build location"
else
    pass "no build-location references in the payload's text files"
fi
echo

echo "8. The pose on screen reaches the exported file"
# Read the two OBJs the packaged smoke run exported at both ends of an
# action, with a parser that shares no code with the exporter.
python3 - "$WORK/smoke.json" <<'POSE'
import json, sys

def verts(path):
    out = []
    with open(path) as fh:
        for line in fh:
            p = line.split()
            if p and p[0] == "v":
                out.append(tuple(float(x) for x in p[1:4]))
    return out

m = json.load(open(sys.argv[1]))
art = m.get("artifacts", {}).get("posed_export")
if not art:
    print("  [FAIL] the smoke run recorded no posed export"); raise SystemExit(1)
a, b = verts(art["rest"]), verts(art["bent"])
if len(a) != len(b) or not a:
    print(f"  [FAIL] posed exports disagree on vertex count: {len(a)} vs {len(b)}")
    raise SystemExit(1)
shift = max(max(abs(x - y) for x, y in zip(p, q)) for p, q in zip(a, b))
if shift < 1e-3:
    print("  [FAIL] both poses exported identical geometry (bind pose written)")
    raise SystemExit(1)
print(f"  [PASS] the two exported poses differ by {shift:.3f} over "
      f"{len(a)} vertices, read back independently")
POSE
if [ $? -eq 0 ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); fi
echo

echo "$PASS passed, $FAIL failed"
echo "artifacts under $WORK"
[ "$FAIL" -eq 0 ]
