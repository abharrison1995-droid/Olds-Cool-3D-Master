"""Build the compact provider schema from the complete recipe contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FULL_SCHEMA = ROOT / "docs/recipes/recipe-v1.schema.json"
PROVIDER_SCHEMA = ROOT / "docs/recipes/recipe-v1.provider.schema.json"
sys.path.insert(0, str(ROOT))


def render() -> str:
    from am3d.recipes.capabilities import CAPABILITIES

    schema = json.loads(FULL_SCHEMA.read_text(encoding="utf-8"))
    enum = schema["$defs"]["graphNode"]["properties"]["type"]["enum"]
    visible = {cap.name for (kind, _), cap in CAPABILITIES.items()
               if kind == "graph_node" and cap.model_visible}
    schema["$defs"]["graphNode"]["properties"]["type"]["enum"] = [
        name for name in enum if name in visible]
    schema["$id"] = str(schema["$id"]).rstrip("/") + "/provider"
    schema.pop("title", None)
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":")) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    expected = render()
    if args.check:
        if not PROVIDER_SCHEMA.exists() or PROVIDER_SCHEMA.read_text(
                encoding="utf-8") != expected:
            print("provider schema is stale", file=sys.stderr)
            return 1
        return 0
    PROVIDER_SCHEMA.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
