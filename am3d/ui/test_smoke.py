"""Source-level regression test for am3d.ui.smoke.

This exercises the same code path build_windows.ps1 drives against the
packaged .exe, so a regression here is caught by the ordinary pytest
suite instead of only surfacing on the next real Windows build. It
cannot catch packaging-specific failures (e.g. a frozen-build import
bug) -- those need an actual PyInstaller build, which is what the build
script's own smoke-test invocation is for.
"""

from __future__ import annotations

import json

from am3d.ui.smoke import STEPS, run_smoke_test
from am3d.ui.app import main


def test_smoke_test_passes_every_step(tmp_path):
    manifest = run_smoke_test(tmp_path)

    failed = [s for s in manifest["steps"] if s["status"] != "ok"]
    assert not failed, f"smoke steps did not pass: {failed}"
    assert manifest["ok"] is True
    assert [s["name"] for s in manifest["steps"]] == STEPS
    assert manifest["artifacts"]["rendered_objects"] >= 2
    assert manifest["artifacts"]["export_size_bytes"] > 0


def test_smoke_test_manifest_records_a_failing_step(tmp_path, monkeypatch):
    """A step that raises must be recorded as failed, not silently
    swallowed, and must stop the run rather than limping into steps that
    assume state the failed step never set up."""
    import am3d.ui.operators as operators

    def _boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(operators, "CreatePrimitiveCommand", _boom)

    manifest = run_smoke_test(tmp_path)

    assert manifest["ok"] is False
    by_name = {s["name"]: s for s in manifest["steps"]}
    assert by_name["primitive_and_profile_creation"]["status"] == "failed"
    assert "boom" in by_name["primitive_and_profile_creation"]["error"]
    assert by_name["blank_startup"]["status"] == "ok"
    assert by_name["new_project"]["status"] == "ok"
    # Steps after the failure must never have run.
    assert by_name["material_reference"]["status"] == "not_run"
    assert by_name["transformed_export"]["status"] == "not_run"


def test_main_smoke_test_writes_manifest_to_out_path(tmp_path):
    """--smoke-test --out PATH must write the manifest to PATH (not just
    stdout), including when PATH's directory name contains spaces -- the
    exact case that broke silently under Start-Process -ArgumentList
    quoting in build_windows.ps1 (see its Step 7 comment)."""
    out_dir = tmp_path / "release dir with spaces"
    out_dir.mkdir()
    out_path = out_dir / "smoke_manifest.json"

    rc = main(["am3d", "--smoke-test", "--out", str(out_path)])

    assert rc == 0
    manifest = json.loads(out_path.read_text(encoding="utf-8"))
    assert manifest["ok"] is True
    assert [s["name"] for s in manifest["steps"]] == STEPS


def test_main_out_without_value_errors_cleanly(tmp_path, capsys):
    """A malformed ``--out`` with no following PATH must fail fast with a
    clear message instead of an IndexError traceback -- this can otherwise
    happen before QApplication is even constructed, and (in the packaged
    windowed/console=False build) with no attached console to show it in."""
    rc = main(["am3d", "--smoke-test", "--out"])

    assert rc == 2
    assert "--out" in capsys.readouterr().err
