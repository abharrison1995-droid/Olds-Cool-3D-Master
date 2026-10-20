"""Process-boundary, path-audit and lifecycle tests for the AI worker."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time
import traceback

import pytest

from am3d.ai.contracts import CancellationToken
from am3d.ai import worker
from am3d.core.paths import extended_io_path
from am3d.core.serializer import load_project
from am3d.core.script import Session


def _recipe(*, exports=None):
    name = "箱 / Ω — front panel"
    return {
        "name": "Unicode prop",
        "objects": [{"name": name, "primitive": "box"}],
        "materials": [{"name": "paint", "pattern": "checker",
                       "params": {"cells": 4, "size": 32},
                       "objects": [name]}],
        "exports": exports or [
            {"format": "obj", "path": "model.obj"},
            {"format": "spritesheet", "path": "sheet.png",
             "params": {"views": 4, "size": 32}},
        ],
    }


def _deadline(seconds=180):
    return time.monotonic() + seconds


def _test_command(script):
    def command(input_path, result_path):
        return ([sys.executable, "-c", script, str(input_path), str(result_path)], None)
    return command


def _bounded_tree_summary(root: Path, *, limit: int = 128) -> dict:
    """Return test-only relative-path diagnostics without following links."""
    entries = []
    scan_errors = []

    def onerror(exc):
        scan_errors.append(type(exc).__name__)

    try:
        exists = root.exists() or root.is_symlink()
        if not exists:
            return {"exists": False, "entries": [], "scan_errors": []}
        for current, dirs, files in os.walk(
                root, topdown=True, followlinks=False, onerror=onerror):
            dirs.sort()
            files.sort()
            parent = Path(current)
            for name in dirs + files:
                candidate = parent / name
                relative = candidate.relative_to(root).as_posix()
                try:
                    info = candidate.lstat()
                except OSError as exc:
                    entries.append({"path": relative,
                                    "stat_error": type(exc).__name__})
                else:
                    entries.append({
                        "path": relative,
                        "kind": "directory" if stat.S_ISDIR(info.st_mode) else "file",
                        "size_bytes": info.st_size,
                        "symlink": stat.S_ISLNK(info.st_mode),
                    })
                if len(entries) >= limit:
                    return {"exists": True, "entries": entries,
                            "scan_errors": scan_errors, "truncated": True}
        return {"exists": True, "entries": entries,
                "scan_errors": scan_errors, "truncated": False}
    except Exception as exc:
        return {"exists": root.exists(), "entries": entries,
                "scan_errors": scan_errors + [type(exc).__name__],
                "truncated": False}


def _worker_failure_context(result: dict, output_root: Path) -> dict:
    return {"result": result, "root_tree": _bounded_tree_summary(output_root)}


def test_valid_worker_is_private_native_reopens_and_derived_paths_are_opaque(
        tmp_path, monkeypatch):
    output = tmp_path / "worker-output"
    outside = tmp_path / "sentinel.txt"
    outside.write_text("keep me", encoding="utf-8")
    active = Session()
    active.new_project("untouched editor")
    active.create_object("editor-only")

    parent_audit_failures = []
    original_verify_tree = worker._verify_tree
    child_protocol = []
    parent_protocol_errors = []
    original_strict_json = worker._strict_json

    def record_parent_audit_failure(root, **kwargs):
        try:
            return original_verify_tree(root, **kwargs)
        except Exception as exc:
            detail = {"phase": "live" if kwargs.get("include_scratch") else "final",
                      "exception_type": type(exc).__name__}
            frames = traceback.extract_tb(exc.__traceback__)
            inner = next((frame for frame in reversed(frames)
                          if frame.filename.endswith("worker.py")), None)
            if inner is not None:
                detail["location"] = {"function": inner.name, "line": inner.lineno}
            reason = str(exc)[:160]
            for known_path in (str(root), str(Path(os.path.realpath(root)))):
                reason = reason.replace(known_path, "<audited-root>")
            detail["reason"] = reason
            if isinstance(exc, worker.PolicyError):
                detail["code"] = exc.code
                detail["reason"] = worker._safe_error(exc.code, "worker")["message"]
            parent_audit_failures.append({
                **detail,
            })
            raise

    def record_parent_protocol(payload):
        try:
            value = original_strict_json(payload)
        except Exception as exc:
            parent_protocol_errors.append(type(exc).__name__)
            raise
        if isinstance(value, dict) and "status" in value:
            manifest = value.get("manifest")
            child_protocol.append({
                "status": value.get("status"),
                "protocol_version": value.get("protocol_version"),
                "attempt_id_type": type(value.get("attempt_id")).__name__,
                "checks_status": value.get("checks_status"),
                "manifest_count": len(manifest) if isinstance(manifest, list) else None,
            })
        return value

    monkeypatch.setattr(worker, "_verify_tree", record_parent_audit_failure)
    monkeypatch.setattr(worker, "_strict_json", record_parent_protocol)
    result = worker.run_worker(_recipe(), output, _deadline(), CancellationToken())

    assert result["status"] == "execution_ok", json.dumps({
        "worker_failure": _worker_failure_context(result, output),
        "parent_audit_failures": parent_audit_failures,
        "parent_child_protocol": child_protocol,
        "parent_protocol_parse_errors": parent_protocol_errors,
    }, ensure_ascii=False, sort_keys=True)
    assert result["ok"] is True
    assert result["checks_status"] == "not_requested"
    paths = [entry["path"] for entry in result["manifest"]]
    assert any(path.endswith("/project.am3d") for path in paths)
    assert all(Path(path).name.isascii() for path in paths)
    assert not any("箱" in path or "front panel" in path for path in paths)
    native = output / next(path for path in paths if path.endswith("/project.am3d"))
    loaded = load_project(str(native))
    assert "箱 / Ω — front panel" in loaded.objects
    assert list(active.project.objects) == ["editor-only"]
    assert outside.read_text(encoding="utf-8") == "keep me"


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-path IO regression")
def test_worker_succeeds_with_deep_host_output_root(tmp_path):
    deep = Path(extended_io_path(tmp_path))
    for index in range(6):
        deep = deep / (f"level-{index}-" + "x" * 36)
        deep.mkdir()
    output = deep / "worker-output"
    assert len(str(output / ("attempt-" + "0" * 32) / "tmp" / "am3d_stage_12345678" / "export_001.am3d")) > 260

    result = worker.run_worker(
        {"name": "Deep host path", "objects": [{"name": "box", "primitive": "box"}]},
        output, _deadline(), CancellationToken())

    assert result["status"] == "execution_ok", result
    assert any(entry["path"].endswith("/project.am3d") for entry in result["manifest"])


@pytest.mark.parametrize("unsafe_path", [
    "C:\\outside\\file.obj", "D:relative.obj", "\\\\server\\share\\x.obj",
    "../outside.obj", "folder/../../outside.obj", "/tmp/out.obj",
])
def test_policy_denial_does_not_create_output_root_or_mutate_outside_file(tmp_path, unsafe_path):
    outside = tmp_path / "protected.txt"
    outside.write_text("original", encoding="utf-8")
    output = tmp_path / "must-not-exist"
    raw = _recipe(exports=[{"format": "obj", "path": unsafe_path}])

    result = worker.run_worker(raw, output, _deadline(), CancellationToken())

    assert result["status"] == "policy_error"
    assert result["error_records"][0]["code"] == "output_path_denied"
    assert not output.exists()
    assert outside.read_text(encoding="utf-8") == "original"


def test_nested_resource_request_never_reads_host_file(tmp_path):
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"sentinel")
    raw = _recipe()
    raw["materials"][0]["graph"] = [{"type": "noise", "params": {
        "image_path": str(secret),
    }}]
    output = tmp_path / "out"

    result = worker.run_worker(raw, output, _deadline(), CancellationToken())

    assert result["status"] == "policy_error"
    assert result["error_records"][0]["code"] == "resource_access_denied"
    assert not output.exists()
    assert secret.read_bytes() == b"sentinel"


def test_unsupported_checker_protocol_fields_fail_before_worker_start(tmp_path):
    output = tmp_path / "no-worker"
    result = worker.run_worker(
        {"name": "box", "objects": [{"name": "box", "primitive": "box"}]},
        output, _deadline(), CancellationToken(),
        check_options={"command": "must not be accepted"})

    assert result["status"] == "policy_error"
    assert result["error_records"][0]["code"] == "worker_protocol"
    assert not output.exists()


def test_check_options_accept_validated_100k_metadata_within_protocol_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "_worker_command", _test_command("raise SystemExit(0)"))
    result = worker.run_worker(
        {"name": "box", "objects": [{"name": "box", "primitive": "box"}]},
        tmp_path / "accepted", _deadline(), CancellationToken(),
        check_options={"brief": "x" * (100 * 1024)})

    # The test child intentionally omits the result file. Reaching that
    # protocol failure proves the large but valid check request was accepted.
    assert result["status"] == "worker_error"
    assert result["error_records"][0]["code"] == "worker_died"


def test_check_options_over_256k_are_rejected_before_output_creation(tmp_path):
    output = tmp_path / "too-large"
    result = worker.run_worker(
        {"name": "box", "objects": [{"name": "box", "primitive": "box"}]},
        output, _deadline(), CancellationToken(),
        check_options={"brief": "x" * (256 * 1024 + 1)})

    assert result["status"] == "policy_error"
    assert result["error_records"][0]["code"] == "response_too_large"
    assert not output.exists()


@pytest.mark.parametrize(("request_kind", "expected_code"), [
    ("oversized", "response_too_large"),
    ("truncated", "worker_protocol"),
])
def test_internal_child_returns_bounded_early_protocol_error_without_output_root(
        tmp_path, monkeypatch, request_kind, expected_code):
    cwd = tmp_path / "fixed-worker-cwd"
    cwd.mkdir()
    input_path = cwd / ".ai_worker_input.json"
    result_path = cwd / ".ai_worker_result.json"
    output_root = tmp_path / ("attempt-" + "a" * 32)
    request = {
        "protocol_version": 1,
        "recipe": {"name": "unused", "objects": []},
        "output_root": str(output_root),
    }
    payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
    if request_kind == "oversized":
        payload = (payload[:-1] + b',"padding":"'
                   + b"x" * (worker._MAX_INPUT_BYTES + 1) + b'"}')
        assert len(payload) > worker._MAX_INPUT_BYTES
    else:
        payload = payload[:-1]
    input_path.write_bytes(payload)
    monkeypatch.chdir(cwd)

    exit_code = worker.internal_worker_main([str(input_path), str(result_path)])

    assert exit_code == 2
    response_bytes = result_path.read_bytes()
    assert len(response_bytes) <= worker._MAX_RESULT_BYTES
    response = json.loads(response_bytes)
    assert response["status"] == "policy_error"
    assert response["ok"] is False
    assert response["error_records"][0]["code"] == expected_code
    assert response["attempt_id"] is None
    assert str(output_root) not in response_bytes.decode("utf-8")
    assert not output_root.exists()


def test_output_root_symlink_is_rejected_without_following_it(tmp_path):
    target = tmp_path / "real-output"
    target.mkdir()
    sentinel = target / "sentinel.txt"
    sentinel.write_text("untouched", encoding="utf-8")
    link = tmp_path / "linked-output"
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlink creation is unavailable: {exc}")

    result = worker.run_worker(_recipe(), link, _deadline(), CancellationToken())

    assert result["status"] == "worker_error"
    assert result["error_records"][0]["code"] == "unsafe_output_tree"
    assert list(target.iterdir()) == [sentinel]


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junctions are platform-specific")
def test_output_root_junction_is_rejected_without_following_it(tmp_path):
    target = tmp_path / "junction-target"
    target.mkdir()
    sentinel = target / "sentinel.txt"
    sentinel.write_text("untouched", encoding="utf-8")
    link = tmp_path / "junction-output"
    # cmd.exe is used only for the fixed Windows `mklink /J` builtin. Skip
    # unusual temp paths with shell metacharacters rather than interpolate
    # them into a command string.
    if any(char in str(link) + str(target) for char in "&|<>^%!\n\r"):
        pytest.skip("temporary path contains a cmd.exe metacharacter")
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    cmd = Path(system_root) / "System32" / "cmd.exe"
    created = subprocess.run(
        [str(cmd), "/d", "/c", "mklink", "/J", str(link), str(target)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=5.0, check=False)
    if created.returncode != 0 or not link.exists():
        pytest.skip("directory junction creation is unavailable")
    try:
        result = worker.run_worker(_recipe(), link, _deadline(), CancellationToken())
        assert result["status"] == "worker_error"
        assert result["error_records"][0]["code"] == "unsafe_output_tree"
        assert list(target.iterdir()) == [sentinel]
    finally:
        # Remove only the junction entry. os.rmdir on a Windows junction
        # removes the reparse point and never recursively visits its target.
        os.rmdir(link)


def test_final_tree_audit_rejects_portable_filename_collisions(tmp_path, monkeypatch):
    root = tmp_path / "attempt"
    root.mkdir()
    (root / "first.png").write_bytes(b"1")
    (root / "SECOND.png").write_bytes(b"2")
    monkeypatch.setattr(worker.os, "walk", lambda *a, **kw: iter([
        (str(root), [], ["SECOND.png", "second.PNG"]),
    ]))
    with pytest.raises(worker.PolicyError, match="collide"):
        worker._verify_tree(root)


@pytest.mark.skipif(os.name != "nt", reason="Windows realpath prefix race regression")
def test_tree_audit_normalizes_transient_extended_realpath_prefix(tmp_path, monkeypatch):
    root = tmp_path / "attempt"
    root.mkdir()
    child = root / "preview.png"
    child.write_bytes(b"image")
    ordinary_realpath = worker.os.path.realpath
    child_key = worker.os.path.normcase(os.fspath(child))

    def transient_extended_realpath(path):
        resolved = ordinary_realpath(path)
        if worker.os.path.normcase(os.fspath(path)) == child_key:
            # Models ntpath.realpath retaining \\\\?\\ when its second
            # final-path probe loses a file that existed for the first probe.
            return extended_io_path(resolved)
        return resolved

    ordinary_root = ordinary_realpath(root)
    extended_child = transient_extended_realpath(child)
    with pytest.raises(ValueError, match="drive"):
        worker.os.path.commonpath((ordinary_root, extended_child))

    monkeypatch.setattr(worker.os.path, "realpath", transient_extended_realpath)
    manifest, total = worker._verify_tree(root)

    assert manifest == [{"path": "preview.png", "format": "png", "size_bytes": 5}]
    assert total == 5


@pytest.mark.parametrize("token", ["a1b2c3d4", "a1_b2c3d"])
def test_live_tree_audit_counts_fixed_native_atomic_write_temp_only(tmp_path, token):
    root = tmp_path / "attempt"
    root.mkdir()
    native_stage = root / f".am3d_tmp_{token}"
    native_stage.write_bytes(b"staged native project")

    manifest, live_bytes = worker._verify_tree(root, include_scratch=True)

    assert manifest == []
    assert live_bytes == native_stage.stat().st_size
    with pytest.raises(worker.PolicyError, match="unapproved"):
        worker._verify_tree(root)

    native_stage.unlink()
    (root / ".arbitrary_tmp_file").write_bytes(b"not the serializer's fixed temp name")
    with pytest.raises(worker.PolicyError, match="unapproved"):
        worker._verify_tree(root, include_scratch=True)


@pytest.mark.parametrize("filename", ["vanished.png", "vanished.tmp"])
def test_live_tree_audit_tolerates_vanished_private_staging_entries(
        tmp_path, monkeypatch, filename):
    root = tmp_path / "attempt"
    scratch = root / "tmp"
    scratch.mkdir(parents=True)
    candidate = scratch / filename
    candidate.write_bytes(b"temporary")

    def walk_with_vanishing_file(*_args, **_kwargs):
        yield str(root), ["tmp"], []
        candidate.unlink()
        yield str(scratch), [], [filename]

    monkeypatch.setattr(worker.os, "walk", walk_with_vanishing_file)
    # Live polling tolerates a staging file that disappeared after enumeration.
    worker._verify_tree(root, include_protocol=True, include_scratch=True)

    candidate.write_bytes(b"temporary")
    if filename.endswith(".png"):
        with pytest.raises(FileNotFoundError):
            worker._verify_tree(root)
    else:
        # The strict final audit ignores non-deliverable files in the private
        # scratch directory; it never includes them in the output manifest.
        worker._verify_tree(root)


def test_final_tree_audit_rejects_symlink(tmp_path):
    root = tmp_path / "attempt"
    root.mkdir()

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    try:
        os.symlink(outside, root / "linked.png")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")
    with pytest.raises(worker.PolicyError, match="link"):
        worker._verify_tree(root)


@pytest.mark.parametrize("report,status,checks_status,ok", [
    ({"status": "passed", "ok": True, "checks": []}, "checked_ok", "passed", True),
    ({"status": "failed", "ok": False, "checks": []}, "check_failed", "failed", False),
    ({"status": "passed", "ok": False, "checks": []}, "check_failed", "failed", False),
])
def test_checked_status_requires_both_success_fields(tmp_path, monkeypatch,
                                                     report, status, checks_status, ok):
    script = (
        "import sys, types; "
        "from am3d.ai import worker; "
        "m=types.ModuleType('am3d.ai.checks'); "
        f"m.check_artifacts=lambda *a, **k: {report!r}; "
        "sys.modules['am3d.ai.checks']=m; "
        "raise SystemExit(worker.internal_worker_main())"
    )
    monkeypatch.setattr(worker, "_worker_command", _test_command(script))
    result = worker.run_worker(
        {"name": "box", "objects": [{"name": "box", "primitive": "box"}]},
        tmp_path / "out", _deadline(), CancellationToken(),
        check_options={"brief": "Make a box"})

    assert result["status"] == status
    assert result["checks_status"] == checks_status
    assert result["ok"] is ok
    assert result["check_report"] == report
    if status == "check_failed":
        assert result["manifest"]
        assert result["error_records"][0]["stage"] == "check"


def test_cancelled_worker_is_terminated_promptly_and_never_successful(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "_worker_command", _test_command("import time; time.sleep(60)"))
    token = CancellationToken()
    results = {}

    thread = threading.Thread(target=lambda: results.setdefault(
        "result", worker.run_worker(
            {"name": "box", "objects": [{"name": "box", "primitive": "box"}]},
            tmp_path / "cancel", _deadline(), token)))
    thread.start()
    time.sleep(.4)
    cancelled_at = time.monotonic()
    token.cancel()
    thread.join(timeout=3.0)

    assert not thread.is_alive()
    assert time.monotonic() - cancelled_at <= 3.0
    assert results["result"]["status"] == "cancelled"
    assert results["result"]["ok"] is False


@pytest.mark.skipif(os.name != "nt", reason="Windows child-tree guarantee uses a Job Object or taskkill /T")
def test_windows_cancel_terminates_descendant_processes(tmp_path, monkeypatch):
    pid_file = "tmp\\descendant.pid"
    script = (
        "import subprocess,sys,time; "
        "time.sleep(.25); "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        f"open({pid_file!r},'w').write(str(child.pid)); "
        "time.sleep(60)"
    )
    observed = {}
    def command(input_path, result_path):
        observed["workspace"] = Path(input_path).parent
        return ([sys.executable, "-c", script, str(input_path), str(result_path)], None)
    monkeypatch.setattr(worker, "_worker_command", command)
    token = CancellationToken()
    results = {}
    output = tmp_path / "tree-cancel"
    thread = threading.Thread(target=lambda: results.setdefault(
        "result", worker.run_worker(
            {"name": "box", "objects": [{"name": "box", "primitive": "box"}]},
            output, _deadline(), token)))
    thread.start()
    pid_path = None
    wait_deadline = time.monotonic() + 8
    while time.monotonic() < wait_deadline:
        workspace = observed.get("workspace")
        candidates = list((workspace / "tmp").glob("descendant.pid")) if workspace else []
        if candidates:
            pid_path = candidates[0]
            break
        time.sleep(.05)
    assert pid_path is not None
    descendant_pid = int(pid_path.read_text(encoding="ascii"))
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    process_handle = kernel.OpenProcess(0x00100000, False, descendant_pid)  # SYNCHRONIZE
    assert process_handle
    token.cancel()
    thread.join(timeout=3.0)
    try:
        assert not thread.is_alive()
        assert results["result"]["status"] == "cancelled"
        assert kernel.WaitForSingleObject(process_handle, 2500) == 0
    finally:
        kernel.CloseHandle(process_handle)


def test_deadline_kills_a_hung_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "_worker_command", _test_command("import time; time.sleep(60)"))
    started = time.monotonic()
    result = worker.run_worker(
        {"name": "box", "objects": [{"name": "box", "primitive": "box"}]},
        tmp_path / "timeout", _deadline(.6), CancellationToken())

    assert result["status"] == "timed_out"
    assert result["ok"] is False
    assert time.monotonic() - started < 4


def test_dead_worker_without_protocol_result_is_not_successful(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "_worker_command", _test_command("raise SystemExit(0)"))
    result = worker.run_worker(
        {"name": "box", "objects": [{"name": "box", "primitive": "box"}]},
        tmp_path / "died", _deadline(), CancellationToken())

    assert result["status"] == "worker_error"
    assert result["error_records"][0]["code"] == "worker_died"
    assert result["ok"] is False


def test_minimal_environment_does_not_copy_provider_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-never-copy")
    monkeypatch.setenv("HOME", str(tmp_path))
    env = worker._minimal_environment(tmp_path / "private-temp")

    assert "OPENAI_API_KEY" not in env
    assert "HOME" not in env
    assert env["TEMP"] == extended_io_path(tmp_path / "private-temp")
