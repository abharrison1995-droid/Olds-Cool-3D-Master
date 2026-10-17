"""Generate the registry-derived capability summary in the agent guide."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
GUIDE = ROOT / "docs/recipes/EXTERNAL_AGENT_GUIDE.md"
START = "<!-- capability-registry:start -->"
END = "<!-- capability-registry:end -->"


def _default(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      default=list)


def _parameter(spec):
    if spec.has_default:
        detail = f"default `{_default(spec.default)}`"
    else:
        detail = "required" if spec.required else "optional"
    limits = []
    if spec.minimum is not None:
        limits.append(f"min {spec.minimum:g}")
    if spec.maximum is not None:
        limits.append(f"max {spec.maximum:g}")
    if spec.enum:
        limits.append("one of " + ", ".join(f"`{v}`" for v in spec.enum))
    if spec.length:
        limits.append(f"length {spec.length[0]}–{spec.length[1]}")
    suffix = f"; {', '.join(limits)}" if limits else ""
    return f"`{spec.type}` ({detail}{suffix})"


def render_registry_table() -> str:
    from am3d.recipes.capabilities import CAPABILITIES

    categories = (
        ("primitive", "Primitives"),
        ("pattern", "Material patterns"),
        ("graph_node", "Material graph nodes"),
        ("action_kind", "Action kinds"),
        ("export_format", "Export formats"),
        ("channel_property", "Channel properties"),
        ("interpolation", "Interpolation modes"),
    )
    lines = [
        "## Capability Registry (generated)",
        "",
        "Validation accepts the parameter names and types listed here. Limits",
        "apply during validation; `(hidden)` entries remain readable for legacy",
        "recipes but are not offered to AI generation.",
        "",
    ]
    for category, title in categories:
        lines.extend([f"### {title}", "", "| Name | Parameters | AI | Description |", "| --- | --- | :---: | --- |"])
        for (kind, _), cap in CAPABILITIES.items():
            if kind != category:
                continue
            params = "; ".join(
                f"`{name}` {_parameter(spec)}"
                for name, spec in cap.params.items()) or "—"
            visible = "yes" if cap.model_visible else "hidden"
            desc = f"{cap.description} Cost: {cap.cost_hint}"
            lines.append(f"| `{cap.name}` | {params} | {visible} | {desc} |")
        lines.append("")
    return "\n".join(lines).rstrip()


def updated_guide(source: str) -> str:
    generated = render_registry_table()
    block = f"{START}\n{generated}\n{END}"
    if START in source and END in source:
        before, rest = source.split(START, 1)
        _, after = rest.split(END, 1)
        return before + block + after
    anchor = "## 6. External Agent Error-Correction Loop"
    if anchor not in source:
        raise ValueError(f"guide missing insertion anchor {anchor!r}")
    before, after = source.split(anchor, 1)
    return before + block + "\n\n" + anchor + after


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    source = GUIDE.read_text(encoding="utf-8")
    target = updated_guide(source)
    if args.check:
        if target != source:
            print("EXTERNAL_AGENT_GUIDE.md capability table is stale", file=sys.stderr)
            return 1
        return 0
    GUIDE.write_text(target, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
