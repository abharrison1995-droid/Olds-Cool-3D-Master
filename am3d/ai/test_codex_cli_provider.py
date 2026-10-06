"""Offline subprocess and orchestration tests for the Codex CLI adapter."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest

from .codex_cli_provider import (DEFAULT_CODEX_DEADLINE_SECONDS,
                                 DISABLED_TOOL_FEATURES,
                                 MAX_DIAGNOSTIC_BYTES,
                                MAX_EVENT_STREAM_BYTES,
                                CodexCliConfig, CodexCliProvider)
from .contracts import GenerationStatus
from .orchestrator import GenerationOrchestrator, OrchestrationStatus
from .prompt import PromptCompiler
from .provider_contracts import FailureCode
from .providers import AdapterKind, ProviderCallStatus
from .runner import GenerationRunner
from .storage import GenerationStore


_FAKE_CLI = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import time

args = sys.argv[1:]
report_path = None
mode = None
if args and args[0] == "--fake-report":
    report_path = Path(args[1])
    args = args[2:]
if args and args[0] == "--fake-mode":
    mode = args[1]
    args = args[2:]

if args == ["--version"]:
    print("codex-cli 0.159.0-test")
    raise SystemExit(0)
if args == ["--help"]:
    print("--model --sandbox" +
          ("" if mode == "no-approval" else " --ask-for-approval"))
    raise SystemExit(0)
if args == ["exec", "--help"]:
    print("--model --sandbox --cd --skip-git-repo-check --ephemeral "
          "--ignore-user-config --ignore-rules --output-schema "
          "--output-last-message --json --color --disable stdin")
    raise SystemExit(0)
if args == ["login", "status"]:
    print("Logged in using " + ("API key" if mode == "api-login" else "ChatGPT"),
          file=sys.stderr)
    raise SystemExit(0)
if args and args[-2:] == ["features", "list"]:
    disabled = [args[i + 1] for i, item in enumerate(args[:-1])
                if item == "--disable"]
    for feature in disabled:
        if not (mode == "missing-shell-disable" and feature == "shell_tool"):
            print(f"{feature} stable false")
    raise SystemExit(0)

assert "exec" in args, args
def option(name):
    index = args.index(name)
    return args[index + 1]

schema_path = Path(option("--output-schema"))
result_path = Path(option("--output-last-message"))
prompt_bytes = sys.stdin.buffer.read()
prompt = prompt_bytes.decode("utf-8", "replace")
case = "valid"
for candidate in ("nonzero-auth", "nonzero-quota", "nonzero-refusal", "missing",
                  "malformed", "invalid-utf8", "oversized", "stdout-flood",
                  "stderr-flood", "hang", "child-hang", "extra-file",
                  "unknown-usage", "policy-denied"):
    if "FAKE_CASE=" + candidate in prompt:
        case = candidate
        break

record = {
    "argv": args,
    "cwd": os.getcwd(),
    "prompt": prompt,
    "workspace_entries": sorted(os.listdir(os.getcwd())),
    "schema_exists": schema_path.is_file(),
    "schema_top_fields": sorted(json.loads(schema_path.read_text()).get("properties", {})),
    "secret_env_present": {
        key: key in os.environ
        for key in ("OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "DATABASE_URL")
    },
    "codex_home_present": "CODEX_HOME" in os.environ,
}
if case == "extra-file":
    Path.cwd().joinpath("unexpected.tmp").write_text("fake child artifact")
if case == "child-hang":
    marker = prompt.split("FAKE_CHILD_MARKER=", 1)[1].splitlines()[0]
    child_code = (
        "import pathlib,time,sys; p=pathlib.Path(sys.argv[1]); "
        "\nwhile True:\n p.open('a').write('x')\n time.sleep(.04)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", child_code, marker])
    record["child_pid"] = child.pid
if report_path:
    with report_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")

events = {"type": "turn.started", "model": "gpt-codex-test"}
if case == "unknown-usage":
    completed = {"type": "turn.completed"}
else:
    completed = {"type": "turn.completed", "usage": {
        "input_tokens": 7, "output_tokens": 5, "total_tokens": 12}}

if case in {"nonzero-auth", "nonzero-quota", "nonzero-refusal"}:
    code = {"nonzero-auth": "authentication_required",
            "nonzero-quota": "rate_limit_exceeded",
            "nonzero-refusal": "refusal"}[case]
    print(json.dumps({"type": "turn.failed", "error": {"code": code}}))
    raise SystemExit(23)
if case == "stdout-flood":
    sys.stdout.buffer.write(b"x" * (1024 * 1024 + 8192))
    sys.stdout.buffer.flush()
    time.sleep(30)
if case == "stderr-flood":
    sys.stderr.buffer.write(b"d" * (64 * 1024 + 8192))
    sys.stderr.buffer.flush()
if case in {"hang", "child-hang"}:
    while True:
        time.sleep(0.1)

print(json.dumps(events))
if case not in {"unknown-usage"}:
    print(json.dumps(completed))
if case == "missing":
    raise SystemExit(0)
if case == "malformed":
    result_path.write_bytes(b"{")
elif case == "invalid-utf8":
    result_path.write_bytes(b"\xff")
elif case == "oversized":
    result_path.write_bytes(b" " * (1024 * 1024 + 1))
else:
    payload = {
        "schema_version": 1,
        "intent": "A simple block.",
        "assumptions": [],
        "approximations": [],
        "required_components": ["body"],
        "recipe": {"version": 1, "name": "fake_codex",
                   "objects": [{"name": "body", "primitive": "box"}]},
    }
    if case == "policy-denied":
        payload["recipe"]["exports"] = [
            {"format": "obj", "path": "../escape.obj"}]
    result_path.write_text(json.dumps(payload, separators=(",", ":")),
                           encoding="utf-8")
raise SystemExit(0)
'''


def _harness(tmp_path: Path, *, mode="normal", model=None, deadline=2.0):
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "fake_codex_cli.py"
    script.write_text(_FAKE_CLI, encoding="utf-8")
    report = tmp_path / "invocations.jsonl"
    config = CodexCliConfig(executable=sys.executable, model=model,
                            deadline_seconds=deadline)
    provider = CodexCliProvider(
        config, argv_prefix_for_tests=(str(script), "--fake-report", str(report),
                                       "--fake-mode", mode))
    if mode not in {"api-login", "no-approval", "missing-shell-disable"}:
        assert provider.ready, provider._setup_message
    return provider, script, report


def _request(case="valid", *, deadline=2.0, extra=""):
    brief = f"FAKE_CASE={case}\n{extra}".strip()
    request = PromptCompiler().compile(brief)
    from dataclasses import replace
    return replace(request, deadline_seconds=deadline)


def _read_report(report: Path):
    lines = report.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_codex_request_uses_fixed_argv_empty_cwd_stdin_and_host_schema(tmp_path,
                                                                       monkeypatch):
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(
        'sandbox_mode = "danger-full-access"\nmodel = "untrusted-model"\n',
        encoding="utf-8")
    (codex_home / "untrusted.rules").write_text(
        "allow all tools\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("OPENAI_API_KEY", "SENTINEL_SHOULD_NOT_LEAK")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "SENTINEL_SHOULD_NOT_LEAK")
    monkeypatch.setenv("DATABASE_URL", "SENTINEL_SHOULD_NOT_LEAK")
    provider, _script, report = _harness(tmp_path, model="gpt-codex-test")
    spawned = []
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        spawned.append({"shell": kwargs.get("shell"),
                        "cwd": str(kwargs.get("cwd"))})
        return real_popen(*args, **kwargs)

    with patch("am3d.ai.codex_cli_provider.subprocess.Popen", recording_popen):
        result = provider.generate(_request())

    assert result.status is ProviderCallStatus.SUCCEEDED
    assert result.adapter_kind is AdapterKind.AGENT_CLI
    assert result.provider_id == "openai/codex"
    assert result.model_id == "gpt-codex-test"
    assert result.usage.input_tokens == 7
    assert result.usage.output_tokens == 5
    assert result.usage.total_tokens == 12
    assert result.latency_ms is not None and result.latency_ms >= 0
    call, = _read_report(report)
    argv = call["argv"]
    assert argv[:4] == ["--ask-for-approval", "never", "exec", "--model"]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("--cd") + 1] == call["cwd"]
    assert argv[-1] == "-"
    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    disabled = [argv[i + 1] for i, item in enumerate(argv[:-1])
                if item == "--disable"]
    assert disabled == list(DISABLED_TOOL_FEATURES)
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    assert "FAKE_CASE=valid" in call["prompt"]
    assert "FAKE_CASE=valid" not in argv
    assert call["schema_exists"]
    assert call["schema_top_fields"] == [
        "approximations", "assumptions", "intent", "recipe",
        "required_components", "schema_version"]
    assert call["workspace_entries"] == ["response.schema.json", "tmp"]
    assert provider.last_workspace_entries == (
        "final-response.json", "response.schema.json", "tmp")
    assert all(not present for present in call["secret_env_present"].values())
    assert call["codex_home_present"]
    assert "SENTINEL_SHOULD_NOT_LEAK" not in report.read_text(encoding="utf-8")
    assert provider.last_event_kinds == ("turn.started", "turn.completed")
    assert spawned == [{"shell": False, "cwd": call["cwd"]}]
    assert not Path(call["cwd"]).exists()


def test_codex_rejects_unexpected_workspace_artifacts(tmp_path):
    provider, _script, report = _harness(tmp_path)
    result = provider.generate(_request("extra-file"))
    assert result.status is ProviderCallStatus.FAILED
    assert result.failure_code is FailureCode.TRANSPORT_FAILURE
    assert result.transport_status == "unexpected_workspace_artifact"
    assert provider.last_workspace_entries == (
        "final-response.json", "response.schema.json", "tmp",
        "unexpected.tmp")
    assert len(_read_report(report)) == 1


@pytest.mark.parametrize(("case", "expected"), [
    ("nonzero-auth", FailureCode.AUTHENTICATION_FAILURE),
    ("nonzero-quota", FailureCode.QUOTA_RATE_LIMIT),
    ("nonzero-refusal", FailureCode.REFUSAL),
    ("missing", FailureCode.INVALID_STRUCTURED_RESPONSE),
    ("oversized", FailureCode.RESPONSE_TOO_LARGE),
])
def test_codex_process_failures_are_typed_and_one_exec_only(tmp_path, case, expected):
    provider, _script, report = _harness(tmp_path)
    result = provider.generate(_request(case))
    assert result.status is ProviderCallStatus.FAILED
    assert result.failure_code is expected
    assert len(_read_report(report)) == 1
    assert result.response_bytes is None
    if expected is FailureCode.QUOTA_RATE_LIMIT:
        assert result.quota_or_rate_limited is True
    assert result.usage.input_tokens is None or result.usage.input_tokens == 7


@pytest.mark.parametrize("case", ["malformed", "invalid-utf8"])
def test_raw_codex_output_still_goes_through_m31_parser_and_no_runner(tmp_path,
                                                                      case):
    provider, _script, _report = _harness(tmp_path)

    class RunnerSpy:
        running = False
        store = type("Store", (), {"private": tmp_path / "private"})()
        start_calls = 0
        last_result = None

        def start(self, _recipe):
            self.start_calls += 1
            raise AssertionError("bad provider result reached runner")

    runner = RunnerSpy()
    outcome = GenerationOrchestrator(provider, runner).start(f"FAKE_CASE={case}")
    assert outcome.status is OrchestrationStatus.FAILED
    assert outcome.failure_code is (
        FailureCode.MALFORMED_JSON if case == "malformed"
        else FailureCode.INVALID_UTF8)
    assert runner.start_calls == 0


def test_codex_policy_denial_never_starts_generation_runner(tmp_path):
    class RunnerSpy:
        running = False
        store = type("Store", (), {"private": tmp_path / "private"})()
        start_calls = 0
        last_result = None

        def start(self, _recipe):
            self.start_calls += 1
            raise AssertionError("policy-denied recipe reached runner")

    provider, _script, report = _harness(tmp_path)
    runner = RunnerSpy()
    outcome = GenerationOrchestrator(provider, runner).start(
        "FAKE_CASE=policy-denied")
    assert outcome.status is OrchestrationStatus.FAILED
    assert outcome.failure_code is FailureCode.POLICY_REJECTION
    assert runner.start_calls == 0
    assert len(_read_report(report)) == 1


@pytest.mark.parametrize(("case", "expected"), [
    ("nonzero-auth", FailureCode.AUTHENTICATION_FAILURE),
    ("nonzero-quota", FailureCode.QUOTA_RATE_LIMIT),
    ("nonzero-refusal", FailureCode.REFUSAL),
])
def test_auth_quota_and_refusal_never_start_m2(tmp_path, case, expected):
    class RunnerSpy:
        running = False
        store = type("Store", (), {"private": tmp_path / "private"})()
        start_calls = 0
        last_result = None

        def start(self, _recipe):
            self.start_calls += 1
            raise AssertionError("failed provider reached runner")

    provider, _script, report = _harness(tmp_path)
    runner = RunnerSpy()
    outcome = GenerationOrchestrator(provider, runner).start(f"FAKE_CASE={case}")
    assert outcome.failure_code is expected
    assert runner.start_calls == 0
    assert len(_read_report(report)) == 1


def test_orchestrator_cancel_terminates_provider_and_prevents_stale_run(tmp_path):
    provider, _script, report = _harness(tmp_path, deadline=4.0)
    marker = tmp_path / "orchestrator-child-marker"
    runner = GenerationRunner(GenerationStore(tmp_path / "app-data"))
    orchestrator = GenerationOrchestrator(provider, runner)
    outcomes = []
    thread = threading.Thread(target=lambda: outcomes.append(
        orchestrator.start(
            f"FAKE_CASE=child-hang\nFAKE_CHILD_MARKER={marker}")))
    thread.start()
    wait_until = time.monotonic() + 3
    while time.monotonic() < wait_until and not marker.exists():
        time.sleep(0.02)
    assert marker.exists()
    assert orchestrator.cancel()
    thread.join(timeout=5)
    assert not thread.is_alive()
    result, = outcomes
    assert result.status is OrchestrationStatus.FAILED
    assert result.failure_code is FailureCode.CANCELLED
    assert result.usage.failure_classification == FailureCode.CANCELLED.value
    assert not runner.running
    assert not runner.store.generations.exists()
    assert len(_read_report(report)) == 1
    size = marker.stat().st_size
    time.sleep(0.2)
    assert marker.stat().st_size == size


def test_cancel_during_prompt_compilation_prevents_provider_launch(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    class BlockingCompiler:
        def compile(self, brief):
            entered.set()
            assert release.wait(timeout=3)
            return PromptCompiler().compile(brief)

    provider, _script, report = _harness(tmp_path)
    runner = GenerationRunner(GenerationStore(tmp_path / "app-data"))
    orchestrator = GenerationOrchestrator(
        provider, runner, prompt_compiler=BlockingCompiler())
    outcomes = []
    thread = threading.Thread(target=lambda: outcomes.append(
        orchestrator.start("A simple stool.")))
    thread.start()
    assert entered.wait(timeout=2)
    assert orchestrator.cancel()
    release.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert outcomes[0].failure_code is FailureCode.CANCELLED
    assert provider.last_workspace_entries == ()
    assert not report.exists()
    assert not runner.running


def test_valid_codex_recipe_reaches_the_existing_m2_runner(tmp_path):
    provider, _script, report = _harness(tmp_path)
    runner = GenerationRunner(GenerationStore(tmp_path / "app-data"))
    orchestrator = GenerationOrchestrator(provider, runner)
    outcome = orchestrator.start("FAKE_CASE=valid")
    assert outcome.status is OrchestrationStatus.RUNNING
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        outcome = orchestrator.poll()
        if outcome is not None and outcome.status is not OrchestrationStatus.RUNNING:
            break
        time.sleep(0.025)
    assert outcome.status is OrchestrationStatus.COMPLETE
    assert outcome.generation_result.status is GenerationStatus.COMPLETE
    assert all(check.ok for check in outcome.generation_result.checks)
    assert len(_read_report(report)) == 1


def test_codex_unknown_usage_and_host_latency_are_truthful(tmp_path):
    provider, _script, _report = _harness(tmp_path)
    result = provider.generate(_request("unknown-usage"))
    assert result.status is ProviderCallStatus.SUCCEEDED
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert result.usage.total_tokens is None
    assert result.latency_ms is not None and result.latency_ms >= 0


def test_missing_unsupported_or_api_key_codex_fails_before_exec(tmp_path):
    missing = CodexCliProvider(CodexCliConfig(executable=str(tmp_path / "missing")))
    assert missing.generate(_request()).failure_code is FailureCode.UNAVAILABLE_PROVIDER

    api_login, _script, report = _harness(tmp_path / "api", mode="api-login")
    assert not api_login.ready
    assert api_login._setup_failure is FailureCode.AUTHENTICATION_FAILURE
    failed = api_login.generate(_request())
    assert failed.failure_code is FailureCode.AUTHENTICATION_FAILURE
    assert not report.exists()

    bad_help, _script, report2 = _harness(tmp_path / "bad-help", mode="no-approval")
    assert not bad_help.ready
    assert bad_help._setup_failure is FailureCode.UNSUPPORTED_ADAPTER
    assert not report2.exists()

    bad_feature, _script, report3 = _harness(
        tmp_path / "bad-feature", mode="missing-shell-disable")
    assert not bad_feature.ready
    assert bad_feature._setup_failure is FailureCode.UNSUPPORTED_ADAPTER
    assert not report3.exists()


@pytest.mark.parametrize("case", ["stdout-flood", "stderr-flood"])
def test_event_and_diagnostic_streams_are_bounded(tmp_path, case):
    provider, _script, report = _harness(tmp_path)
    result = provider.generate(_request(case, deadline=3.0))
    assert len(_read_report(report)) == 1
    if case == "stdout-flood":
        assert result.status is ProviderCallStatus.FAILED
        assert result.failure_code is FailureCode.RESPONSE_TOO_LARGE
    else:
        assert result.status is ProviderCallStatus.SUCCEEDED
    assert not hasattr(result, "stdout")
    assert not hasattr(result, "stderr")


def test_codex_deadline_terminates_process_and_returns_timeout(tmp_path):
    provider, _script, report = _harness(tmp_path, deadline=0.25)
    started = time.monotonic()
    result = provider.generate(_request("hang", deadline=0.25))
    assert result.failure_code is FailureCode.TIMEOUT
    assert time.monotonic() - started < 4
    assert len(_read_report(report)) == 1


def test_cancel_kills_codex_process_tree_and_never_returns_a_recipe(tmp_path):
    provider, _script, report = _harness(tmp_path, deadline=4.0)
    marker = tmp_path / "child-live-marker"
    outcomes = []
    thread = threading.Thread(
        target=lambda: outcomes.append(provider.generate(
            _request("child-hang", deadline=4.0,
                     extra=f"FAKE_CHILD_MARKER={marker}"))))
    thread.start()
    wait_until = time.monotonic() + 3
    while time.monotonic() < wait_until and not marker.exists():
        time.sleep(0.02)
    assert marker.exists()
    assert provider.cancel()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert outcomes[0].failure_code is FailureCode.CANCELLED
    before = marker.stat().st_size
    time.sleep(0.25)
    after = marker.stat().st_size
    assert before == after
    assert len(_read_report(report)) == 1


def test_request_schema_cannot_be_changed_by_the_adapter_caller(tmp_path):
    from dataclasses import replace

    provider, _script, report = _harness(tmp_path)
    request = _request()
    changed_schema = dict(request.response_schema)
    changed_schema["additionalProperties"] = True
    result = provider.generate(replace(request, response_schema=changed_schema))
    assert result.failure_code is FailureCode.UNSUPPORTED_ADAPTER
    assert not report.exists()


def test_host_default_uses_ten_minutes_and_no_config_escape_hatch():
    config = CodexCliConfig(executable="codex")
    assert config.deadline_seconds == DEFAULT_CODEX_DEADLINE_SECONDS
    assert config.model is None
    assert not hasattr(config, "reasoning_effort")
