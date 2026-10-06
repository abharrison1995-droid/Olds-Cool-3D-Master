"""M2 strict AI policy stays layered over recipe-v1 validation."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest

from .policy import (MAX_RECIPE_BYTES, PolicyRejected, authorize_recipe,
                     policy_snapshot)


def _recipe(**changes):
    value = {
        "version": 1,
        "name": "local_recipe",
        "objects": [{"name": "shape", "primitive": "plane"}],
        "exports": [{"format": "am3d", "path": "exports/project"}],
    }
    value.update(changes)
    return value


def test_policy_accepts_m1_valid_recipe_and_binds_snapshot(tmp_path):
    decision = authorize_recipe(_recipe(), tmp_path.resolve())
    payload = {key: value for key, value in decision.snapshot.items()
               if key != "sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(encoded.encode()).hexdigest() == decision.snapshot["sha256"]
    assert decision.output_root == str(tmp_path.resolve())
    assert decision.recipe.name == "local_recipe"
    assert decision.resource_estimate["objects"] == 1


def test_policy_rejects_oversized_serialized_recipe_before_parsing(tmp_path):
    raw = b"{}" + b" " * (MAX_RECIPE_BYTES - 1)
    assert len(raw) > MAX_RECIPE_BYTES
    with pytest.raises(PolicyRejected) as exc:
        authorize_recipe(raw, tmp_path.resolve())
    assert exc.value.errors[0].code == "recipe_too_large"


@pytest.mark.parametrize("path", [
    "../escape.am3d", "/tmp/absolute.am3d", "C:\\escape.am3d",
    "//server/share/file.am3d", "CON.am3d",
])
def test_policy_rejects_nonportable_or_escaping_output_paths(tmp_path, path):
    with pytest.raises(PolicyRejected) as exc:
        authorize_recipe(_recipe(exports=[{"format": "am3d", "path": path}]),
                         tmp_path.resolve())
    assert any(error.code == "output_path_rejected" for error in exc.value.errors)
    assert any(error.path == "recipe.exports[0].path" for error in exc.value.errors)


def test_policy_rejects_texture_paths_with_repairable_location(tmp_path):
    recipe = _recipe(materials=[{"name": "paint", "texture": "/tmp/secret.png"}])
    with pytest.raises(PolicyRejected) as exc:
        authorize_recipe(recipe, tmp_path.resolve())
    assert any(error.code == "texture_path_forbidden"
               and error.path == "recipe.materials[0].texture"
               for error in exc.value.errors)


def test_policy_rejects_m1_ai_ceiling_before_execution(tmp_path):
    recipe = _recipe(objects=[{"name": "sphere", "primitive": "sphere",
                              "params": {"sections": 129}}])
    with pytest.raises(PolicyRejected) as exc:
        authorize_recipe(recipe, tmp_path.resolve())
    assert any(error.path == "recipe.objects[0].params.sections"
               for error in exc.value.errors)


def test_policy_rejects_duplicate_json_keys(tmp_path):
    with pytest.raises(PolicyRejected) as exc:
        authorize_recipe('{"version":1,"name":"one","name":"two"}',
                         tmp_path.resolve())
    assert exc.value.errors[0].code == "invalid_json"


def test_policy_requires_absolute_host_selected_root(tmp_path):
    with pytest.raises(PolicyRejected) as exc:
        authorize_recipe(_recipe(), "relative/output")
    assert exc.value.errors[0].code == "host_output_root_required"


def test_policy_snapshot_is_stable_and_versioned():
    first, second = policy_snapshot(), policy_snapshot()
    assert first == second
    assert first["policy_version"] == 1
    assert len(first["sha256"]) == 64


def test_headless_ai_modules_do_not_import_qt():
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; import am3d.ai.policy, am3d.ai.contracts; "
         "assert not any(name.startswith('PySide6') for name in sys.modules)"],
        check=False, capture_output=True, text=True)
    assert probe.returncode == 0, probe.stderr
