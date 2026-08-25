"""Smoke tests for the scriptable facade (Agent 2 data/scripting layer)."""

from __future__ import annotations

import numpy as np

import am3d
from am3d.core import script
from am3d.core.project import Project


def test_package_version():
    assert isinstance(am3d.__version__, str)


def test_script_session_headless_creation():
    s = script.Session()
    obj = s.create_object("carrier")
    spl = s.add_spline("carrier", [(0, 0, 0), (2, 0, 0), (4, 1, 0)], name="spine")
    assert obj.name == "carrier"
    assert spl.name == "spine"
    assert len(spl.cps) == 3


def test_script_lathe_and_extrude_patches():
    s = script.Session()
    s.create_object("vase")
    s.add_spline("vase", [(0.5, 0, 0), (1.0, 1, 0), (0.6, 2, 0)], name="profile")
    p = s.lathe_spline("vase", "profile", axis="y", sections=12)
    assert p.interior.shape == (12, 3, 3)
    e = s.extrude_spline("vase", "profile", height=3.0, rings=5)
    assert e.interior.shape == (5, 3, 3)


def test_script_error_unknown_object():
    s = script.Session()
    try:
        s.add_spline("missing", [(0, 0, 0)])
    except script.ScriptingError:
        return
    raise AssertionError("expected ScriptingError")


def test_bones_registered():
    s = script.Session()
    s.create_object("avatar")
    b = s.add_bone("avatar", "upper", (0, 0, 0), (0, 1, 0))
    assert b.name == "upper"
    assert b.tail.tolist() == [0, 1, 0]


def test_project_mode_switch():
    p = Project()
    p.set_mode("choreography")
    assert p.mode == "choreography"


def test_action_library_reuse_and_compat(tmp_path):
    s = script.Session()
    # build a walk action
    walk = s.create_action("walk", duration=1.0)
    ch = walk.add_channel("hip", "translate")
    ch.add_key(0.0, [0, 0, 0])
    ch.add_key(1.0, [0.4, 0, 0])

    # a compatible character
    s.create_object("hero")
    b = s.add_bone("hero", "hip", (0, 0, 0), (0, 1, 0))
    walk.signature = (f"{b.name}->root",)
    applied = s.apply_action_to_character("walk", "hero")
    assert applied.name == "walk"

    # a non-compatible character must raise
    s.create_object("other")
    s.add_bone("other", "tail", (0, 0, 0), (0, 1, 0))
    try:
        s.apply_action_to_character("walk", "other")
    except script.ScriptingError:
        pass
    else:
        raise AssertionError("expected ScriptingError for incompatible skeleton")

    # save/load the reusable asset and drop it on a fresh session
    path = str(tmp_path / "walk.am3a")
    s.save_action_file("walk", path)
    s2 = script.Session()
    loaded = s2.load_action_file(path)
    assert loaded.name == "walk"
    assert np.allclose(loaded.sample(0.5)["hip"]["translate"], [0.2, 0, 0], atol=1e-6)
# ---------------------------------------------------------------------------
# Thread-isolated default session (Phase 3A fix)
# ---------------------------------------------------------------------------
import threading

from am3d.core.script import reset_default


def test_thread_isolated_default_sessions():
    results = {}

    def worker(name, key):
        reset_default()
        script.create_object(name)
        results[key] = [script.get_object(name).name]

    t1 = threading.Thread(target=worker, args=("alpha", 1))
    t2 = threading.Thread(target=worker, args=("beta", 2))
    t1.start(); t1.join()
    t2.start(); t2.join()

    assert results[1] == ["alpha"]
    assert results[2] == ["beta"]


def test_reset_default_gives_fresh_project():
    script.reset_default()
    script.create_object("stale")
    session = script.reset_default()
    assert "stale" not in session.project.objects
