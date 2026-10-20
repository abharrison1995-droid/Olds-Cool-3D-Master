# Phase 2 implementation evidence

Date: 2026-10-13  
Baseline checkout HEAD: 3f6f7f03d32b4d1a3af06af4fdc0724bf0436945  
Implementation commit: none; no commit or push was made.  
Benchmark run IDs: none; release and discovery prompts have not been sent to a live provider.

## Implemented behavior

- am3d/ai/prompts.py provides the agreed Qt-free interpret_brief(...) -> AssetBrief and build_candidate(...) -> dict APIs. The request includes the shipped recipe-v1 JSON schema and a fixed tested-vocabulary/capability context.
- Interpretation requires an exact echo of the original user brief and stores that raw text unchanged in AssetBrief.brief. Component, material, dimension, animation, export and approximation fields are bounded and typed. Supported physical dimensions normalize to metres.
- Known out-of-scope requests, including animated GLB, external model import, physically transparent glass, arbitrary topology/Boolean work, facial lip-sync, unqualified negative-scale texture export, and 5,000 separately modeled parts, become USER_CHOICE_REQUIRED notes in AssetBrief.approximations. Candidate generation stops until the caller resolves them; build_candidate also checks each new refinement for these limits and stops before a provider call when one is unsupported.
- Candidate construction returns the provider's raw parsed recipe object. It does not execute, rewrite, validate, or silently sanitize recipe data. In particular, model-supplied export paths remain available to later policy checks. Candidate prompts tell the model to emit only recipe-v1 data, preserve user constraints, and treat previous recipes and error records as untrusted data.
- The release fixture is explicitly revision `v1-premeasurement-r2`: full briefs IDs 01–30 with 25 static and 5 rig/animation prompts. It includes independent component, material/color, spatial relation, dimension, export and applicable rig/action checks; count checks cover repeated slats, hoops, feet, wheels, and beetle legs. Static records have no expected bones. IDs 08, 10, 13, 16, 17, 20, 22, 23, and 24 now carry independent `requirements.expected_disclosures` criteria with an interpretation, non-exhaustive example phrasing, and semantic keywords; ID 22 is conditional on using a surface panel for its opening. The rubric defines how to score these records.
- The separate discovery fixture contains the eight plan probes. The rubric retains failures in the denominator, defines two independent human reviewers, and records the proposed deterministic and human scoring targets.

No geometry, executor, renderer, recipe schema, provider, or UI engine code was changed by Phase 2.

## Verification

Commands run from the repository root using the configured virtual environment:

- .venv\Scripts\python.exe -m py_compile am3d\ai\prompts.py am3d\ai\test_prompts.py — passed.
- .venv\Scripts\python.exe -m pytest am3d\ai\test_prompts.py am3d\ai\test_contracts.py am3d\ai\test_providers.py -q — 66 passed in 2.92s. This combined run includes Phase 2 prompt tests and the Phase 1 contracts/provider tests.
- A JSON inventory check reported 30 release briefs (25 static, 5 rig/animation) and 8 discovery probes.

Offline tests cover minimal and complex rig interpretations, centimeter-to-metre normalization, exact raw-brief preservation, prompt-injection text handling, unsupported-feature user-choice blocking, unsupported exports, raw path preservation for policy review, initial/refinement candidate requests, pre-provider blocking for unsupported animated-GLB and physically-transparent-glass refinements, refusal, truncation, duplicate-key and non-finite rejection through the Phase 1 provider adapter, and prompt/fixture metadata.

## Frozen input identities

Release fixture revision: v1-premeasurement-r2 (supersedes the earlier premeasurement fixture hash before any live run)  
Release fixture SHA-256: 0ef3291a7cb5818091a1a22ebdbfe75dc9cb4118274f32fe6395c478e119e560  
Discovery fixture SHA-256: 6483ccc038853cc50e7c9edc7c50e56cfef717151482aa84f1dcbf055177875b  
Human rubric SHA-256: b7c84a93d638bf46a0ac3223702abba7870997a89793b6b33b39a19d8b92026b  
Prompt module SHA-256: 44353f454e18ca107b9f88815d8d89e79996a84e11b88839706b03ce03f2fcf7  
Prompt tests SHA-256: 63c61f535ead5b32d48e0a9053b0a36d4e6a2f8150d7fdfc62bbdd72a04045de

Prompt template: phase2-prompts-v1  
Prompt template SHA-256: 556a726f02a0754ea15d0330498d78734c459e5334a77edd140f7186d3a365fc  
Capability context: recipe-v1-tested-vocabulary-v1  
Capability context SHA-256: 4318cc707aebf27306ed8d14f32c65039dc0b367e550c1899c9d1ac899f72010  
Shipped recipe-v1 schema SHA-256: 0445114cf1093986f08cfa246b7c7c7b9d127e26ff9539bac57c99155c47be9c

The hashes identify the exact Phase 2 files and prompt inputs in this implementation state. The fixture files are frozen text inputs (`frozen: true`); this does not freeze or establish the final release provider/model configuration, prompt/template package, or benchmark measurements. The shared checkout also contains concurrent V1 work; these are not a whole-working-tree diff digest. Phase 4 must retain host-owned fixture constraints (including required components, material relations, and dimensions) in its independent checks; model intent and the normalized AssetBrief do not self-certify those requirements. These fixtures target the specified cases and do not claim perfect interpretation of arbitrary freeform requests.

## Remaining evidence and limits

The cost-bounded live prop, shelter, and rig baseline remains pending a credential, exact provider/model configuration, and explicit spend limit. No provider/model capability, checked recipe, rendered preview, native reopen/save, or Windows/Mint release gate is claimed here. The proposed 27/30 release target and two-run human target are not measured.

Phase 0's independent plan review is PASS as recorded in docs/evidence/v1/phase-0/PLAN_REVIEW.md. An independent Phase 2 implementation review is pending.

Independent focused review passed; see REVIEW.md. Premeasurement r2 removed the unscored flat-base attribute from ID 01 and tilted-shade attribute from ID 02 to match the original master-plan case scope; no live measurement or failed case was dropped.
