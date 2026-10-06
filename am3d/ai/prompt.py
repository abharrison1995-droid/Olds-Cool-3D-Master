"""Stable, deterministic, bounded prompt construction for recipe proposals."""

from __future__ import annotations

from copy import deepcopy
import json

from .provider_contracts import (FailureCode, MAX_PROVIDER_RESPONSE_BYTES,
                                 provider_response_schema,
                                 provider_response_schema_json)
from .providers import ProviderRequest


MAX_BRIEF_CHARS = 4096
MAX_BRIEF_BYTES = 16 * 1024
MAX_PROMPT_BYTES = 64 * 1024
PROVIDER_DEADLINE_SECONDS = 10 * 60


_EXAMPLES = (
    {
        "schema_version": 1,
        "intent": "A simple cube.",
        "assumptions": [],
        "approximations": [],
        "required_components": ["body"],
        "recipe": {
            "version": 1,
            "name": "cube",
            "objects": [{"name": "body", "primitive": "box"}],
        },
    },
    {
        "schema_version": 1,
        "intent": "A small wooden stool with a seat and two example legs.",
        "assumptions": ["The brief does not specify exact dimensions."],
        "approximations": ["Only two legs are shown in this compact example."],
        "required_components": ["seat", "leg_a", "leg_b"],
        "recipe": {
            "version": 1,
            "name": "wood_stool_example",
            "objects": [
                {"name": "seat", "primitive": "box",
                 "params": {"width": 1.5, "height": 0.2, "depth": 1.2},
                 "transform": {"translate": [0, 1, 0]}},
                {"name": "leg_a", "primitive": "box",
                 "params": {"width": 0.15, "height": 1, "depth": 0.15},
                 "transform": {"translate": [-0.5, 0.4, -0.4]}},
                {"name": "leg_b", "primitive": "box",
                 "params": {"width": 0.15, "height": 1, "depth": 0.15},
                 "transform": {"translate": [0.5, 0.4, -0.4]}},
            ],
            "materials": [{"name": "wood", "color": [0.4, 0.2, 0.1],
                           "objects": ["seat", "leg_a", "leg_b"]}],
        },
    },
)


class PromptBuildError(ValueError):
    def __init__(self, code: FailureCode, message: str):
        self.code = code
        super().__init__(message)


def _stable_prefix() -> str:
    examples = "\n\n".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for item in _EXAMPLES)
    return (
        "You propose a new 3D scene for 3D MASTER:2005. Use only the user brief. "
        "You have no access to the user's repository, editor, active document, "
        "filesystem, or other files. Return exactly one JSON object matching the "
        "versioned response schema below; do not use Markdown fences. Only the "
        "recipe-v1 object may be executed, after host policy validation, the fixed "
        "worker, and deterministic checks. Never return Python, shell, commands, "
        "imports, modules, callbacks, plugins, executable steps, a worker command, "
        "an output root, or absolute paths. Use brief assumptions and approximations "
        "for details the contract cannot represent.\n\n"
        "Response JSON Schema:\n" + provider_response_schema_json() +
        "\n\nExamples:\n" + examples
    )


class PromptCompiler:
    """Compile a user brief after one immutable cached contract prefix."""

    def __init__(self):
        self._prefix = _stable_prefix()
        try:
            prefix_size = len(self._prefix.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise RuntimeError("fixed provider prompt is not valid UTF-8") from exc
        if prefix_size > MAX_PROMPT_BYTES:
            raise RuntimeError("fixed provider prompt exceeds its byte limit")

    @property
    def stable_prefix(self) -> str:
        return self._prefix

    def compile(self, brief: str) -> ProviderRequest:
        if not isinstance(brief, str):
            raise PromptBuildError(FailureCode.INVALID_BRIEF,
                                   "brief must be text")
        brief = brief.strip()
        if not brief:
            raise PromptBuildError(FailureCode.INVALID_BRIEF,
                                   "brief cannot be empty")
        if len(brief) > MAX_BRIEF_CHARS:
            raise PromptBuildError(FailureCode.PROMPT_TOO_LARGE,
                                   f"brief exceeds {MAX_BRIEF_CHARS} characters")
        try:
            brief_size = len(brief.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as exc:
            raise PromptBuildError(FailureCode.INVALID_BRIEF,
                                   "brief contains invalid Unicode") from exc
        if brief_size > MAX_BRIEF_BYTES:
            raise PromptBuildError(FailureCode.PROMPT_TOO_LARGE,
                                   f"brief exceeds {MAX_BRIEF_BYTES} UTF-8 bytes")
        user_prompt = "User brief:\n" + brief
        if len(user_prompt.encode("utf-8")) + len(self._prefix.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise PromptBuildError(FailureCode.PROMPT_TOO_LARGE,
                                   f"compiled prompt exceeds {MAX_PROMPT_BYTES} bytes")
        return ProviderRequest(
            system_prompt=self._prefix,
            user_prompt=user_prompt,
            response_schema=deepcopy(provider_response_schema()),
            deadline_seconds=PROVIDER_DEADLINE_SECONDS,
            max_response_bytes=MAX_PROVIDER_RESPONSE_BYTES,
        )
