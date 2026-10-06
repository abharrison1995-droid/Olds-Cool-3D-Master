"""Real-process local generation and parent-boundary regressions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from .contracts import GenerationStatus
from .runner import GenerationRunner
from .storage import GenerationStore


def _recipe(exports=None):
    value = {
        "version": 1,
        "name": "worker_smoke",
        "objects": [{"name": "shape", "primitive": "box"}],
    }
    if exports:
        value["exports"] = exports
    return value


def _finish(runner: GenerationRunner, timeout=45):
    deadline = time.monotonic() + timeout
    while runner.running and time.monotonic() < deadline:
        runner.poll()
        time.sleep(0.025)
    if runner.running:
        runner.cancel()
        raise AssertionError("generation worker did not finish before test deadline")
    return runner.poll() or runner.last_result


def test_real_worker_pipeline_publishes_checked_immutable_snapshot(tmp_path):
    store = GenerationStore(tmp_path / "user data with spaces – £")
    runner = GenerationRunner(store, timeout_seconds=45)
    run_id = runner.start(_recipe())
    result = _finish(runner)

    assert result.run_id == run_id
    assert result.status is GenerationStatus.COMPLETE
    assert {check.name for check in result.checks} >= {
        "native_project_reopen", "renderable_geometry", "finite_geometry",
        "valid_indices", "scene_bounds", "whole_scene_preview"}
    assert all(check.ok for check in result.checks)
    run_dir = store.generations / run_id
    assert (run_dir / "record.json").is_file()
    assert (run_dir / "recipe.json").is_file()
    assert (run_dir / "checks.json").is_file()
    assert (run_dir / "preview.png").is_file()
    assert (run_dir / "project.am3d").is_file()
    assert result.record_path == f"generations/{run_id}/record.json"

    original = (run_dir / "project.am3d").read_bytes()
    original_hash = hashlib.sha256(original).hexdigest()
    writable = runner.create_writable_project_copy(run_id)
    from am3d.core.script import Session
    session = Session()
    session.load_project(str(writable))
    session.project.name = "edited working copy"
    session.save_project(str(writable))
    assert hashlib.sha256((run_dir / "project.am3d").read_bytes()).hexdigest() == original_hash
    assert hashlib.sha256(writable.read_bytes()).hexdigest() != original_hash
    assert (run_dir / "record.json").stat().st_mode & 0o222 == 0


def test_worker_modules_remain_qt_independent():
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; import am3d.ai.checks, am3d.ai.runner, "
         "am3d.ai.storage, am3d.ai.worker; "
         "assert not any(name.startswith('PySide6') for name in sys.modules)"],
        check=False, capture_output=True, text=True)
    assert probe.returncode == 0, probe.stderr


def test_real_worker_independently_checks_requested_exports(tmp_path):
    exports = [
        {"format": "obj", "path": "model.obj"},
        {"format": "glb", "path": "model.glb"},
        {"format": "spritesheet", "path": "sheet.png",
         "params": {"views": 2, "size": 32}},
    ]
    store = GenerationStore(tmp_path / "user-data")
    runner = GenerationRunner(store, timeout_seconds=45)
    run_id = runner.start(_recipe(exports))
    result = _finish(runner)

    assert result.status is GenerationStatus.COMPLETE, result.error_records
    assert any(check.name.startswith("export_") for check in result.checks)
    assert all(check.ok for check in result.checks)
    published = store.generations / run_id
    assert (published / "exports/model.obj").is_file()
    assert (published / "exports/model.glb").is_file()
    assert (published / "exports/sheet_shape.png").is_file()


def test_policy_failure_is_a_failed_record_and_never_a_success(tmp_path):
    store = GenerationStore(tmp_path / "user-data")
    runner = GenerationRunner(store, timeout_seconds=5)
    run_id = runner.start({
        **_recipe(), "materials": [{"name": "m", "texture": "/private/file.png"}]})
    result = runner.poll()

    assert result is not None
    assert result.status is GenerationStatus.FAILED
    assert not result.ok
    assert any(item["code"] == "texture_path_forbidden"
               for item in result.error_records)
    assert not (store.generations / run_id).exists()
    record = json.loads((store.failures / run_id / "record.json").read_text())
    assert record["status"] == "failed"


def _stub_worker(tmp_path, mode):
    script = tmp_path / f"worker_{mode}.py"
    script.write_text(
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "result = Path(sys.argv[1])\n"
        f"mode = {mode!r}\n"
        "if mode == 'hang': time.sleep(60)\n"
        "elif mode == 'crash': os._exit(23)\n"
        "elif mode == 'malformed': result.write_text('{', encoding='utf-8')\n"
        "elif mode == 'stale':\n"
        "  value = {'schema_version':1,'run_id':'f'*32,'status':'failed',"
        "'artifacts':[],'checks':[],'warnings':[],'error_records':[],"
        "'elapsed_seconds':0.0,'record_path':None}\n"
        "  result.write_text(json.dumps(value), encoding='utf-8')\n"
        "elif mode == 'env':\n"
        "  result.write_text('credential' if os.getenv('M2_WORKER_SECRET') else 'clean',"
        " encoding='utf-8')\n"
        "sys.exit(1 if mode == 'stale' else 0)\n",
        encoding="utf-8")
    return script


def _use_stub(monkeypatch, runner, tmp_path, mode):
    script = _stub_worker(tmp_path, mode)
    monkeypatch.setattr(runner, "_command",
                        lambda attempt: [sys.executable, str(script),
                                         str(attempt.result_path)])


@pytest.mark.parametrize("mode, expected", [
    ("crash", "worker_crash"),
    ("malformed", "malformed_worker_response"),
    ("stale", "stale_worker_result"),
])
def test_crash_malformed_and_stale_responses_are_structured_failures(
        tmp_path, monkeypatch, mode, expected):
    runner = GenerationRunner(GenerationStore(tmp_path / "data"), timeout_seconds=5)
    _use_stub(monkeypatch, runner, tmp_path, mode)
    run_id = runner.start(_recipe())
    result = _finish(runner)

    assert result.run_id == run_id
    assert result.status is GenerationStatus.FAILED
    assert result.error_records[0]["code"] == expected
    assert not (runner.store.generations / run_id).exists()


@pytest.mark.parametrize("end", ["cancel", "timeout"])
def test_parent_can_terminate_worker_for_cancel_and_deadline(
        tmp_path, monkeypatch, end):
    limit = 10 if end == "cancel" else 0.05
    runner = GenerationRunner(GenerationStore(tmp_path / "data"), timeout_seconds=limit)
    _use_stub(monkeypatch, runner, tmp_path, "hang")
    run_id = runner.start(_recipe())
    if end == "cancel":
        deadline = time.monotonic() + 5
        while runner._process is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runner.cancel()
    result = _finish(runner, timeout=5)

    assert result.run_id == run_id
    assert result.status is (GenerationStatus.CANCELLED if end == "cancel"
                             else GenerationStatus.TIMED_OUT)
    assert not (runner.store.generations / run_id).exists()
    assert not runner.running


def test_worker_environment_drops_credential_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("M2_WORKER_SECRET", "must-not-cross")
    runner = GenerationRunner(GenerationStore(tmp_path / "data"), timeout_seconds=5)
    script = _stub_worker(tmp_path, "env")
    result_file = tmp_path / "environment-result.txt"
    monkeypatch.setattr(runner, "_command",
                        lambda attempt: [sys.executable, str(script), str(result_file)])
    runner.start(_recipe())
    result = _finish(runner)
    assert result.status is GenerationStatus.FAILED
    assert result_file.read_text(encoding="utf-8") == "clean"


def test_previous_success_becomes_non_openable_after_newer_run(tmp_path):
    store = GenerationStore(tmp_path / "user-data")
    runner = GenerationRunner(store, timeout_seconds=45)
    first_id = runner.start(_recipe())
    first = _finish(runner)
    assert first.ok
    second_id = runner.start({
        **_recipe(), "materials": [{"name": "m", "texture": "/private/file.png"}]})
    assert second_id != first_id
    failure = runner.poll()
    assert failure is not None and not failure.ok
    with pytest.raises(ValueError, match="latest successful"):
        runner.create_writable_project_copy(first_id)
