# V1 security and resource limits

Authority: [V1 master plan](V1_MASTER_IMPLEMENTATION_PLAN.md), section 6.
Current V1 implementation is `am3d.ai.*`. The incompatible earlier M2/M3.1
implementation remains under `am3d.ai.m3.*`; its historical limits are not the
current V1 defaults. The worker is a bounded data-only process, not an OS sandbox.

## Current V1 ceilings

`ai/policy.py` owns AI preflight limits, `ai/contracts.py` provider/lifecycle
limits, and `ai/orchestrator.py` candidate/repair counts. Recipe registry and
resource checks also run before allocation. Trusted offline CLI constraints
remain distinct from AI-only ceilings.

| Resource | Ceiling or current setting |
| --- | ---: |
| Recipe JSON | 512 KiB |
| Provider JSON response | 1 MiB |
| Objects / patches | 128 / 1,024 |
| Bones per rig / total copied bones | 64 / 256 |
| Actions / channels / keys | 16 / 256 / 4,096 |
| Authored profile/control points | 4,096 |
| Primitive subdivisions | 128 |
| Materials / graph nodes per material | 32 / 32 |
| V1 policy/check tessellation setting | 16 × 16 |
| Evaluated triangles | 250,000 |
| Whole-scene preview | 512 × 512 pixels |
| Sheet cells / maximum cell size | 16 / 256 × 256 pixels |
| Combined sheet pixels | 16 million |
| Atlas cell / combined pixels | 256 / 64 million |
| Output bytes | 256 MiB |
| Estimated/monitored worker memory target | 1 GiB |
| Worker deadline | At most 180 seconds within shared deadline |
| Shared generation deadline | At most 600 seconds |
| Provider HTTP attempt | At most 90 seconds within shared deadline |
| Candidates / semantic calls | 4 / 5 |
| Validation repairs / execution-check repairs | 2 / 1 |
| HTTP attempts per semantic call | 2 |
| Cancellation acknowledgement target | 3 seconds |

Estimate control nets, triangle and texture memory before allocating; count
actual scene/output resources afterward. Memory exhaustion and resource-limit
outcomes must remain terminal failures. Host enforcement combines estimates,
deadlines and process monitoring/termination. Windows Job Objects currently
provide kill-on-close descendant cleanup, not a configured kernel memory cap.
Do not present the memory target as guaranteed OS-level containment.

## Paths, credentials and provider failures

AI names must be nonempty UTF-8 text of at most 256 bytes without control
characters, in addition to recipe validation. File-producing object names
use deterministic opaque IDs; native names stay readable. Portable path and
link/reparse checks guard the host-selected private output tree and derived
export/sidecar destinations. V1 AI mode forbids model-selected texture inputs,
code, commands and arbitrary resource paths. Do not silently sanitize a model
path-policy violation into an accepted request.

Workers receive bounded host-selected recipe/check inputs and an allowlisted
environment. Credentials never enter workers, projects, records or logs.
Provider errors are sanitized before persistence. Authentication, refusal,
configuration and policy failures do not enter repair loops; transient and
rate-limit transport handling is bounded by attempts and shared deadlines.

The current provider exposes usage when available and no configured pricing
tariff or enforced daily/monthly dollar budget. Do not claim the old draft's
$0.10/$1/$5 limits are implemented. Live benchmark authorization must explicitly
account for the provider contract's cost/input-token limitations; see
[benchmark protocol](V1_BENCHMARK.md). Manual/CLI workflows remain offline.
