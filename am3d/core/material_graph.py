"""Composable material node graph (Material Mode).

A tiny dataflow system: nodes take input maps (float RGBA arrays) and
produce output maps; a :class:`MaterialGraph` chains them and evaluates to
a final texture.  Built for LLM/agent authoring — a graph is plain data::

    g = MaterialGraph.from_dicts([
        {"type": "bricks", "params": {"rows": 8}},
        {"type": "noise_overlay", "params": {"amount": 0.15}},
    ])
    tex = g.evaluate(size=256)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def _as_rgba(x) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 2:
        x = np.repeat(x[..., None], 3, axis=2)
    if x.shape[-1] == 3:
        a = np.ones(x.shape[:2])[..., None]
        x = np.concatenate([x, a], axis=-1)
    return np.clip(x, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Node implementations: (inputs: dict[str, ndarray], params) -> RGBA map
# ---------------------------------------------------------------------------
def _node_source(inputs, params):
    return _as_rgba(inputs["in"])


def _node_bricks(inputs, params):
    from ..renderer.materials import bricks
    return bricks(**params)


def _node_checker(inputs, params):
    from ..renderer.materials import checkerboard
    return checkerboard(**params)


def _node_gradient(inputs, params):
    from ..renderer.materials import gradient
    return gradient(**params)


def _node_noise(inputs, params):
    from ..renderer.materials import noise
    return noise(**params)


def _node_solid(inputs, params):
    from ..renderer.materials import solid
    return solid(**params)


def _node_mix(inputs, params):
    """Linear blend of two inputs by ``factor`` (0 = A, 1 = B)."""
    a = _as_rgba(inputs["a"])
    b = _as_rgba(inputs["b"])
    f = float(params.get("factor", 0.5))
    out = a * (1 - f) + b * f
    out[..., 3] = np.maximum(a[..., 3], b[..., 3])
    return out


def _node_noise_overlay(inputs, params):
    """Modulate the base input with grain."""
    from ..renderer.materials import noise
    base = _as_rgba(inputs["in"])
    amount = float(params.get("amount", 0.15))
    grain = noise(seed=int(params.get("seed", 7)),
                  size=base.shape[0],
                  octaves=params.get("octaves", 3),
                  base=(1.0, 1.0, 1.0), contrast=1.0)
    shade = 1.0 - amount + amount * 2.0 * grain[..., :3]
    out = base.copy()
    out[..., :3] = np.clip(base[..., :3] * shade, 0.0, 1.0)
    return out


def _node_tint(inputs, params):
    """Multiply the input by a flat colour."""
    base = _as_rgba(inputs["in"])
    tint = np.asarray(params.get("color", (1, 1, 1))[:3], dtype=np.float64)
    out = base.copy()
    out[..., :3] = np.clip(base[..., :3] * tint[None, None, :], 0.0, 1.0)
    return out


NODE_TYPES = {
    "source": _node_source,
    "solid": _node_solid,
    "checker": _node_checker,
    "gradient": _node_gradient,
    "noise": _node_noise,
    "bricks": _node_bricks,
    "mix": _node_mix,
    "noise_overlay": _node_noise_overlay,
    "tint": _node_tint,
}

# Which named inputs each node type consumes.
NODE_INPUTS = {
    "source": ["in"],
    "solid": [],
    "checker": [],
    "gradient": [],
    "noise": [],
    "bricks": [],
    "mix": ["a", "b"],
    "noise_overlay": ["in"],
    "tint": ["in"],
}

@dataclass
class Node:
    """One node in a material graph."""

    type: str
    params: dict = field(default_factory=dict)

    def evaluate(self, inputs: dict, size: int) -> np.ndarray:
        if self.type not in NODE_TYPES:
            raise ValueError(f"unknown node type {self.type!r} "
                             f"(choose from {sorted(NODE_TYPES)})")
        missing = [i for i in NODE_INPUTS[self.type] if i not in inputs]
        if missing:
            raise ValueError(f"node {self.type!r} missing inputs {missing}")
        if self.type in ("solid", "checker", "gradient", "noise", "bricks"):
            params = dict(self.params)
            params.setdefault("size", size)
            try:
                result = NODE_TYPES[self.type](inputs, params)
            except TypeError as exc:
                raise ValueError(
                    f"node {self.type!r} got bad params "
                    f"{self.params!r}: {exc}") from exc
        else:
            result = NODE_TYPES[self.type](inputs, self.params)
        result = _as_rgba(result)
        if result.shape[0] != size or result.shape[1] != size:
            from ..renderer.materials import _resize
            result = _resize(result, size, size)
        return result


@dataclass
class MaterialGraph:
    """A linear chain of nodes; each feeds the next's 'in' slot."""

    nodes: list = field(default_factory=list)

    @staticmethod
    def from_dicts(specs) -> "MaterialGraph":
        """Build from plain dicts (the LLM-facing shape)."""
        if isinstance(specs, dict):
            specs = [specs]
        return MaterialGraph(nodes=[
            Node(type=s.get("type", "source"),
                 params=dict(s.get("params", {})))
            for s in specs or []
        ])

    def evaluate(self, size: int = 256) -> np.ndarray:
        """Run the chain; returns the final ``(size, size, 4)`` map.

        An empty graph yields a neutral grey card.  A chain starting with a
        generator node (bricks/noise/...) needs no upstream source; a chain
        starting with 'tint'/'noise_overlay'/'source' does.
        """
        if not self.nodes:
            from ..renderer.materials import solid
            return solid((0.8, 0.8, 0.8), size=size)

        first = self.nodes[0]
        if NODE_INPUTS[first.type]:      # needs an upstream source
            raise ValueError(
                f"graph starts with {first.type!r}, which requires an "
                f"upstream generator node (e.g. bricks/noise/checker)")

        current = None
        for i, node in enumerate(self.nodes):
            needed = NODE_INPUTS[node.type]
            inputs = {}
            for slot in needed:
                if slot == "a" and current is not None:
                    inputs[slot] = current
                elif slot == "b":
                    # 'mix' takes the previous as A and the node's own
                    # params-driven pattern as B is unsupported in chains;
                    # treat B as the previous too unless it's a generator.
                    if current is None:
                        raise ValueError(
                            f"node {i} ({node.type!r}): no upstream source")
                    inputs[slot] = current
                elif current is None:
                    raise ValueError(
                        f"node {i} ({node.type!r}): no upstream source")
                else:
                    inputs[slot] = current
            current = node.evaluate(inputs, size)
        return current

    def validate(self) -> list:
        """Human-readable problems ([] = the graph is well-formed)."""
        problems = []
        if self.nodes and NODE_INPUTS.get(self.nodes[0].type):
            problems.append(
                f"first node {self.nodes[0].type!r} requires an upstream "
                f"generator (bricks/noise/checker/gradient/solid)")
        for i, node in enumerate(self.nodes):
            if node.type not in NODE_TYPES:
                problems.append(f"node {i}: unknown type {node.type!r}")
        return problems