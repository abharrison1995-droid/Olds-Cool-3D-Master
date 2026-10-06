"""Offline M3.1 provider, prompt, policy and M2 orchestration coverage."""

from __future__ import annotations

from dataclasses import fields, replace
import json
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from . import orchestrator as orchestrator_module
from .contracts import GenerationStatus
from .orchestrator import (GenerationOrchestrator, OrchestrationStatus)
from .policy import authorize_recipe
from .prompt import (MAX_BRIEF_CHARS, PromptBuildError, PromptCompiler)
from .provider_contracts import FailureCode, provider_response_schema
from .providers import (AdapterKind, FakeBehavior, FakeProvider,
                        ProviderCallStatus, ProviderResult, UsageMetadata)
from .runner import GenerationRunner
from .storage import GenerationStore


def _wait(orchestrator: GenerationOrchestrator, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = orchestrator.poll()
        if result is not None and result.status is not OrchestrationStatus.RUNNING:
            return result
        time.sleep(0.025)
    raise AssertionError("orchestration did not complete before the test deadline")


def _deny_worker_start(runner):
    def denied(_recipe):
        raise AssertionError("unvalidated provider recipe reached the M2 runner")
    runner.start = denied


def _raw_provider(response: bytes) -> FakeProvider:
    provider = FakeProvider()

    def generate(request):
        provider.calls += 1
        provider.last_request = request
        return ProviderResult(
            provider.provider_id, provider.model_id, provider.adapter_kind,
            ProviderCallStatus.SUCCEEDED, response_bytes=response,
            latency_ms=1.0, usage=UsageMetadata())

    provider.generate = generate
    return provider


def test_prompt_prefix_is_stable_bounded_and_brief_is_last():
    compiler = PromptCompiler()
    first = compiler.compile("A blue cube")
    second = compiler.compile("A red stool")

    assert first.system_prompt == second.system_prompt
    assert first.user_prompt.endswith("A blue cube")
    assert second.user_prompt.endswith("A red stool")
    assert "Response JSON Schema:" in first.system_prompt
    assert first.system_prompt.count('"schema_version":1') == 2
    assert "You have no access to the user's repository" in first.system_prompt
    assert first.deadline_seconds == 600
    assert first.max_response_bytes == 1024 * 1024
    assert set(field.name for field in fields(first)) == {
        "system_prompt", "user_prompt", "response_schema",
        "deadline_seconds", "max_response_bytes"}
    assert "output_root" not in first.__dict__
    assert "command" not in first.__dict__
    assert first.response_schema["additionalProperties"] is False

    with pytest.raises(PromptBuildError) as caught:
        compiler.compile("x" * (MAX_BRIEF_CHARS + 1))
    assert caught.value.code is FailureCode.PROMPT_TOO_LARGE


def test_both_fixed_prompt_examples_pass_existing_ai_policy(tmp_path):
    from .prompt import _EXAMPLES

    for example in _EXAMPLES:
        response = json.loads(json.dumps(example))
        schema = provider_response_schema()
        from jsonschema import Draft202012Validator
        Draft202012Validator(schema).validate(response)
        authorize_recipe(response["recipe"], tmp_path / "host-preflight" / "exports")


@pytest.mark.parametrize(("behavior", "code"), [
    (FakeBehavior.TRANSPORT_FAILURE, FailureCode.TRANSPORT_FAILURE),
    (FakeBehavior.NONZERO_EXIT, FailureCode.NONZERO_EXIT),
    (FakeBehavior.TIMEOUT, FailureCode.TIMEOUT),
    (FakeBehavior.QUOTA_LIMIT, FailureCode.QUOTA_RATE_LIMIT),
    (FakeBehavior.AUTHENTICATION_FAILURE, FailureCode.AUTHENTICATION_FAILURE),
    (FakeBehavior.REFUSAL, FailureCode.REFUSAL),
    (FakeBehavior.UNAVAILABLE_PROVIDER, FailureCode.UNAVAILABLE_PROVIDER),
    (FakeBehavior.UNSUPPORTED_ADAPTER, FailureCode.UNSUPPORTED_ADAPTER),
])
def test_fake_provider_failure_classes_are_typed_and_one_shot(behavior, code):
    provider = FakeProvider(behavior)
    request = PromptCompiler().compile("A cube")
    result = provider.generate(request)
    assert provider.calls == 1
    assert result.status is ProviderCallStatus.FAILED
    assert result.failure_code is code
    assert result.response_bytes is None
    assert result.provider_id == "fake"
    assert result.model_id == "canned-v1"
    assert result.adapter_kind is AdapterKind.FAKE
    assert result.transport_status
    if behavior is FakeBehavior.NONZERO_EXIT:
        assert result.transport_code == 23


def test_fake_provider_hang_obeys_a_short_test_deadline():
    request = PromptCompiler().compile("A cube")
    request = replace(request, deadline_seconds=0.1)
    provider = FakeProvider(FakeBehavior.HANG, hang_seconds=0.5)
    started = time.monotonic()
    result = provider.generate(request)
    elapsed = time.monotonic() - started

    assert result.status is ProviderCallStatus.FAILED
    assert result.failure_code is FailureCode.TIMEOUT
    assert elapsed < 1.0
    assert provider.calls == 1


@pytest.mark.parametrize(("behavior", "code"), [
    (FakeBehavior.MALFORMED_JSON, FailureCode.MALFORMED_JSON),
    (FakeBehavior.DUPLICATE_KEYS, FailureCode.DUPLICATE_JSON_KEYS),
    (FakeBehavior.INVALID_UTF8, FailureCode.INVALID_UTF8),
    (FakeBehavior.OVERSIZED, FailureCode.RESPONSE_TOO_LARGE),
    (FakeBehavior.TEXTURE_PATH, FailureCode.INVALID_STRUCTURED_RESPONSE),
    (FakeBehavior.COMMAND_FIELD, FailureCode.UNKNOWN_FIELDS),
    (FakeBehavior.OUTPUT_ROOT_FIELD, FailureCode.UNKNOWN_FIELDS),
])
def test_failed_provider_response_never_launches_m2(behavior, code, tmp_path):
    provider = FakeProvider(behavior)
    runner = GenerationRunner(GenerationStore(tmp_path / "data"))
    _deny_worker_start(runner)
    outcome = GenerationOrchestrator(provider, runner).start("Make a cube")

    assert provider.calls == 1
    assert outcome.status is OrchestrationStatus.FAILED
    assert outcome.failure_code is code
    assert runner.last_result is None
    assert not runner.store.generations.exists()
    assert outcome.usage is not None
    assert outcome.usage.input_tokens is None
    assert outcome.usage.total_tokens is None


@pytest.mark.parametrize("behavior", [
    FakeBehavior.INVALID_RECIPE,
    FakeBehavior.POLICY_DENIED,
    FakeBehavior.RESOURCE_LIMIT,
])
def test_m1_m2_policy_rejections_do_not_launch_worker(behavior, tmp_path):
    provider = FakeProvider(behavior)
    runner = GenerationRunner(GenerationStore(tmp_path / "data"))
    _deny_worker_start(runner)
    with patch.object(orchestrator_module, "authorize_recipe",
                      wraps=orchestrator_module.authorize_recipe) as validate:
        outcome = GenerationOrchestrator(provider, runner).start("Make a cube")

    assert validate.call_count == 1
    assert provider.calls == 1
    assert outcome.status is OrchestrationStatus.FAILED
    assert outcome.failure_code is FailureCode.POLICY_REJECTION
    assert outcome.validation_issues
    assert runner.last_result is None
    assert not runner.store.generations.exists()


def test_valid_response_reaches_real_m2_runner_and_worker(tmp_path):
    provider = FakeProvider(known_usage=True)
    runner = GenerationRunner(GenerationStore(tmp_path / "local data – £"))
    with patch.object(orchestrator_module, "authorize_recipe",
                      wraps=orchestrator_module.authorize_recipe) as preflight, \
            patch("am3d.ai.runner.authorize_recipe",
                  wraps=authorize_recipe) as runner_policy:
        orchestrator = GenerationOrchestrator(provider, runner)
        started = orchestrator.start("A simple block")
        assert started.status is OrchestrationStatus.RUNNING
        result = _wait(orchestrator)

    assert provider.calls == 1
    assert preflight.call_count == 1
    assert runner_policy.call_count == 1
    assert result.status is OrchestrationStatus.COMPLETE
    assert result.failure_code is None
    assert result.generation_result is not None
    assert result.generation_result.status is GenerationStatus.COMPLETE
    assert result.generation_run_id == result.generation_result.run_id
    assert all(item.ok for item in result.generation_result.checks)
    assert (runner.store.generations / result.generation_run_id / "record.json").is_file()
    assert result.usage is not None
    assert result.usage.input_tokens == 41
    assert result.usage.output_tokens == 29
    assert result.usage.total_tokens == 70
    assert result.usage.failure_classification is None
    assert len(result.usage.attempt_id) == 32
    assert result.usage.occurred_at.endswith("+00:00")


def test_host_policy_rejects_path_escape_before_runner_start(tmp_path):
    provider = FakeProvider(FakeBehavior.POLICY_DENIED)
    runner = GenerationRunner(GenerationStore(tmp_path / "data"))
    _deny_worker_start(runner)
    outcome = GenerationOrchestrator(provider, runner).start("Export this model")

    assert outcome.failure_code is FailureCode.POLICY_REJECTION
    assert any(issue.path.endswith(".path") for issue in outcome.validation_issues)
    assert provider.calls == 1


def test_provider_cannot_bypass_policy_with_texture_or_arbitrary_params(tmp_path):
    # The generated provider contract blocks arbitrary texture paths. Its
    # generic params shape can still express an unknown key, which the existing
    # M1 registry-backed policy then rejects.
    texture = FakeProvider(FakeBehavior.TEXTURE_PATH)
    runner = GenerationRunner(GenerationStore(tmp_path / "texture-data"))
    _deny_worker_start(runner)
    result = GenerationOrchestrator(texture, runner).start("Use a texture")
    assert result.failure_code is FailureCode.INVALID_STRUCTURED_RESPONSE

    invalid = FakeProvider(FakeBehavior.INVALID_RECIPE)
    runner = GenerationRunner(GenerationStore(tmp_path / "params-data"))
    _deny_worker_start(runner)
    result = GenerationOrchestrator(invalid, runner).start("Make a block")
    assert result.failure_code is FailureCode.POLICY_REJECTION
    assert result.validation_issues[0].code


def test_provider_modules_do_not_import_qt_or_read_active_document():
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; import am3d.ai.provider_contracts, am3d.ai.providers, "
         "am3d.ai.prompt, am3d.ai.orchestrator; "
         "assert not any(name.startswith('PySide6') for name in sys.modules)"],
        check=False, capture_output=True, text=True)
    assert probe.returncode == 0, probe.stderr


def test_provider_exception_is_sanitized_and_never_retried(tmp_path):
    class ExplodingProvider(FakeProvider):
        def generate(self, request):
            self.calls += 1
            raise OSError("cannot read /home/alex/.ssh/private-key")

    provider = ExplodingProvider()
    runner = GenerationRunner(GenerationStore(tmp_path / "data"))
    _deny_worker_start(runner)
    outcome = GenerationOrchestrator(provider, runner).start("Make a block")

    assert provider.calls == 1
    assert outcome.failure_code is FailureCode.TRANSPORT_FAILURE
    assert "/home/alex" not in outcome.message
    assert outcome.usage is not None
    assert outcome.usage.call_status == ProviderCallStatus.FAILED.value


def test_quota_failure_is_recorded_without_inventing_token_usage(tmp_path):
    provider = FakeProvider(FakeBehavior.QUOTA_LIMIT)
    runner = GenerationRunner(GenerationStore(tmp_path / "data"))
    outcome = GenerationOrchestrator(provider, runner).start("Make a block")

    assert outcome.failure_code is FailureCode.QUOTA_RATE_LIMIT
    assert outcome.usage is not None
    assert outcome.usage.quota_or_rate_limited is True
    assert outcome.usage.input_tokens is None
    assert outcome.usage.output_tokens is None
    assert outcome.usage.total_tokens is None
