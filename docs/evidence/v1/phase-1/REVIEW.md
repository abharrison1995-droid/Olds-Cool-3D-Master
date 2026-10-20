# Phase 1 independent boundary review

Date: 2026-10-13. Reviewer was a fresh read-only Luna subagent, requested
`gpt-6-luna/xhigh`, distinct from the implementation context. Tool accepted
configuration; resolved model/effort is not introspectable.

## First round

- P2 reproduced: cancelling inside an HTTPX mock handler immediately before a
  successful response could return a completed ProviderResponse after cancel.
  Fixed by checking cancellation/deadline after async task completion, after
  transport returns and immediately before successful return. Regression tests
  cover HTTPX and injected transports plus expiry at the response boundary.
- P2 reproduced: placing the active key in `ProviderConfig.model` could send it
  in the JSON body. Fixed by screening endpoint/model/messages/serialized body
  before sending; fixed sanitized errors and zero-transport-call regressions.
- Linux runtime lock missing HTTPX/keyring/Secret Service closure. Fixed in
  implementation preparation by target-wheel cross-resolution; existing 23
  Linux pins retained and 17 new pins added. See `LINUX_LOCK.md` and
  `linux-lock-resolution.json`. Native/frozen Mint verification remains open.

## One focused verification round

Independent reviewer ran the focused 54-test suite and the original HTTPX race
reproduction. Tests passed, and cancellation now raises GenerationCancelledError.
Reviewer confirmed the Linux lock additions, preserved historical pins and
recorded lock SHA-256. Verdict: **local implementation review passed** with
the reproduced defects fixed. No additional implementation review loop was run.

The orchestrator separately exercised real Windows 10 Credential Manager using
a random sentinel entry: store/retrieve/rotate/delete all passed, then the entry
was removed. See `windows-credential-check.json`. No provider API call occurred.
This is not Windows 11 target qualification or Linux Secret Service evidence.

Phase 1's live endpoint/model transport check remains **pending** credentials,
configuration and explicit live-spend limit. Local tested implementation can
support dependent offline scaffolding, but the complete Phase 1 acceptance gate
is not marked passed without its live evidence. Frozen backend/import and
target-platform checks remain Phase 10 requirements.
# Source identity follow-up

`source-identity.json` captures the current listed source bytes for integration,
not a retrospective hash of the earlier review snapshot. Phase 5 subsequently
extends `CancellationToken` with an atomic publication boundary. That extension
is covered by Phase 5's independent review and the final regression suite; the
earlier Phase 1 verdict does not by itself accept that later change.

