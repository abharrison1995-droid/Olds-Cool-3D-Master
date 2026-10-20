"""Focused tests for the V1 Phase10 packaging preparation helpers."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_input_digest_covers_new_untracked_v1_inputs_but_excludes_identity(tmp_path, monkeypatch):
    digest = _load("phase10_digest", ROOT / "scripts" / "build_input_digest.py")
    monkeypatch.setattr(digest, "_tracked_paths", lambda _root: set())
    for directory in digest.INPUT_DIRS:
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    before = digest.build_manifest(tmp_path)["build_input_digest"]

    samples = {
        "am3d/runtime.py": b"runtime",
        "am3d/recipes/schema.json": b"schema",
        "assets/example.bin": b"asset",
        "benchmarks/cases.json": b"benchmark",
        "scripts/new_builder.ps1": b"builder",
        "am3d.spec": b"spec",
        "requirements-lock-windows.txt": b"name==1.0\n",
        "docs/USER_GUIDE.md": b"guide",
    }
    for relative, content in samples.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    generated = tmp_path / "am3d" / "build_identity.json"
    generated.write_text('{"source_sha256":"ignored"}', encoding="utf-8")
    cache = tmp_path / "am3d" / "__pycache__"
    cache.mkdir()
    (cache / "module.pyc").write_bytes(b"ignored cache")

    manifest = digest.build_manifest(tmp_path)
    assert manifest["build_input_digest"] != before
    included = {item["path"]: item for item in manifest["inputs"]}
    assert set(samples) <= set(included)
    assert "am3d/build_identity.json" not in included
    assert "am3d/__pycache__/module.pyc" not in included
    assert all(included[path]["git_state"] == "untracked" for path in samples)


def test_input_digest_fails_closed_when_git_is_missing(tmp_path, monkeypatch, capsys):
    digest = _load("phase10_digest_missing_git", ROOT / "scripts" / "build_input_digest.py")

    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git executable detail must not escape")

    monkeypatch.setattr(digest.subprocess, "run", missing_git)
    with pytest.raises(digest.InputInventoryError, match="could not enumerate tracked build inputs"):
        digest.build_manifest(tmp_path)

    with pytest.raises(SystemExit) as exc:
        digest.main(["--root", str(tmp_path), "--digest-only"])
    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert "could not enumerate tracked build inputs" in error
    assert "executable detail" not in error


def test_input_digest_rejects_a_non_checkout_instead_of_using_an_empty_tracked_set(tmp_path):
    digest = _load("phase10_digest_non_checkout", ROOT / "scripts" / "build_input_digest.py")
    with pytest.raises(digest.InputInventoryError, match="working checkout with Git available"):
        digest._tracked_paths(tmp_path)


def test_input_digest_records_deleted_tracked_inputs(tmp_path):
    digest = _load("phase10_digest_deleted_tracked", ROOT / "scripts" / "build_input_digest.py")
    subprocess.run(["git", "init", "--quiet", os.fspath(tmp_path)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    tracked = tmp_path / "am3d" / "removed_runtime.py"
    tracked.parent.mkdir(parents=True, exist_ok=True)
    for directory in digest.INPUT_DIRS:
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    tracked.write_text("runtime input", encoding="utf-8")
    subprocess.run(["git", "-C", os.fspath(tmp_path), "add", "--", "am3d/removed_runtime.py"],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    present_digest = digest.build_manifest(tmp_path)["build_input_digest"]
    tracked.unlink()
    manifest = digest.build_manifest(tmp_path)
    entries = {item["path"]: item for item in manifest["inputs"]}
    assert entries["am3d/removed_runtime.py"] == {
        "path": "am3d/removed_runtime.py", "kind": "missing", "git_state": "tracked"}
    assert manifest["build_input_digest"] != present_digest


def test_input_digest_records_symlink_target_without_following(tmp_path, monkeypatch):
    digest = _load("phase10_digest_symlink", ROOT / "scripts" / "build_input_digest.py")
    monkeypatch.setattr(digest, "_tracked_paths", lambda _root: set())
    (tmp_path / "am3d").mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("outside bytes", encoding="utf-8")
    link = tmp_path / "am3d" / "link.py"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("file symlink creation is unavailable")
    manifest = digest.build_manifest(tmp_path)
    entry = next(item for item in manifest["inputs"] if item["path"] == "am3d/link.py")
    assert entry["kind"] == "symlink"
    assert entry["target_kind"] == "absolute"
    assert entry["target_sha256"] == hashlib.sha256(os.fsencode(os.readlink(link))).hexdigest()
    assert "sha256" not in entry


def test_compact_identity_writer_and_runtime_reader_use_whitelist(tmp_path, monkeypatch):
    writer = _load("phase10_identity_writer", ROOT / "scripts" / "write_build_identity.py")
    package = tmp_path / "am3d"
    (package / "ai").mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
    (package / "ai" / "records.py").write_text(
        '_CAPABILITY_VERSION = "recipe-v1-policy-v1-prompt-v1"\n', encoding="utf-8")
    digest = "a" * 64
    assert writer.main(["--root", str(tmp_path), "--platform", "windows",
                        "--digest", digest]) == 0
    generated = json.loads((tmp_path / "build" / "windows" / "build_identity.json").read_text())
    assert set(generated) == {"version", "build_id", "capability_version", "source_sha256"}
    assert generated["source_sha256"] == digest

    from am3d.ai import records
    (package / "build_identity.json").write_text(json.dumps(generated), encoding="utf-8")
    monkeypatch.setattr(records, "__file__", str(package / "ai" / "records.py"))
    monkeypatch.setattr("am3d.__version__", "1.2.3")
    runtime_identity = records.application_identity()
    assert runtime_identity == {
        "version": "1.2.3",
        "build_id": f"build-input-sha256:{digest}",
        "capability_version": "recipe-v1-policy-v1-prompt-v1",
    }


def test_payload_audit_scans_all_bytes_and_rejects_payload_links(tmp_path):
    audit = _load("phase10_payload_audit", ROOT / "scripts" / "audit_build_payload.py")
    payload = tmp_path / "bundle"
    payload.mkdir()
    root_token = os.fspath(tmp_path / "private-build-root")
    (payload / "large.bin").write_bytes(b"x" * (5 * 1024 * 1024) + root_token.encode())
    assert audit.audit(payload, Path(root_token)) == ["large.bin"]
    (payload / "large.bin").write_bytes(b"x" * (5 * 1024 * 1024))
    assert audit.audit(payload, Path(root_token)) == []

    alias = tmp_path / "bundle-alias"
    try:
        alias.symlink_to(payload, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable")
    with pytest.raises(ValueError, match="link or junction"):
        audit.audit(alias, Path(root_token))


def test_runtime_license_writer_rejects_linked_release_root(tmp_path):
    licenses = _load("phase10_runtime_licenses", ROOT / "scripts" / "write_runtime_licenses.py")
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside-release"
    outside.mkdir()
    try:
        (root / "release").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable")
    with pytest.raises(ValueError, match="release directory is linked"):
        licenses.write_licenses(root, outside, "windows")


def test_runtime_license_writer_copies_exact_interpreter_and_pyinstaller_notices(tmp_path):
    licenses = _load("phase10_bundled_component_notices",
                     ROOT / "scripts" / "write_runtime_licenses.py")
    sources = licenses._bundled_component_sources("windows")
    root = tmp_path / "repo"
    output = root / "release" / "candidate"
    licenses_root = output / "LICENSES"
    licenses_root.mkdir(parents=True)

    manifest = licenses.write_licenses(root, output, "windows")
    components = manifest["bundled_components"]
    assert len(components) == 2
    assert manifest["format_version"] == 2
    by_name = {item["name"]: item for item in components}
    for source in sources:
        component = by_name[source["name"]]
        copied = licenses_root / Path(component["license_file"])
        assert copied.read_bytes() == source["source"].read_bytes()
        assert hashlib.sha256(copied.read_bytes()).hexdigest() == component["sha256"]
        assert str(ROOT) not in json.dumps(component)

    pyinstaller_notice = licenses_root / "pyinstaller" / "PyInstaller-COPYING.txt"
    text = pyinstaller_notice.read_text(encoding="utf-8")
    assert "Bootloader Exception" in text
    assert "Run-time Hooks" in text
    notice_text = (licenses_root / "NOTICE.txt").read_text(encoding="utf-8")
    assert "PyInstaller is a build tool" in notice_text
    runtime_names = {item["name"].casefold() for item in manifest["packages"]}
    assert not runtime_names.intersection({"pytest", "pygments", "packaging", "setuptools"})


@pytest.mark.parametrize("platform", ["windows", "linux"])
def test_runtime_license_names_cover_keyring_resolved_requirement_metadata(platform):
    from importlib import metadata
    from packaging.markers import default_environment
    from packaging.requirements import Requirement

    licenses = _load("phase10_runtime_license_closure", ROOT / "scripts" / "write_runtime_licenses.py")
    names = {re.sub(r"[-_.]+", "-", name).casefold()
             for name in licenses.runtime_distribution_names(platform)}
    environment = default_environment()
    environment["sys_platform"] = "win32" if platform == "windows" else "linux"
    environment["os_name"] = "nt" if platform == "windows" else "posix"
    environment["platform_system"] = "Windows" if platform == "windows" else "Linux"

    # keyring selects an OS backend through these runtime requirements; the
    # shared jaraco dependencies also bring in more-itertools. Compare the
    # helper's actual notice set with installed wheel metadata so a platform
    # split cannot silently drop the Windows runtime closure again.
    for distribution_name in ("keyring", "jaraco.classes", "jaraco.context",
                              "jaraco.functools"):
        required = metadata.requires(distribution_name) or []
        for raw_requirement in required:
            requirement = Requirement(raw_requirement)
            if requirement.marker and not requirement.marker.evaluate(environment):
                continue
            canonical = re.sub(r"[-_.]+", "-", requirement.name).casefold()
            assert canonical in names, (
                f"{platform} runtime notices omit {distribution_name}'s "
                f"active dependency {requirement.name}"
            )


def test_selftest_dispatch_precedes_qt_and_unknown_flags_have_no_side_effect(tmp_path):
    source = (ROOT / "am3d" / "ui" / "__main__.py").read_text(encoding="utf-8")
    dispatch = source.index('sys.argv[1] == "--ai-self-test"')
    qt_import = source.index("from am3d.ui.app import main")
    assert dispatch < qt_import

    module = _load("phase10_frozen_acceptance", ROOT / "am3d" / "ai" / "frozen_acceptance.py")
    output = tmp_path / "not-created"
    with pytest.raises(SystemExit) as exc:
        module.main(["--out", str(output), "--module", "arbitrary"])
    assert exc.value.code == 2
    assert not output.exists()


def test_source_acceptance_runs_fixed_mock_flow_before_qt(tmp_path):
    output = tmp_path / "selftest-output"
    blocker_dir = tmp_path / "no-qt"
    blocker_dir.mkdir()
    (blocker_dir / "sitecustomize.py").write_text(
        "import importlib.abc, sys\n"
        "class _BlockQt(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == 'PySide6' or fullname.startswith('PySide6.'):\n"
        "            raise RuntimeError('Qt import attempted before fixed dispatch')\n"
        "sys.meta_path.insert(0, _BlockQt())\n",
        encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [os.fspath(blocker_dir), os.fspath(ROOT), env.get("PYTHONPATH", "")])
    command = [sys.executable, "-m", "am3d.ui", "--ai-self-test",
               "--out", os.fspath(output)]
    result = subprocess.run(command, cwd=ROOT, env=env, text=True,
                            capture_output=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    report_path = output / "phase10-ai-self-test" / "acceptance.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["mode"] == "source"
    assert report["qualification"] == "offline-fixed-mock-transport"
    assert report["live_network_used"] is False
    assert report["provider_requests"] == 4
    assert report["qt_loaded_before_dispatch"] is False
    assert report["worker_and_checks"] == "passed"
    assert report["history_store"] == "passed"
    assert report["refinement"] == "passed"
    assert report["export_checks"]["obj_parse"] == "passed"
    assert report["export_checks"]["glb_parse"] == "passed"
    assert report["export_checks"]["spritesheet_png"] == "passed"
    assert report["export_checks"]["preview_png"] == "passed"
    assert report["export_checks"]["preview_nonblank"] is True
    assert report["credential_sentinel_written"] is False


def test_credential_store_check_uses_owned_alias_and_verifies_cleanup(tmp_path, monkeypatch):
    module = _load("phase10_credential_acceptance", ROOT / "am3d" / "ai" / "frozen_acceptance.py")
    from am3d.ai import credentials

    class PasswordDeleteError(Exception):
        pass

    class Backend:
        def __init__(self):
            self.values = {}
            self.calls = []

        def get_password(self, service, alias):
            self.calls.append(("get", service, alias))
            return self.values.get((service, alias))

        def set_password(self, service, alias, value):
            self.calls.append(("set", service, alias))
            self.values[(service, alias)] = value

        def delete_password(self, service, alias):
            self.calls.append(("delete", service, alias))
            key = (service, alias)
            if key not in self.values:
                raise PasswordDeleteError("private fake backend message")
            del self.values[key]

    backend = Backend()
    monkeypatch.setattr(credentials, "_make_approved_backend", lambda _platform: backend)
    report = module.run_credential_store_check(str(tmp_path))

    assert report["ok"] is True
    assert report["mode"] == "source"
    assert report["platform"] == ("windows" if sys.platform.startswith("win") else "linux")
    assert report["crud_status"] == "passed"
    assert report["cleanup_status"] == "passed"
    aliases = {call[2] for call in backend.calls}
    assert len(aliases) == 1
    assert next(iter(aliases)).startswith("phase10-self-test-")
    assert all(call[1] == "3d-master-2005/provider" for call in backend.calls)
    assert [call[0] for call in backend.calls] == [
        "get", "set", "get", "set", "get", "delete", "get", "delete", "get"]
    assert backend.values == {}
    report_text = (tmp_path / "phase10-credential-store-check" /
                   "credential-store-check.json").read_text(encoding="utf-8")
    assert "phase10-self-test-" not in report_text
    assert "phase10-sentinel-" not in report_text
    assert "private fake backend message" not in report_text


def test_credential_store_check_reports_unavailable_backend_without_fallback(tmp_path, monkeypatch):
    module = _load("phase10_credential_unavailable", ROOT / "am3d" / "ai" / "frozen_acceptance.py")
    from am3d.ai import credentials
    from am3d.ai.contracts import ProviderCredentialError

    monkeypatch.setattr(
        credentials, "_make_approved_backend",
        lambda _platform: (_ for _ in ()).throw(ProviderCredentialError("locked sentinel")))
    report = module.run_credential_store_check(str(tmp_path))

    assert report["ok"] is False
    assert report["crud_status"] == "unpassed"
    assert report["crud_failure_code"] == "backend_unavailable"
    assert report["cleanup_status"] == "not_required"
    assert "locked sentinel" not in json.dumps(report)
    assert report["credential_alias_exposed"] is False
    assert report["sentinel_values_exposed"] is False


def test_credential_store_check_cleans_after_store_failure(tmp_path, monkeypatch):
    module = _load("phase10_credential_cleanup", ROOT / "am3d" / "ai" / "frozen_acceptance.py")
    from am3d.ai import credentials

    class Backend:
        def __init__(self):
            self.values = {}
            self.writes = 0

        def get_password(self, service, alias):
            return self.values.get((service, alias))

        def set_password(self, service, alias, value):
            self.writes += 1
            self.values[(service, alias)] = value
            if self.writes == 2:
                raise RuntimeError("private locked backend details")

        def delete_password(self, service, alias):
            self.values.pop((service, alias), None)

    backend = Backend()
    monkeypatch.setattr(credentials, "_make_approved_backend", lambda _platform: backend)
    report = module.run_credential_store_check(str(tmp_path))

    assert report["ok"] is False
    assert report["crud_status"] == "unpassed"
    assert report["crud_failure_code"] == "secure_store_unavailable"
    assert report["cleanup_status"] == "passed"
    assert backend.values == {}
    report_text = (tmp_path / "phase10-credential-store-check" /
                   "credential-store-check.json").read_text(encoding="utf-8")
    assert "private locked backend details" not in report_text
    assert "phase10-sentinel-" not in report_text


def test_credential_store_check_marks_cleanup_failure_unpassed(tmp_path, monkeypatch):
    module = _load("phase10_credential_cleanup_failure", ROOT / "am3d" / "ai" / "frozen_acceptance.py")
    from am3d.ai import credentials

    class Backend:
        def __init__(self):
            self.values = {}

        def get_password(self, service, alias):
            return self.values.get((service, alias))

        def set_password(self, service, alias, value):
            self.values[(service, alias)] = value

        def delete_password(self, service, alias):
            raise RuntimeError("private delete failure")

    backend = Backend()
    monkeypatch.setattr(credentials, "_make_approved_backend", lambda _platform: backend)
    report = module.run_credential_store_check(str(tmp_path))

    assert report["ok"] is False
    assert report["crud_failure_code"] == "store_delete_failed"
    assert report["cleanup_status"] == "unpassed"
    assert report["cleanup_failure_code"] == "cleanup_failed"
    assert len(backend.values) == 1
    assert "private delete failure" not in json.dumps(report)


def test_credential_store_check_dispatches_before_qt_with_a_mock_store(tmp_path):
    blocker_dir = tmp_path / "no-qt"
    blocker_dir.mkdir()
    sitecustomize = (
        "import importlib.abc, sys\n"
        "class _BlockQt(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == 'PySide6' or fullname.startswith('PySide6.'):\n"
        "            raise RuntimeError('Qt import attempted before fixed dispatch')\n"
        "sys.meta_path.insert(0, _BlockQt())\n"
        "import am3d.ai.credentials as _credentials\n"
        "class _MemoryStore:\n"
        "    def __init__(self): self.values = {}\n"
        "    def get(self, alias): return self.values.get(alias)\n"
        "    def set(self, alias, value): self.values[alias] = value\n"
        "    def delete(self, alias): self.values.pop(alias, None)\n"
        "_credentials.SystemCredentialStore = _MemoryStore\n"
    )
    (blocker_dir / "sitecustomize.py").write_text(sitecustomize, encoding="utf-8")
    output = tmp_path / "credential-output"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [os.fspath(blocker_dir), os.fspath(ROOT), env.get("PYTHONPATH", "")])
    command = [sys.executable, "-m", "am3d.ui", "--ai-self-test",
               "--credential-store-check", "--out", os.fspath(output)]
    result = subprocess.run(command, cwd=ROOT, env=env, text=True,
                            capture_output=True, timeout=30, check=False)

    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    report = json.loads((output / "phase10-credential-store-check" /
                         "credential-store-check.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["qt_loaded_before_dispatch"] is False
    assert report["real_provider_or_network_used"] is False
    assert "phase10-self-test-" not in result.stdout
    assert "phase10-sentinel-" not in result.stdout


def test_credential_store_check_rejects_linked_output_path(tmp_path):
    module = _load("phase10_credential_link_guard", ROOT / "am3d" / "ai" / "frozen_acceptance.py")
    target = tmp_path / "actual-output"
    target.mkdir()
    linked = tmp_path / "linked-output"
    try:
        linked.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable")

    with pytest.raises(module.AcceptanceError, match="unsafe_output_path"):
        module.run_credential_store_check(str(linked))
    assert list(target.iterdir()) == []


def test_credential_store_check_rejects_reparse_components_and_unknown_options(tmp_path, monkeypatch):
    module = _load("phase10_credential_guard_flags", ROOT / "am3d" / "ai" / "frozen_acceptance.py")
    guarded = tmp_path / "reparse-output"
    guarded.mkdir()
    original_linklike = module._linklike
    monkeypatch.setattr(
        module, "_linklike",
        lambda path: Path(path).name.casefold() == "reparse-output"
        or original_linklike(path))
    with pytest.raises(module.AcceptanceError, match="unsafe_output_path"):
        module.run_credential_store_check(str(guarded))
    assert list(guarded.iterdir()) == []

    output = tmp_path / "unknown-flag-output"
    with pytest.raises(SystemExit) as exc:
        module.main(["--credential-store-check", "--out", str(output),
                     "--module", "caller-controlled"])
    assert exc.value.code == 2
    assert not output.exists()


def test_ui_package_keeps_legacy_main_and_mainwindow_exports():
    from am3d import ui

    assert callable(ui.main)
    assert isinstance(ui.MainWindow, type)


def test_recipe_spec_stays_free_of_qt_and_gpu_hidden_imports():
    spec = (ROOT / "am3d_recipe.spec").read_text(encoding="utf-8")
    section = spec.split("hiddenimports=[", 1)[1].split("],", 1)[0]
    assert "PySide6" not in section
    assert "moderngl" not in section
    assert "am3d.ui" not in section
    assert "am3d.gpu" not in section


def test_frozen_specs_exclude_only_optional_test_and_command_helpers():
    expected = (
        "pytest", "_pytest", "anyio.pytest_plugin", "httpx._main",
        "pygments", "packaging", "setuptools", "_distutils_hack", "distutils",
    )
    for filename in ("am3d.spec", "am3d_recipe.spec"):
        source = (ROOT / filename).read_text(encoding="utf-8")
        excludes = source.split("excludes=[", 1)[1].split("],", 1)[0]
        for module in expected:
            assert f'"{module}"' in excludes, (filename, module)
    for platform in ("windows", "linux"):
        notices = _load("phase10_distribution_notice_names",
                        ROOT / "scripts" / "write_runtime_licenses.py")
        normalized = {re.sub(r"[-_.]+", "-", name).casefold()
                      for name in notices.runtime_distribution_names(platform)}
        assert not normalized.intersection({
            "pytest", "pygments", "packaging", "setuptools",
        })


@pytest.mark.parametrize(
    "doc_directory",
    ["python3.12", "python3.12-minimal", "libpython3.12-minimal"],
)
def test_linux_interpreter_notice_uses_only_selected_versioned_distro_copyright(
        tmp_path, monkeypatch, doc_directory):
    licenses = _load("phase10_linux_distro_notice", ROOT / "scripts" / "write_runtime_licenses.py")
    base_prefix = tmp_path / "selected-python"
    stdlib = base_prefix / "lib" / "python3.12"
    stdlib.mkdir(parents=True)
    doc = base_prefix / "share" / "doc" / doc_directory
    doc.mkdir(parents=True)
    copyright_file = doc / "copyright"
    copyright_file.write_text("exact selected distro copyright", encoding="utf-8")
    monkeypatch.setattr(licenses.sys, "base_prefix", str(base_prefix))
    monkeypatch.setattr(licenses.sysconfig, "get_path", lambda name: str(stdlib))
    monkeypatch.setattr(licenses, "_python_version_tag", lambda: "3.12")

    python_notice = licenses._interpreter_notice_source("linux")
    assert python_notice[0] == copyright_file.resolve()
    assert python_notice[1] == (
        f"Linux distribution copyright: share/doc/{doc_directory}/copyright")


def test_linux_license_manifest_records_distro_source_and_copied_hash(tmp_path, monkeypatch):
    licenses = _load("phase10_linux_distro_notice_manifest",
                     ROOT / "scripts" / "write_runtime_licenses.py")
    base_prefix = tmp_path / "selected-python"
    stdlib = base_prefix / "lib" / "python3.12"
    stdlib.mkdir(parents=True)
    doc = base_prefix / "share" / "doc" / "libpython3.12-minimal"
    doc.mkdir(parents=True)
    copyright_file = doc / "copyright"
    copyright_file.write_text("selected distro copyright bytes", encoding="utf-8")
    monkeypatch.setattr(licenses.sys, "base_prefix", str(base_prefix))
    monkeypatch.setattr(licenses.sysconfig, "get_path", lambda name: str(stdlib))
    monkeypatch.setattr(licenses, "_python_version_tag", lambda: "3.12")
    monkeypatch.setattr(licenses, "runtime_distribution_names", lambda platform: ())

    root = tmp_path / "repo"
    output = root / "release" / "candidate"
    (output / "LICENSES").mkdir(parents=True)
    manifest = licenses.write_licenses(root, output, "linux")
    python_component = next(
        item for item in manifest["bundled_components"]
        if item["license_file"] == "interpreter/CPython-LICENSE.txt")
    copied = output / "LICENSES" / python_component["license_file"]
    assert copied.read_bytes() == copyright_file.read_bytes()
    assert python_component["source"] == (
        "Linux distribution copyright: "
        "share/doc/libpython3.12-minimal/copyright")
    assert python_component["sha256"] == hashlib.sha256(copied.read_bytes()).hexdigest()
    notice = (output / "LICENSES" / "NOTICE.txt").read_text(encoding="utf-8")
    assert "Linux distribution copyright: share/doc/libpython3.12-minimal/copyright" in notice


def test_linux_interpreter_notice_accepts_selected_stdlib_license(tmp_path, monkeypatch):
    licenses = _load("phase10_linux_stdlib_notice", ROOT / "scripts" / "write_runtime_licenses.py")
    base_prefix = tmp_path / "selected-python"
    stdlib = base_prefix / "lib" / "python3.12"
    stdlib.mkdir(parents=True)
    license_file = stdlib / "LICENSE.txt"
    license_file.write_text("selected interpreter stdlib license", encoding="utf-8")
    monkeypatch.setattr(licenses.sys, "base_prefix", str(base_prefix))
    monkeypatch.setattr(licenses.sysconfig, "get_path", lambda name: str(stdlib))
    monkeypatch.setattr(licenses, "_python_version_tag", lambda: "3.12")

    python_notice = licenses._interpreter_notice_source("linux")
    assert python_notice == (
        license_file.resolve(),
        "CPython standard-library LICENSE.txt: lib/python3.12/LICENSE.txt",
    )


def test_linux_interpreter_notice_rejects_version_mismatch_and_missing_notice(
        tmp_path, monkeypatch):
    licenses = _load("phase10_linux_notice_missing", ROOT / "scripts" / "write_runtime_licenses.py")
    base_prefix = tmp_path / "selected-python"
    stdlib = base_prefix / "lib" / "python3.12"
    stdlib.mkdir(parents=True)
    wrong_version = base_prefix / "share" / "doc" / "python3.11"
    wrong_version.mkdir(parents=True)
    (wrong_version / "copyright").write_text("wrong interpreter version", encoding="utf-8")
    monkeypatch.setattr(licenses.sys, "base_prefix", str(base_prefix))
    monkeypatch.setattr(licenses.sysconfig, "get_path", lambda name: str(stdlib))
    monkeypatch.setattr(licenses, "_python_version_tag", lambda: "3.12")

    with pytest.raises(ValueError, match="exact license notice is missing"):
        licenses._interpreter_notice_source("linux")


def test_linux_interpreter_notice_rejects_stdlib_outside_selected_base(
        tmp_path, monkeypatch):
    licenses = _load("phase10_linux_notice_stdlib_escape",
                     ROOT / "scripts" / "write_runtime_licenses.py")
    base_prefix = tmp_path / "selected-python"
    base_prefix.mkdir()
    outside_stdlib = tmp_path / "other-python" / "lib" / "python3.12"
    outside_stdlib.mkdir(parents=True)
    (outside_stdlib / "LICENSE.txt").write_text(
        "license for a different base interpreter", encoding="utf-8")
    monkeypatch.setattr(licenses.sys, "base_prefix", str(base_prefix))
    monkeypatch.setattr(licenses.sysconfig, "get_path", lambda name: str(outside_stdlib))
    monkeypatch.setattr(licenses, "_python_version_tag", lambda: "3.12")

    with pytest.raises(ValueError, match="exact license notice is missing"):
        licenses._interpreter_notice_source("linux")


def test_linux_interpreter_notice_rejects_a_symlink_outside_the_selected_base(
        tmp_path, monkeypatch):
    licenses = _load("phase10_linux_notice_escape", ROOT / "scripts" / "write_runtime_licenses.py")
    base_prefix = tmp_path / "selected-python"
    stdlib = base_prefix / "lib" / "python3.12"
    stdlib.mkdir(parents=True)
    outside = tmp_path / "outside-license.txt"
    outside.write_text("outside source must not be accepted", encoding="utf-8")
    candidate = stdlib / "LICENSE.txt"
    candidate.write_text("linked source placeholder", encoding="utf-8")
    original_is_link = licenses._is_link
    original_resolve = Path.resolve
    monkeypatch.setattr(
        licenses, "_is_link",
        lambda path: Path(path) == candidate or original_is_link(path))

    def resolve_test_link(path, strict=False):
        if Path(path) == candidate:
            return outside.resolve(strict=strict)
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve_test_link)
    monkeypatch.setattr(licenses.sys, "base_prefix", str(base_prefix))
    monkeypatch.setattr(licenses.sysconfig, "get_path", lambda name: str(stdlib))
    monkeypatch.setattr(licenses, "_python_version_tag", lambda: "3.12")

    with pytest.raises(ValueError, match="approved exact notice"):
        licenses._interpreter_notice_source("linux")


def test_windows_interpreter_notice_does_not_use_linux_distribution_fallback(
        tmp_path, monkeypatch):
    licenses = _load("phase10_windows_notice_no_fallback",
                     ROOT / "scripts" / "write_runtime_licenses.py")
    base_prefix = tmp_path / "selected-python"
    doc = base_prefix / "share" / "doc" / "python3.12"
    doc.mkdir(parents=True)
    (doc / "copyright").write_text("Linux-only source", encoding="utf-8")
    monkeypatch.setattr(licenses.sys, "base_prefix", str(base_prefix))
    monkeypatch.setattr(licenses, "_python_version_tag", lambda: "3.12")

    with pytest.raises(ValueError, match="exact license notice is missing"):
        licenses._interpreter_notice_source("windows")


def test_linux_interpreter_notice_allows_only_an_exact_in_base_distro_alias(
        tmp_path, monkeypatch):
    licenses = _load("phase10_linux_notice_alias", ROOT / "scripts" / "write_runtime_licenses.py")
    base_prefix = tmp_path / "selected-python"
    stdlib = base_prefix / "lib" / "python3.12"
    stdlib.mkdir(parents=True)
    doc = base_prefix / "share" / "doc" / "python3.12"
    doc.mkdir(parents=True)
    copyright_file = doc / "copyright"
    copyright_file.write_text("selected distro copyright", encoding="utf-8")
    alias = stdlib / "LICENSE.txt"
    alias.write_text("linked source placeholder", encoding="utf-8")
    original_is_link = licenses._is_link
    original_resolve = Path.resolve
    monkeypatch.setattr(
        licenses, "_is_link",
        lambda path: Path(path) == alias or original_is_link(path))

    def resolve_test_alias(path, strict=False):
        if Path(path) == alias:
            return copyright_file.resolve(strict=strict)
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve_test_alias)
    monkeypatch.setattr(licenses.sys, "base_prefix", str(base_prefix))
    monkeypatch.setattr(licenses.sysconfig, "get_path", lambda name: str(stdlib))
    monkeypatch.setattr(licenses, "_python_version_tag", lambda: "3.12")

    source, description = licenses._interpreter_notice_source("linux")
    assert source == copyright_file.resolve()
    assert description == (
        "Linux distribution copyright: share/doc/python3.12/copyright "
        "(selected path lib/python3.12/LICENSE.txt resolves to "
        "share/doc/python3.12/copyright)"
    )


@pytest.mark.parametrize("dispatch", ["--internal-ai-worker", "--ai-self-test"])
def test_guarded_pyside6_runtime_hook_skips_fixed_dispatch_without_qt(
        dispatch, monkeypatch):
    import runpy
    import types

    hook = ROOT / "scripts" / "pyi_rth_am3d_pyside6.py"
    utils = types.ModuleType("_pyi_rth_utils")
    utils.__getattr__ = lambda name: (_ for _ in ()).throw(
        AssertionError(f"fixed dispatch imported Qt runtime helper {name}"))
    monkeypatch.setitem(sys.modules, "_pyi_rth_utils", utils)
    monkeypatch.setattr(sys, "argv", ["3D MASTER 2005", dispatch, "--out", "unused"])
    monkeypatch.setenv("QT_PLUGIN_PATH", "fixed-qt-plugin-sentinel")
    monkeypatch.setenv("QML2_IMPORT_PATH", "fixed-qml-sentinel")

    class RejectQtImport:
        attempted = False

        def find_spec(self, fullname, _path=None, _target=None):
            if fullname == "PySide6" or fullname.startswith("PySide6."):
                self.attempted = True
                raise AssertionError(f"fixed dispatch attempted Qt import {fullname}")
            return None

    reject_qt = RejectQtImport()
    for name in tuple(sys.modules):
        if name == "PySide6" or name.startswith("PySide6."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [reject_qt, *sys.meta_path])

    environment_names = ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "PATH", "DYLD_LIBRARY_PATH")
    for name in environment_names:
        monkeypatch.setenv(name, f"fixed-dispatch-{name.lower()}-sentinel")
    before = tuple(os.environ[name] for name in environment_names)
    runpy.run_path(os.fspath(hook), run_name="am3d_pyside6_fixed_dispatch_test")

    assert tuple(os.environ[name] for name in environment_names) == before
    assert not reject_qt.attempted


def test_guarded_pyside6_runtime_hook_preserves_normal_gui_setup(tmp_path, monkeypatch):
    import runpy
    import types

    calls = []
    utils = types.ModuleType("_pyi_rth_utils")
    utils.is_macos_app_bundle = False
    utils.prepend_path_to_environment_variable = lambda path, name: calls.append((path, name))
    qt = types.ModuleType("_pyi_rth_utils.qt")
    qt.ensure_single_qt_bindings_package = lambda name: calls.append(("ensure", name))
    qt.create_embedded_qt_conf = lambda name, path: calls.append(("qt.conf", name, path))
    utils.qt = qt
    monkeypatch.setitem(sys.modules, "_pyi_rth_utils", utils)
    monkeypatch.setitem(sys.modules, "_pyi_rth_utils.qt", qt)
    monkeypatch.setattr(sys, "argv", ["3D MASTER 2005", "--open", "project.am3d"])
    monkeypatch.setattr(sys, "_MEIPASS", os.fspath(tmp_path), raising=False)
    monkeypatch.setenv("QT_PLUGIN_PATH", "old-plugin-path")
    monkeypatch.setenv("QML2_IMPORT_PATH", "old-qml-path")

    pyqt_path = (tmp_path / "PySide6" if sys.platform.startswith("win")
                 else tmp_path / "PySide6" / "Qt")
    runpy.run_path(os.fspath(ROOT / "scripts" / "pyi_rth_am3d_pyside6.py"),
                   run_name="am3d_pyside6_gui_test")

    assert calls[0] == ("ensure", "PySide6")
    assert calls[-1] == ("qt.conf", "PySide6", os.fspath(pyqt_path))
    assert os.environ["QT_PLUGIN_PATH"] == os.fspath(pyqt_path / "plugins")
    assert os.environ["QML2_IMPORT_PATH"] == os.fspath(pyqt_path / "qml")
    if sys.platform.startswith("win"):
        assert (os.fspath(tmp_path), "PATH") in calls
    elif sys.platform == "darwin":
        assert (os.fspath(tmp_path), "DYLD_LIBRARY_PATH") in calls


def test_gui_spec_substitutes_only_the_pyinstaller_pyside6_runtime_hook():
    source = (ROOT / "am3d.spec").read_text(encoding="utf-8")
    assert 'entry[0] == "pyi_rth_pyside6"' in source
    assert "len(_pyside6_hook_indexes) != 1" in source
    assert "str(_pyside6_hook_path)" in source


def test_phase10_powershell_parses_and_guards_outside_path(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell Core is unavailable")
    helper = ROOT / "scripts" / "phase10_safety.ps1"
    parse_script = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{str(helper).replace("'", "''")}', "
        "[ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    parsed = subprocess.run([pwsh, "-NoProfile", "-Command", parse_script],
                            text=True, capture_output=True, check=False)
    assert parsed.returncode == 0, parsed.stdout + parsed.stderr

    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    guard_script = (
        f". '{str(helper).replace("'", "''")}'; "
        "try { Remove-Phase10Directory -Target "
        f"'{str(outside).replace("'", "''")}' -AllowedRoot '{str(allowed).replace("'", "''")}'; "
        "exit 3 } catch { exit 0 }"
    )
    guarded = subprocess.run([pwsh, "-NoProfile", "-Command", guard_script],
                             text=True, capture_output=True, check=False)
    assert guarded.returncode == 0, guarded.stdout + guarded.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_windows_build_provenance_uses_the_declared_host_python_version():
    source = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
    provenance = source.split("Step 8b: Writing build provenance...", 1)[1]
    assert "$hostPythonVersion =" in source
    assert '"python (host)    : $hostPythonVersion"' in provenance
    assert "$hostPy.Version" not in provenance


def test_windows_build_counts_singleton_recipe_artifacts_under_strict_mode(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell Core is unavailable")

    source = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
    assert re.search(r"\$produced\s*=\s*@\(\s*Get-ChildItem", source)
    assert re.search(r"\$relocatedArtifacts\s*=\s*@\(\s*Get-ChildItem", source)
    assert "$(@($smokeManifest.steps).Count)" in source

    recipe_output = tmp_path / "one-artifact"
    recipe_output.mkdir()
    (recipe_output / "one.obj").write_text("artifact", encoding="utf-8")
    (recipe_output / "report.json").write_text("{}", encoding="utf-8")
    script = tmp_path / "check_singleton_count.ps1"
    script.write_text(
        "Set-StrictMode -Version Latest\n"
        "$recipeOut = $args[0]\n"
        "$produced = @(\n"
        "    Get-ChildItem -Recurse -File $recipeOut |\n"
        "        Where-Object { $_.Name -ne 'report.json' }\n"
        ")\n"
        "$relocatedArtifacts = @(\n"
        "    Get-ChildItem -LiteralPath $recipeOut -Recurse -File |\n"
        "        Where-Object { $_.Name -ne 'report.json' }\n"
        ")\n"
        "if ($produced.Count -ne 1 -or $relocatedArtifacts.Count -ne 1) { exit 2 }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", os.fspath(script), os.fspath(recipe_output)],
        text=True, capture_output=True, check=False, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_windows_bootstrap_and_locked_build_share_lock_normalizer_under_strict_mode(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell Core is unavailable")

    source = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
    begin = "# PHASE10_LOCK_NORMALIZER_BEGIN"
    end = "# PHASE10_LOCK_NORMALIZER_END"
    normalizer = source.split(begin, 1)[1].split(end, 1)[0]
    lock_check = source.index("if (Test-Path -LiteralPath $lockPath)")
    assert source.index(begin) < lock_check
    assert source.count("Normalize-Phase10LockEntries -Lines") == 3
    assert "$normalizeLock" not in source

    lock_path = tmp_path / "requirements-lock-windows.txt"
    assert not lock_path.exists()
    script = tmp_path / "check_lock_proposal_scope.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "Set-StrictMode -Version Latest\n"
        + normalizer + "\n"
        "$lockPath = $args[0]\n"
        "$frozen = @('My_Pkg==1.2.3', 'other.pkg==4.5.6', "
        "'pip==24.0', 'setuptools==84.0.0', 'wheel==0.44')\n"
        "if (Test-Path -LiteralPath $lockPath) { throw 'bootstrap fixture must start without a source lock' }\n"
        "$bootstrapProposal = @(Normalize-Phase10LockEntries -Lines @($frozen))\n"
        "$expected = @('my-pkg==1.2.3', 'other-pkg==4.5.6', 'setuptools==84.0.0', 'wheel==0.44')\n"
        "if (($bootstrapProposal -join \"`n\") -cne ($expected -join \"`n\")) { throw 'bootstrap proposal changed canonical lock entries' }\n"
        "[System.IO.File]::WriteAllLines($lockPath, [string[]]@('# source lock', 'OTHER_pkg==4.5.6', 'pip==24.0', 'My.Pkg==1.2.3', 'setuptools==84.0.0', 'wheel==0.44'))\n"
        "if (-not (Test-Path -LiteralPath $lockPath)) { throw 'locked fixture was not installed' }\n"
        "$lockedEntries = @(Normalize-Phase10LockEntries -Lines @(Get-Content -LiteralPath $lockPath))\n"
        "$installedEntries = @(Normalize-Phase10LockEntries -Lines @($frozen))\n"
        "$proposalEntries = @(Normalize-Phase10LockEntries -Lines @($frozen))\n"
        "$matchDifference = @(Compare-Object -ReferenceObject @($lockedEntries) -DifferenceObject @($installedEntries))\n"
        "if ($matchDifference.Count -ne 0) { throw 'equivalent captured lock did not match the installed freeze' }\n"
        "if (($proposalEntries -join \"`n\") -cne ($installedEntries -join \"`n\")) { throw 'proposal and installed comparison use different normalization' }\n"
        "$mismatchPath = [System.IO.Path]::ChangeExtension($lockPath, '.mismatch')\n"
        "[System.IO.File]::WriteAllLines($mismatchPath, [string[]]@('My.Pkg==1.2.3', 'OTHER_pkg==4.5.6', 'setuptools==84.0.1', 'wheel==0.44'))\n"
        "$mismatchEntries = @(Normalize-Phase10LockEntries -Lines @(Get-Content -LiteralPath $mismatchPath))\n"
        "$mismatchDifference = @(Compare-Object -ReferenceObject @($mismatchEntries) -DifferenceObject @($installedEntries))\n"
        "if ($mismatchDifference.Count -eq 0) { throw 'different setuptools version was not detected' }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", os.fspath(script), os.fspath(lock_path)],
        text=True, capture_output=True, check=False, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_windows_pyinstaller_path_excludes_ambient_dlls_and_restores_after_failure(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell Core is unavailable")

    source = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
    begin = "# PHASE10_PYINSTALLER_SEARCH_PATH_HELPERS_BEGIN"
    end = "# PHASE10_PYINSTALLER_SEARCH_PATH_HELPERS_END"
    helpers = source.split(begin, 1)[1].split(end, 1)[0]
    assert source.count("Invoke-Phase10WithPyInstallerSearchPath -HostPythonPath") == 2
    assert source.count("--distpath $DistDir --workpath $WorkDir") == 2

    ambient = tmp_path / "ambient-native-tools"
    ambient.mkdir()
    (ambient / "icuuc.dll").write_bytes(b"test-only ambient DLL sentinel")
    venv_scripts = tmp_path / "isolated-venv" / "Scripts"
    venv_scripts.mkdir(parents=True)

    def ps_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    script = tmp_path / "check_pyinstaller_search_path.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "$env:PATH = " + ps_literal(str(ambient)) +
        " + [System.IO.Path]::PathSeparator + $env:PATH\n"
        "$ambientDirectory = " + ps_literal(str(ambient)) + "\n"
        "$hostPython = " + ps_literal(sys.executable) + "\n"
        "$venvScripts = " + ps_literal(str(venv_scripts)) + "\n"
        "$previousPath = $env:PATH\n"
        + helpers + "\n"
        "$expected = @(Get-Phase10PyInstallerSearchPath -HostPythonPath $hostPython -VenvScriptsPath $venvScripts) -split [System.IO.Path]::PathSeparator\n"
        "$actionFailed = $false\n"
        "try {\n"
        "    Invoke-Phase10WithPyInstallerSearchPath -HostPythonPath $hostPython -VenvScriptsPath $venvScripts -Action {\n"
        "        $actual = @($env:PATH -split [System.IO.Path]::PathSeparator)\n"
        "        if ($actual -contains $ambientDirectory) { throw 'ambient DLL directory leaked into PyInstaller PATH' }\n"
        "        if ($actual.Count -ne $expected.Count) { throw 'unexpected dependency-search directories were retained' }\n"
        "        foreach ($trusted in $expected) { if ($actual -cnotcontains $trusted) { throw 'trusted dependency-search directory was omitted' } }\n"
        "        $env:PATH = 'mutated-inside-action'\n"
        "        throw 'intentional callback failure'\n"
        "    }\n"
        "} catch { if ($_.Exception.Message -ne 'intentional callback failure') { throw }; $actionFailed = $true }\n"
        "if (-not $actionFailed) { throw 'callback failure did not propagate' }\n"
        "if ($env:PATH -cne $previousPath) { throw 'PATH was not restored exactly after failure' }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", os.fspath(script)],
        text=True, capture_output=True, check=False, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_windows_acl_restore_parent_resolves_with_powershell_directory_info(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell Core is unavailable")

    source = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
    assert "$aclRestoreParent = [System.IO.Path]::GetDirectoryName($verifiedReleaseDir.FullName)" in source
    parent = tmp_path / "acl-parent"
    child = parent / "payload"
    parent.mkdir()
    child.mkdir()
    script = tmp_path / "check_acl_parent.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "$verifiedReleaseDir = Get-Item -LiteralPath $args[0]\n"
        "if ($verifiedReleaseDir -isnot [System.IO.DirectoryInfo]) { exit 2 }\n"
        "$aclRestoreParent = [System.IO.Path]::GetDirectoryName($verifiedReleaseDir.FullName)\n"
        "$expectedParent = [System.IO.Path]::GetFullPath($args[1])\n"
        "if ([System.IO.Path]::GetFullPath($aclRestoreParent) -ine $expectedParent) { exit 3 }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", os.fspath(script), os.fspath(child), os.fspath(parent)],
        text=True, capture_output=True, check=False, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_readonly_relocation_checks_workflow_while_payload_writes_are_denied():
    windows = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
    windows_block = windows.split("# Apply a real Windows access-control deny", 1)[1]
    restore_call = '& $icacls.Source $aclRestoreParent /restore $aclBackupPath /c'
    restore_positions = [match.start() for match in re.finditer(re.escape(restore_call), windows_block)]
    deny_position = windows_block.index("/deny")
    workflow_position = windows_block.index('$readOnlyAiPsi.Arguments = "--ai-self-test')
    assert len(restore_positions) == 2
    assert "$aclRestoreParent = [System.IO.Path]::GetDirectoryName($verifiedReleaseDir.FullName)" in windows_block
    assert "Split-Path -LiteralPath $verifiedReleaseDir.FullName -Parent" not in windows_block
    assert windows_block.index("/save $aclBackupPath /t /c") < restore_positions[0] < deny_position
    assert restore_positions[0] < windows_block.index("$aclMutationAttempted = $true") < deny_position
    assert deny_position < workflow_position < restore_positions[1]
    assert '"*$($currentSid):(OI)(CI)(W)"' in windows_block
    assert '"UNPASSED: Windows ACL restore capability unavailable"' in windows_block
    assert '"UNPASSED: restore capability not proven; payload ACL was not changed"' in windows_block
    assert 'if ($aclMutationAttempted) {' in windows_block
    assert "$script:preserveVerifyRoot = $true" in windows_block
    assert 'if ($script:preserveVerifyRoot)' in windows
    assert windows_block.index('$script:readOnlyStatus = "passed"') < windows_block.index(
        'if ($script:readOnlyStatus -eq "passed")')
    assert 'Join-Path $verifyRoot "readonly_ai_self_test_host"' in windows_block
    assert "$readOnlyAiHostFull.StartsWith(" in windows_block
    assert '"relocated read-only write-denial: $($script:readOnlyStatus)"' in windows
    assert '"read-only frozen AI workflow: $($script:readOnlyWorkflowStatus)"' in windows
    assert windows_block.rindex('Write-Host "  Read-only frozen AI workflow:') < windows_block.index(
        'throw "Fixed offline AI workflow failed while the relocated payload was write-denied."')

    linux = (ROOT / "build_linux.sh").read_text(encoding="utf-8")
    linux_block = linux.split('step "Step 9b: Checking relocated payload write protection..."', 1)[1]
    assert linux_block.index("chmod -R a-w -- \"$VERIFY_DIR\"") < linux_block.index(
        '"$VERIFY_DIR/$APP_NAME" --ai-self-test')
    assert linux_block.index('if [ "$READ_ONLY_RC" -eq 0 ]; then') < linux_block.index(
        '"$VERIFY_DIR/$APP_NAME" --ai-self-test')
    assert linux_block.index('"$VERIFY_DIR/$APP_NAME" --ai-self-test') < linux_block.index(
        'chmod -R u+w -- "$VERIFY_DIR"')
    assert 'case "$READ_ONLY_AI_HOST_REAL" in' in linux_block
    assert 'READ_ONLY_AI_REPORT="$READ_ONLY_AI_HOST/phase10-ai-self-test/acceptance.json"' in linux_block
    assert "relocated read-only write-denial: $READ_ONLY_STATUS" in linux
    assert "read-only frozen AI workflow: $READ_ONLY_WORKFLOW_STATUS" in linux
    assert linux_block.index('printf \'  Read-only frozen AI workflow: %s\\n\' "$READ_ONLY_WORKFLOW_STATUS"') < linux_block.index(
        'die "fixed offline AI workflow failed while the relocated payload was write-denied"')


@pytest.mark.parametrize("path", ["build_windows.ps1", "build_linux.sh",
                                   "am3d.spec", "scripts/build_input_digest.py"])
def test_phase10_tooling_files_are_present(path):
    assert (ROOT / path).is_file()
