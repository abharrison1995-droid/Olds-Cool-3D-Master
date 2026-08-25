"""Tests for the material node graph."""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.material_graph import NODE_TYPES, MaterialGraph, Node


def test_all_node_types_registered():
    for t in ("source", "solid", "checker", "gradient", "noise", "bricks",
              "mix", "noise_overlay", "tint"):
        assert t in NODE_TYPES


def test_empty_graph_is_neutral_grey():
    tex = MaterialGraph().evaluate(size=16)
    assert tex.shape == (16, 16, 4)
    assert np.allclose(tex[0, 0], [0.8, 0.8, 0.8, 1.0])


def test_generator_only_graph():
    g = MaterialGraph.from_dicts([{"type": "checker",
                                   "params": {"cells": 2}}])
    assert g.validate() == []
    tex = g.evaluate(size=32)
    assert tex.shape == (32, 32, 4)
    # checker produced two distinct colours
    assert len(np.unique(tex[..., 0].round(3))) >= 2


def test_chained_generators_and_tint():
    g = MaterialGraph.from_dicts([
        {"type": "bricks", "params": {"rows": 4}},
        {"type": "tint", "params": {"color": [0.5, 1.0, 0.5]}},
    ])
    assert g.validate() == []
    plain = MaterialGraph.from_dicts(
        [{"type": "bricks", "params": {"rows": 4}}]).evaluate(size=32)
    tinted = g.evaluate(size=32)
    # tint halves the red channel but keeps it nonzero
    assert tinted[..., 0].max() < plain[..., 0].max()
    assert tinted[..., 0].max() > 0


def test_noise_overlay_adds_grain():
    base = MaterialGraph.from_dicts(
        [{"type": "solid", "params": {"color": [1, 1, 1]}}])
    grained = MaterialGraph.from_dicts([
        {"type": "solid", "params": {"color": [1, 1, 1]}},
        {"type": "noise_overlay", "params": {"amount": 0.5}},
    ])
    a = base.evaluate(size=32)
    b = grained.evaluate(size=32)
    assert not np.allclose(a, b)


def test_mix_node_blends_two_maps():
    node = Node(type="mix", params={"factor": 0.25})
    white = np.ones((8, 8, 4))
    black = np.zeros((8, 8, 4))
    out = node.evaluate({"a": white, "b": black}, size=8)
    assert np.allclose(out[0, 0], [0.75, 0.75, 0.75, 1.0])


def test_unknown_node_type_rejected():
    with pytest.raises(ValueError, match="unknown node type"):
        Node(type="quantum_diffusion").evaluate({}, size=8)


def test_source_without_upstream_rejected():
    g = MaterialGraph.from_dicts([{"type": "tint"}])
    problems = g.validate()
    assert problems and "requires an upstream" in problems[0]
    with pytest.raises(ValueError, match="requires an upstream|upstream"):
        g.evaluate(size=8)


def test_from_dicts_accepts_single_dict():
    g = MaterialGraph.from_dicts({"type": "noise"})
    assert len(g.nodes) == 1
    assert g.nodes[0].type == "noise"


def test_bad_params_raise_actionable_error():
    # Extra/unknown params must fail with a message an LLM can act on.
    g = MaterialGraph.from_dicts([
        {"type": "gradient", "params": {"top": [1, 1, 1], "mood": "dramatic"}},
    ])
    with pytest.raises(ValueError, match="bad params"):
        g.evaluate(size=16)