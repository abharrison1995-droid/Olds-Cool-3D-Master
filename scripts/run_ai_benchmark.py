#!/usr/bin/env python3
"""Run or inspect the frozen V1 AI benchmark without making default network calls."""

from __future__ import annotations

import argparse
from copy import deepcopy
import getpass
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlsplit
import uuid


if os.name == "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from am3d.ai import benchmark


DEFAULT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_OFFLINE_MODEL = "offline-refusal-v1"
DEFAULT_OFFLINE_CALLS = 150
LIVE_ACK = "RUN V1 LIVE BENCHMARK"
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SECRET_MODEL_RE = re.compile(r"(?i)^(?:sk|key|token)[-_][A-Za-z0-9_-]{12,}$")


class RunInputError(ValueError):
    """A sanitized runner configuration error."""


class ReplayProvider:
    """Deterministic offline fake provider; never creates a transport."""

    def __init__(self, *, model: str, replay: dict | None = None) -> None:
        self.model = model
        self.replay = replay or {}
        self.case_id: str | None = None
        self.cursor = 0

    def set_case(self, fixture_id: str) -> None:
        self.case_id = fixture_id
        self.cursor = 0

    def generate(self, request, deadline, cancellation):
        from am3d.ai.contracts import ProviderError, ProviderResponse, ProviderUsage

        if cancellation.cancelled:
            raise ProviderError("offline fake provider request cancelled")
        entries = self.replay.get(self.case_id or "", [])
        if self.cursor >= len(entries):
            if self.replay:
                raise ProviderError("offline replay has no response for this semantic call")
            return ProviderResponse(
                provider="offline-fake", model=self.model, request_id=None,
                json_text=None, json_data=None, usage=ProviderUsage(),
                finish_reason="content_filter", refused=True,
            )
        entry = entries[self.cursor]
        self.cursor += 1
        if entry.get("purpose") not in (None, request.purpose):
            raise ProviderError("offline replay request purpose does not match")
        usage_value = entry.get("usage", {})
        usage = ProviderUsage(
            prompt_tokens=usage_value.get("prompt_tokens"),
            completion_tokens=usage_value.get("completion_tokens"),
            total_tokens=usage_value.get("total_tokens"),
            cost_usd=usage_value.get("cost_usd"),
        )
        data = deepcopy(entry.get("json_data"))
        return ProviderResponse(
            provider="offline-replay", model=self.model, request_id=None,
            json_text=None, json_data=data, usage=usage,
            finish_reason=entry.get("finish_reason", "stop"),
            refused=entry.get("refused", False),
        )


class BudgetedProvider:
    """Account semantic requests and reserve their maximum completion output."""

    def __init__(self, provider, *, max_calls: int, output_token_budget: int,
                 initial_calls: int = 0, initial_output_tokens: int = 0) -> None:
        self.provider = provider
        self.max_calls = max_calls
        self.output_token_budget = output_token_budget
        self.semantic_call_attempts = initial_calls
        self.semantic_calls_forwarded = initial_calls
        self.output_tokens_reserved = initial_output_tokens
        self.budget_stop_reason: str | None = None
        self.item_semantic_call_attempts = 0
        self.item_semantic_calls_forwarded = 0
        self.item_output_tokens_reserved = 0
        self.item_usage: dict[str, list[int | float | None]] = {
            "prompt_tokens": [], "completion_tokens": [],
            "total_tokens": [], "cost_usd": [],
        }
        self.item_budget_stop_reason: str | None = None
        self.on_progress = None

    def set_case(self, fixture_id: str, on_progress=None) -> None:
        setter = getattr(self.provider, "set_case", None)
        if callable(setter):
            setter(fixture_id)
        self.item_semantic_call_attempts = 0
        self.item_semantic_calls_forwarded = 0
        self.item_output_tokens_reserved = 0
        self.item_budget_stop_reason = None
        self.item_usage = {"prompt_tokens": [], "completion_tokens": [],
                           "total_tokens": [], "cost_usd": []}
        self.on_progress = on_progress

    def snapshot(self) -> dict:
        return {
            "semantic_call_attempts": self.semantic_call_attempts,
            "semantic_calls_forwarded": self.semantic_calls_forwarded,
            "output_tokens_reserved": self.output_tokens_reserved,
            "budget_stop_reason": self.budget_stop_reason,
        }

    def delta(self, before: dict) -> dict:
        after = self.snapshot()
        return {
            "semantic_call_attempts": after["semantic_call_attempts"] - before["semantic_call_attempts"],
            "semantic_calls_forwarded": after["semantic_calls_forwarded"] - before["semantic_calls_forwarded"],
            "output_tokens_reserved": after["output_tokens_reserved"] - before["output_tokens_reserved"],
            "budget_stop_reason": after["budget_stop_reason"],
        }

    def _progress_snapshot(self) -> dict:
        def total(values):
            return (None if not values or any(value is None for value in values)
                    else sum(values))
        return {
            "semantic_call_attempts": self.item_semantic_call_attempts,
            "semantic_calls_forwarded": self.item_semantic_calls_forwarded,
            "output_tokens_reserved": self.item_output_tokens_reserved,
            "budget_stop_reason": self.item_budget_stop_reason,
            "usage": {name: total(values) for name, values in self.item_usage.items()},
        }

    def _save_progress(self, stage: str) -> None:
        if callable(self.on_progress):
            self.on_progress(stage, self._progress_snapshot(), self.snapshot())

    def generate(self, request, deadline, cancellation):
        from am3d.ai.contracts import ProviderRequestError

        self.semantic_call_attempts += 1
        self.item_semantic_call_attempts += 1
        if self.semantic_calls_forwarded >= self.max_calls:
            self.budget_stop_reason = "semantic_call_budget_exhausted"
            self.item_budget_stop_reason = self.budget_stop_reason
            self._save_progress("budget_rejected")
            raise ProviderRequestError("The benchmark semantic-call ceiling was reached.")
        reservation = request.output_token_limit
        if type(reservation) is not int or reservation <= 0:
            self.budget_stop_reason = "completion_output_token_limit_missing"
            self.item_budget_stop_reason = self.budget_stop_reason
            self._save_progress("budget_rejected")
            raise ProviderRequestError("The benchmark request has no bounded completion-output limit.")
        if self.output_tokens_reserved + reservation > self.output_token_budget:
            self.budget_stop_reason = "completion_output_token_budget_exhausted"
            self.item_budget_stop_reason = self.budget_stop_reason
            self._save_progress("budget_rejected")
            raise ProviderRequestError("The benchmark completion-output reservation ceiling was reached.")
        self.semantic_calls_forwarded += 1
        self.item_semantic_calls_forwarded += 1
        self.output_tokens_reserved += reservation
        self.item_output_tokens_reserved += reservation
        # Persist the request count and full completion reservation before the
        # provider can perform any network IO. A process restart therefore
        # cannot accidentally spend the same allowance a second time.
        self._save_progress("reserved")
        response = self.provider.generate(request, deadline, cancellation)
        usage = getattr(response, "usage", None)
        for name in self.item_usage:
            self.item_usage[name].append(getattr(usage, name, None))
        self._save_progress("response")
        completion_tokens = getattr(usage, "completion_tokens", None)
        if type(completion_tokens) is int and completion_tokens > reservation:
            self.budget_stop_reason = "provider_output_exceeded_reserved_completion_limit"
            self.item_budget_stop_reason = self.budget_stop_reason
            self._save_progress("provider_budget_violation")
            raise ProviderRequestError(
                "The provider reported completion usage above the reserved request limit.")
        return response


def _load_replay(path: str | None, fixture_ids: tuple[str, ...]) -> tuple[dict, str | None]:
    if path is None:
        return {}, None
    try:
        raw = Path(path).read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_replay_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise RunInputError("offline replay file could not be read as UTF-8 JSON") from None
    if not isinstance(value, dict) or set(value) != {"schema_version", "cases"}:
        raise RunInputError("offline replay file has an invalid top-level schema")
    if value.get("schema_version") != 1 or not isinstance(value.get("cases"), dict):
        raise RunInputError("offline replay file has an unsupported schema")
    cases = value["cases"]
    if set(cases) - set(fixture_ids):
        raise RunInputError("offline replay contains an unknown fixture ID")
    allowed_entry = {"purpose", "json_data", "refused", "finish_reason", "usage"}
    allowed_usage = {"prompt_tokens", "completion_tokens", "total_tokens", "cost_usd"}
    for fixture_id, entries in cases.items():
        if not isinstance(entries, list) or len(entries) > 5:
            raise RunInputError("offline replay response count exceeds the per-item call ceiling")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - allowed_entry:
                raise RunInputError("offline replay response has unsupported fields")
            if type(entry.get("refused", False)) is not bool:
                raise RunInputError("offline replay refusal flag must be boolean")
            if entry.get("finish_reason", "stop") not in {"stop", "length", "content_filter"}:
                raise RunInputError("offline replay completion status is unsupported")
            if "json_data" in entry and not isinstance(entry["json_data"], dict):
                raise RunInputError("offline replay structured content must be an object")
            usage = entry.get("usage", {})
            if not isinstance(usage, dict) or set(usage) - allowed_usage:
                raise RunInputError("offline replay usage fields are invalid")
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                item = usage.get(name)
                if item is not None and (type(item) is not int or item < 0):
                    raise RunInputError("offline replay token usage must be a non-negative integer or null")
            cost = usage.get("cost_usd")
            if cost is not None and (type(cost) not in {int, float}
                                     or not math.isfinite(cost) or cost < 0):
                raise RunInputError("offline replay cost must be non-negative or null")
    return cases, benchmark.sha256_bytes(raw)


def _reject_replay_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate replay key")
        result[key] = value
    return result


def _safe_model(model: str | None) -> str:
    if not isinstance(model, str) or not _MODEL_RE.fullmatch(model) or _SECRET_MODEL_RE.fullmatch(model):
        raise RunInputError("an explicit safe model identifier is required")
    return model


def _provider_info(*, mode: str, model: str | None = None,
                   endpoint: str = DEFAULT_ENDPOINT, credential_source: str = "system",
                   credential_alias: str = "default", allow_host: str | None = None) -> tuple[dict, object | None]:
    if mode in {"fake", "replay"}:
        offline_model = _safe_model(model) if model else (
            "offline-replay-v1" if mode == "replay" else DEFAULT_OFFLINE_MODEL)
        return {"provider_id": "offline-replay" if mode == "replay" else "offline-fake",
                "model": offline_model,
                "endpoint_host": None, "endpoint_path": None,
                "credential_source": None}, None
    model = _safe_model(model)
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname
        if (not host or parsed.scheme.lower() != "https"
                or parsed.port not in (None, 443)
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or "?" in endpoint
                or "#" in endpoint
                or any(char.isspace() or ord(char) < 32 for char in endpoint)):
            raise ValueError
    except (TypeError, ValueError):
        raise RunInputError("provider endpoint must be a safe HTTPS URL on port 443") from None
    endpoint_host = host.encode("idna").decode("ascii").lower()
    endpoint_path = parsed.path or "/"
    allowed_host = allow_host or ("api.openai.com" if endpoint == DEFAULT_ENDPOINT else None)
    if not allowed_host or allowed_host.encode("idna").decode("ascii").lower() != endpoint_host:
        raise RunInputError("a custom provider endpoint requires an exact explicit allow-host value")
    if credential_source not in {"system", "session"}:
        raise RunInputError("credential source must be system or session")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", credential_alias):
        raise RunInputError("credential alias has an invalid format")
    provider_data = {
        "provider_id": "openai-compatible",
        "model": model,
        "endpoint_host": endpoint_host,
        "endpoint_path": endpoint_path,
        "endpoint_sha256": benchmark.sha256_bytes(endpoint.encode("utf-8")),
        "credential_source": credential_source,
        "credential_alias": credential_alias,
    }
    return provider_data, None


def _live_provider(args, endpoint: str, allowed_host: str):
    from am3d.ai.contracts import ProviderConfig, ProviderCredentialError
    from am3d.ai.credentials import SessionCredentialStore, SystemCredentialStore
    from am3d.ai.providers import OpenAICompatibleProvider

    if args.credential_source == "session":
        store = SessionCredentialStore()
        secret = getpass.getpass("Provider API key (input hidden; kept in this process only): ")
        try:
            store.set(args.credential_alias, secret)
        except Exception:
            raise RunInputError("session credential input was rejected") from None
    else:
        try:
            store = SystemCredentialStore()
            secret = store.get(args.credential_alias)
        except Exception:
            raise RunInputError("system credential store is unavailable or locked") from None
        if not secret:
            raise RunInputError("no saved credential exists for the selected system credential alias")
    # Keep the secret only in the credential-store object and provider call
    # boundary. Never print, serialize, hash, or place it in process arguments.
    del secret
    config = ProviderConfig(model=_safe_model(args.model), endpoint=endpoint,
                           credential_alias=args.credential_alias,
                           allowed_hosts=(allowed_host,))
    try:
        return OpenAICompatibleProvider(config, store)
    except Exception:
        raise RunInputError("provider configuration did not pass the adapter trust boundary") from None


def _live_preflight(*, scope: str, model: str, max_calls: int,
                    output_budget: int, http_upper_bound: int) -> None:
    print("LIVE BENCHMARK PREFLIGHT")
    print(f"Scope: {scope}; frozen items: {30 if scope == 'release' else 8}.")
    print(f"Configured model identifier: {model}.")
    print(f"Semantic call ceiling: {max_calls}; conservative HTTP upper bound: {http_upper_bound}.")
    print(f"Reserved completion output ceiling: {output_budget} tokens.")
    print(benchmark._COST_DISCLOSURE)
    print("Input/prompt tokens and dollar spend cannot be bounded. Actual cost will be unknown unless returned by the provider.")
    if not sys.stdin.isatty():
        raise RunInputError("live preflight requires an interactive acknowledgement")
    response = input(f"Type {LIVE_ACK} to make these live provider calls: ")
    if response != LIVE_ACK:
        raise RunInputError("live benchmark was not acknowledged")


def _default_output_parent() -> Path:
    local_data = os.environ.get("LOCALAPPDATA")
    if local_data:
        return Path(local_data) / "3D-MASTER-2005" / "V1-Benchmark"
    return Path(tempfile.gettempdir()) / "3D-MASTER-2005" / "V1-Benchmark"


def _validated_output_parent(requested: str | None) -> Path:
    private_root = benchmark.assert_no_links(_default_output_parent())
    if requested is None:
        return private_root
    candidate = benchmark.assert_no_links(Path(requested).expanduser())
    try:
        candidate.relative_to(private_root)
    except ValueError:
        raise RunInputError("output parent must be inside the per-user benchmark directory") from None
    return candidate


def _counters_for(outcome, wrapper: BudgetedProvider, before: dict) -> dict:
    delta = wrapper.delta(before)
    local = wrapper._progress_snapshot()
    return {
        "semantic_calls_forwarded": local["semantic_calls_forwarded"],
        "semantic_call_attempts": local["semantic_call_attempts"],
        "output_tokens_reserved": local["output_tokens_reserved"],
        "budget_stop_reason": local["budget_stop_reason"] or delta["budget_stop_reason"],
        "usage": local["usage"],
    }


def _run_inputs_match(repo_root: Path, manifest: dict, replay_file: str | None) -> bool:
    if not benchmark.frozen_inputs_match(repo_root, manifest):
        return False
    if manifest.get("mode") == "replay":
        try:
            return bool(replay_file and benchmark.sha256_file(replay_file)
                        == manifest.get("replay_sha256"))
        except OSError:
            return False
    return True


def _item_progress_callback(journal: dict, item: dict, run_root: Path):
    def persist(_stage: str, local: dict, global_counts: dict) -> None:
        http_limit = journal["manifest"]["limits"]["max_http_attempts_per_semantic_call"]
        item["provider_calls"] = {
            "semantic_calls": local["semantic_calls_forwarded"],
            "semantic_call_attempts": local["semantic_call_attempts"],
            "http_attempts_actual": None,
            "http_attempts_upper_bound": local["semantic_calls_forwarded"] * http_limit,
            "completion_output_tokens_reserved": local["output_tokens_reserved"],
            "budget_stop_reason": local["budget_stop_reason"],
            "run_http_attempt_ceiling": journal["manifest"]["limits"]["http_attempts_conservative_upper_bound"],
        }
        item["usage"].update(local["usage"])
        journal["totals"]["semantic_calls"] = global_counts["semantic_calls_forwarded"]
        journal["totals"]["completion_output_tokens_reserved"] = global_counts["output_tokens_reserved"]
        journal["totals"]["http_attempts_actual"] = None
        journal["totals"]["http_attempts_upper_bound"] = global_counts["semantic_calls_forwarded"] * http_limit
        benchmark.refresh_totals(journal)
        benchmark.persist_journal(run_root, journal)
    return persist


def _mark_input_drift(journal: dict, first_pending_id: str | None) -> None:
    for item in journal["items"]:
        if item["id"] == first_pending_id or item["status"] == "pending":
            item["status"] = "not_run_input_drift"
            item["completed_utc"] = benchmark.utc_now()
            item["failure_class"] = "frozen_input_drift"
            item["failure_code"] = "frozen_input_identity_changed"
            item["deterministic_pass"] = False


def execute_pending(repo_root: Path, run_root: Path, journal: dict,
                    wrapped_provider: BudgetedProvider,
                    replay_file: str | None = None) -> dict:
    from am3d.ai.orchestrator import GenerationOrchestrator
    from am3d.ai.records import GenerationRecordStore

    fixtures = benchmark.load_fixture_set(repo_root, journal["manifest"]["scope"])[1]
    fixture_by_id = {fixture["id"]: fixture for fixture in fixtures}
    if not _run_inputs_match(repo_root, journal["manifest"], replay_file):
        first_pending = next((item["id"] for item in journal["items"]
                              if item["status"] in {"pending", "running"}), None)
        _mark_input_drift(journal, first_pending)
        journal["status"] = "aborted_input_drift"
        journal["completed_utc"] = benchmark.utc_now()
        benchmark.refresh_totals(journal)
        benchmark.persist_journal(run_root, journal)
        return journal
    store = GenerationRecordStore(run_root / "store")
    store.recover_interrupted()
    orchestrator = GenerationOrchestrator(wrapped_provider, store)
    journal["status"] = "running"
    if not journal.get("started_utc"):
        journal["started_utc"] = benchmark.utc_now()
    benchmark.persist_journal(run_root, journal)
    try:
        for item in journal["items"]:
            if item["status"] != "pending":
                continue
            if not _run_inputs_match(repo_root, journal["manifest"], replay_file):
                _mark_input_drift(journal, item["id"])
                journal["status"] = "aborted_input_drift"
                journal["completed_utc"] = benchmark.utc_now()
                break
            fixture = fixture_by_id[item["id"]]
            item["status"] = "running"
            item["started_utc"] = benchmark.utc_now()
            benchmark.persist_journal(run_root, journal)
            item["failure_class"] = None
            item["failure_code"] = None
            wrapped_provider.set_case(
                item["id"],
                on_progress=_item_progress_callback(journal, item, run_root),
            )
            before = wrapped_provider.snapshot()
            start = time.perf_counter()
            try:
                outcome = orchestrator.generate(
                    fixture["prompt"], requirements=benchmark.fixture_requirements(fixture),
                    run_id=str(uuid.uuid4()),
                )
            except KeyboardInterrupt:
                item["status"] = "running"
                item["failure_class"] = "interrupted"
                item["failure_code"] = "process_interrupted"
                benchmark.persist_journal(run_root, journal)
                raise
            wall_seconds = max(0.0, time.perf_counter() - start)
            benchmark.apply_outcome(
                journal, item["id"], outcome,
                provider_stats=_counters_for(outcome, wrapped_provider, before),
                wall_seconds=wall_seconds, run_root=run_root, fixture=fixture,
            )
            benchmark.persist_journal(run_root, journal)
            if not _run_inputs_match(repo_root, journal["manifest"], replay_file):
                item["status"] = "failed_input_drift"
                item["failure_class"] = "frozen_input_drift"
                item["failure_code"] = "frozen_input_identity_changed_during_item"
                item["deterministic_pass"] = False
                item["integrity"]["frozen_inputs_match"] = False
                for later in journal["items"]:
                    if later["status"] == "pending":
                        later["status"] = "not_run_input_drift"
                        later["completed_utc"] = benchmark.utc_now()
                        later["failure_class"] = "frozen_input_drift"
                        later["failure_code"] = "frozen_input_identity_changed"
                journal["status"] = "aborted_input_drift"
                journal["completed_utc"] = benchmark.utc_now()
                break
    except KeyboardInterrupt:
        benchmark.refresh_totals(journal)
        benchmark.persist_journal(run_root, journal)
        return journal
    benchmark.update_completion_state(journal)
    benchmark.persist_journal(run_root, journal)
    return journal


def _make_provider(args, *, mode: str, replay: dict, endpoint: str,
                   allowed_host: str | None):
    if mode == "live":
        return _live_provider(args, endpoint, allowed_host or "api.openai.com")
    return ReplayProvider(model=args.model or ("offline-replay-v1" if mode == "replay" else DEFAULT_OFFLINE_MODEL),
                          replay=replay)


def command_run(args) -> int:
    scope = args.scope
    mode = args.mode
    fixtures = benchmark.load_fixture_set(REPO_ROOT, scope)[1]
    fixture_ids = tuple(item["id"] for item in fixtures)
    replay, replay_hash = _load_replay(args.replay_file, fixture_ids)
    if mode == "replay" and not args.replay_file:
        raise RunInputError("replay mode requires --replay-file")
    if mode != "replay" and args.replay_file:
        raise RunInputError("--replay-file is available only in replay mode")
    if mode == "live":
        if args.max_semantic_calls is None or args.completion_output_token_budget is None:
            raise RunInputError("live mode requires explicit positive semantic-call and completion-output-token budgets")
        max_calls = args.max_semantic_calls
        output_budget = args.completion_output_token_budget
    else:
        max_calls = (args.max_semantic_calls if args.max_semantic_calls is not None
                     else (150 if scope == "release" else 40))
        output_budget = (args.completion_output_token_budget
                         if args.completion_output_token_budget is not None
                         else max_calls * 8192)
    cap = 150 if scope == "release" else 40
    if type(max_calls) is not int or not 1 <= max_calls <= cap:
        raise RunInputError(f"semantic-call ceiling must be from 1 through {cap} for this scope")
    if type(output_budget) is not int or output_budget <= 0:
        raise RunInputError("completion output token budget must be a positive integer")
    if output_budget > max_calls * 8192:
        raise RunInputError("completion output token budget exceeds the fixed per-request output caps")
    provider_data, _ = _provider_info(
        mode=mode, model=args.model,
        endpoint=args.endpoint or DEFAULT_ENDPOINT,
        credential_source=args.credential_source,
        credential_alias=args.credential_alias,
        allow_host=args.allow_host,
    )
    endpoint = args.endpoint or DEFAULT_ENDPOINT
    allowed_host = provider_data.get("endpoint_host")
    http_limit = max_calls * 2 if mode == "live" else 0
    if mode == "live":
        if not args.acknowledge_unbounded_cost:
            raise RunInputError("live mode requires --acknowledge-unbounded-cost for the input-token and dollar-cost limitation")
        _live_preflight(scope=scope, model=provider_data["model"],
                        max_calls=max_calls, output_budget=output_budget,
                        http_upper_bound=http_limit)
    provider = _make_provider(args, mode=mode, replay=replay,
                              endpoint=endpoint, allowed_host=allowed_host)
    manifest = benchmark.build_manifest(
        REPO_ROOT, scope=scope, mode=mode, provider=provider_data,
        limits={"max_semantic_calls": max_calls,
                "completion_output_tokens": output_budget},
        replay_sha256=replay_hash,
    )
    output_parent = _validated_output_parent(args.output_parent)
    run_root, journal = benchmark.initialize_run(REPO_ROOT, output_parent,
                                                 manifest=manifest)
    wrapped = BudgetedProvider(provider, max_calls=max_calls,
                               output_token_budget=output_budget)
    journal = execute_pending(REPO_ROOT, run_root, journal, wrapped,
                              replay_file=args.replay_file)
    report = benchmark.single_run_report(run_root, REPO_ROOT)
    print(json.dumps({"run_root": str(run_root), "report": report},
                     ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if journal.get("status") == "complete" else 2


def command_resume(args) -> int:
    run_root = Path(args.run_root)
    journal = benchmark.load_journal(run_root)
    manifest = journal["manifest"]
    mode = args.mode
    if mode != manifest["mode"]:
        raise RunInputError("resume mode must match the frozen run manifest")
    scope = manifest["scope"]
    provider_data, _ = _provider_info(
        mode=mode, model=args.model,
        endpoint=args.endpoint or DEFAULT_ENDPOINT,
        credential_source=args.credential_source,
        credential_alias=args.credential_alias,
        allow_host=args.allow_host,
    )
    frozen_provider = manifest["provider"]
    comparable = ("provider_id", "model", "endpoint_host", "endpoint_path",
                  "endpoint_sha256", "credential_source", "credential_alias")
    if any(provider_data.get(key) != frozen_provider.get(key) for key in comparable):
        raise RunInputError("resume provider/model configuration must match the frozen manifest")
    replay, replay_hash = _load_replay(args.replay_file, tuple(manifest["fixture_ids"]))
    if mode == "replay" and replay_hash != manifest.get("replay_sha256"):
        raise RunInputError("resume replay file does not match the frozen input hash")
    if mode != "replay" and args.replay_file:
        raise RunInputError("--replay-file is available only for replay mode")
    if mode == "live":
        if not args.acknowledge_unbounded_cost:
            raise RunInputError("live resume requires --acknowledge-unbounded-cost")
        _live_preflight(
            scope=scope, model=frozen_provider["model"],
            max_calls=manifest["limits"]["max_semantic_calls"],
            output_budget=manifest["limits"]["completion_output_token_reservation"],
            http_upper_bound=manifest["limits"]["http_attempts_conservative_upper_bound"],
        )
    benchmark.mark_interrupted_items(journal)
    if not benchmark.frozen_inputs_match(REPO_ROOT, manifest):
        _mark_input_drift(journal, next((item["id"] for item in journal["items"]
                                         if item["status"] == "pending"), None))
        journal["status"] = "aborted_input_drift"
        journal["completed_utc"] = benchmark.utc_now()
        benchmark.refresh_totals(journal)
        benchmark.persist_journal(run_root, journal)
        print(json.dumps(benchmark.single_run_report(run_root, REPO_ROOT), indent=2))
        return 2
    benchmark.persist_journal(run_root, journal)
    provider = _make_provider(args, mode=mode, replay=replay,
                              endpoint=args.endpoint or DEFAULT_ENDPOINT,
                              allowed_host=provider_data.get("endpoint_host"))
    limits = manifest["limits"]
    wrapped = BudgetedProvider(
        provider,
        max_calls=limits["max_semantic_calls"],
        output_token_budget=limits["completion_output_token_reservation"],
        initial_calls=int(journal.get("totals", {}).get("semantic_calls", 0)),
        initial_output_tokens=int(journal.get("totals", {}).get("completion_output_tokens_reserved", 0)),
    )
    journal = execute_pending(REPO_ROOT, run_root, journal, wrapped,
                              replay_file=args.replay_file)
    report = benchmark.single_run_report(run_root, REPO_ROOT)
    print(json.dumps({"run_root": str(run_root), "report": report},
                     ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if journal.get("status") == "complete" else 2


def command_report(args) -> int:
    report = benchmark.single_run_report(args.run_root, REPO_ROOT)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


def command_gate(args) -> int:
    result = benchmark.two_run_gate(args.first_run, args.second_run, REPO_ROOT)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["release_gate"] == "PASS" else 2


def command_export_human(args) -> int:
    value = benchmark.export_human_template(args.run_root, args.output)
    print(json.dumps({"output": str(Path(args.output).resolve()),
                      "run_uuid": value["run_uuid"],
                      "items": len(value["items"]),
                      "qualification": "HUMAN SCORES REQUIRED"}, indent=2))
    return 0


def command_import_human(args) -> int:
    value = benchmark.import_human_scores(args.run_root, args.score_file)
    print(json.dumps({"reviewer_id": value["reviewer_id"],
                      "original_sha256": value["original_sha256"],
                      "human_acceptable": value["counts"]["human_acceptable"],
                      "denominator": value["counts"]["denominator"],
                      "status": value["status"]}, indent=2))
    return 0 if value["status"] == "PASS" else 2


def command_export_resolution(args) -> int:
    value = benchmark.export_human_resolution_template(args.run_root, args.output)
    print(json.dumps({"output": str(Path(args.output).resolve()),
                      "run_uuid": value["run_uuid"],
                      "disagreements": len(value["items"]),
                      "resolution_required": bool(value["items"])}, indent=2))
    return 0


def command_import_resolution(args) -> int:
    value = benchmark.import_human_resolution(args.run_root, args.resolution_file)
    print(json.dumps({"original_sha256": value["original_sha256"],
                      "resolved_items": value["resolved_items"],
                      "status": "PRESERVED_SEPARATELY"}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Frozen V1 AI benchmark runner. Default mode is offline fake; live calls require an explicit preflight acknowledgement."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="freeze and execute one release or discovery ledger")
    run.add_argument("--scope", choices=("release", "discovery"), default="release")
    run.add_argument("--mode", choices=("fake", "replay", "live"), default="fake")
    run.add_argument("--output-parent", help="private parent directory for a unique run store")
    run.add_argument("--model", help="explicit provider/model identifier for live or replay runs")
    run.add_argument("--endpoint", help="HTTPS OpenAI-compatible endpoint (default: api.openai.com)")
    run.add_argument("--allow-host", help="exact host allowlist for a custom endpoint")
    run.add_argument("--credential-source", choices=("system", "session"), default="system")
    run.add_argument("--credential-alias", default="default")
    run.add_argument("--max-semantic-calls", type=int,
                     help="whole-run semantic call ceiling; required for live mode")
    run.add_argument("--completion-output-token-budget", type=int,
                     help="whole-run maximum reserved completion output tokens; required for live mode")
    run.add_argument("--acknowledge-unbounded-cost", action="store_true",
                     help="acknowledge that input tokens and dollar cost cannot be bounded")
    run.add_argument("--replay-file", help="offline replay JSON; required only in replay mode")
    run.set_defaults(function=command_run)

    resume = commands.add_parser("resume", help="continue pending items without overwriting terminal outcomes")
    resume.add_argument("--run-root", required=True)
    resume.add_argument("--mode", choices=("fake", "replay", "live"), required=True)
    resume.add_argument("--model", help="explicit model identifier; must match the frozen manifest")
    resume.add_argument("--endpoint", help="must match the frozen endpoint")
    resume.add_argument("--allow-host", help="must match the frozen host allowlist")
    resume.add_argument("--credential-source", choices=("system", "session"), default="system")
    resume.add_argument("--credential-alias", default="default")
    resume.add_argument("--acknowledge-unbounded-cost", action="store_true")
    resume.add_argument("--replay-file")
    resume.set_defaults(function=command_resume)

    report = commands.add_parser("report", help="recheck and report one immutable run ledger")
    report.add_argument("--run-root", required=True)
    report.set_defaults(function=command_report)

    gate = commands.add_parser("gate", help="evaluate exactly two independent release run ledgers")
    gate.add_argument("--first-run", required=True)
    gate.add_argument("--second-run", required=True)
    gate.set_defaults(function=command_gate)

    export = commands.add_parser("export-human", help="export a blank independent scoring template")
    export.add_argument("--run-root", required=True)
    export.add_argument("--output", required=True)
    export.set_defaults(function=command_export_human)

    scoring = commands.add_parser("import-human", help="validate and preserve an original human scoring file")
    scoring.add_argument("--run-root", required=True)
    scoring.add_argument("--score-file", required=True)
    scoring.set_defaults(function=command_import_human)

    resolution_export = commands.add_parser("export-resolution", help="export a separate disagreement-resolution template")
    resolution_export.add_argument("--run-root", required=True)
    resolution_export.add_argument("--output", required=True)
    resolution_export.set_defaults(function=command_export_resolution)

    resolution_import = commands.add_parser("import-resolution", help="preserve a separate evaluator resolution file")
    resolution_import.add_argument("--run-root", required=True)
    resolution_import.add_argument("--resolution-file", required=True)
    resolution_import.set_defaults(function=command_import_resolution)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.function(args)
    except (benchmark.BenchmarkError, RunInputError) as exc:
        print(f"benchmark input error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("benchmark interrupted; the current item remains explicitly pending or interrupted in the run journal", file=sys.stderr)
        return 130
    except Exception as exc:
        # Exception messages and provider bodies are never logged. The type is
        # enough to direct debugging while keeping credential material private.
        print(f"benchmark failed safely ({type(exc).__name__})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
