#!/usr/bin/env bash
#
# Produce OBJ and GLB with the *frozen* recipe CLI, then read them back
# with verify_exports.py, which shares no code with the exporters.
#
#   docs/evidence/desktop-release/phase-e/export_check.sh \
#       "release/3D MASTER 2005 Beta"
set -euo pipefail

BUNDLE="$(cd "${1:-release/3D MASTER 2005 Beta}" && pwd)"
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/am3d_export_XXXXXX")"

cat > "$OUT/scene.json" <<'JSON'
{
  "version": 1,
  "name": "export_check",
  "materials": [
    {"name": "mat_body", "color": [0.8, 0.2, 0.2], "objects": ["body"]},
    {"name": "mat_base", "color": [0.2, 0.4, 0.9], "objects": ["base"]}
  ],
  "objects": [
    {"name": "body", "primitive": "sphere",
     "params": {"radius": 1.0, "sections": 16, "rings": 8}},
    {"name": "base", "primitive": "box",
     "params": {"width": 2.0, "height": 0.4, "depth": 2.0},
     "transform": [[1,0,0,0],[0,1,0,-1.2],[0,0,1,0],[0,0,0,1]]}
  ],
  "exports": [
    {"format": "obj", "path": "scene"},
    {"format": "glb", "path": "scene"}
  ]
}
JSON

env -i HOME="$HOME" PATH=/usr/local/bin:/usr/bin:/bin LANG="${LANG:-C.UTF-8}" \
    "$BUNDLE/am3d-recipe" --recipe "$OUT/scene.json" --out "$OUT" > "$OUT/report.json"
echo "recipe report: $(head -c 200 "$OUT/report.json")"
echo
/usr/bin/python3 "$HERE/verify_exports.py" "$OUT/scene.obj" "$OUT/scene.glb"
