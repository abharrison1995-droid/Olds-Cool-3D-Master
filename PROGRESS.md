# 3D MASTER:2005 — current status

Updated: 2026-09-28.

This file is a short status index, not a second implementation plan. The
active plan is [docs/IMPLEMENTATION_ROADMAP.md](docs/IMPLEMENTATION_ROADMAP.md).
Older V1/V2/V3 plans and their evidence remain as historical records; their
PASS labels do not replace acceptance of the current source and artifacts.

## Product outcome

An external AI agent authors and runs a recipe to create an editable 3D asset;
the desktop editor opens that project for inspection and further work. The
recipe/CLI workflow is code-first. There is no embedded model-provider or
prompt interface.

## Implemented foundation

- Versioned JSON recipe schema, authoring guide, examples, validation-only
  mode, structured CLI errors and output manifests.
- Recipe generation for geometry, procedural appearance, rigs/actions,
  editable `.am3d` projects, static OBJ/GLB exports, and sprite/toon/animation
  sheets.
- Desktop GUI for modeling, materials, rigging, animation, rendering,
  persistence and review of generated projects.
- A Blender-meets-early-2000s desktop restyle is present in the current
  working tree, with previews under `docs/previews/`.
- The Linux Mint 22.3 x86-64 current-source preview candidate has passed its
  source suite and packaged checks. GUI smoke used Qt offscreen/software
  paths; this is not native-desktop, GPU, MX, or broad Linux qualification.

## Deferred platform qualification

MX Linux 25.2 and Windows are follow-on qualification for a later
cross-platform release, not blockers for the Mint preview candidate. No
Windows artifact is included or verified, and the current source has not been
requalified on MX. A genuinely separate LLM vendor has also not been tested;
the earlier agent trial used fresh same-family substitute agents and records
that limitation.

See `docs/evidence/desktop-release/FINDING_LEDGER.md` for historical fixes
and evidence, `docs/CAPABILITY_MATRIX.md` for surface-by-surface support, and
`docs/IMPLEMENTATION_ROADMAP.md` for the remaining work and gates.

Phase 0 of the roadmap is complete: two independent Luna reviewers examined
the plan and supporting docs, their findings were resolved, and the review is
recorded in `docs/evidence/implementation-roadmap/phase-0-review.md`.

Phase 1 is complete: a fresh same-family Luna agent corrected a structured recipe rejection, validated the final recipe, and created the project and exports. Independent evaluation confirmed leg motion; two Luna reviewers passed the gate. The agent trial used the source CLI; packaged CLI acceptance was completed in Phase 3.

Phase 2 is complete for the Qt offscreen MainWindow path: generated-project edit, undo, redo, save, and reopen passed, and the full asset is visible in both workspace captures at 1280×820 and 1440×900. Two independent Luna reviewers passed after renderer fallback reporting was corrected. Native compositor and physical GPU checks remain pending on their target platforms.

Phase 3's final-scope current-source candidate passed on Mint 22.3, with 738 tests, 14 packaged GUI smoke steps, CLI validation/export and structured parse-failure checks, plus relocation and payload checks. The staged docs match the Mint preview scope, and two fresh independent Luna reviews passed. Mint/offscreen evidence does not certify MX or hardware GPU behavior; see `docs/evidence/implementation-roadmap/CANDIDATE_REVIEW.md`.

Phase 4 MX qualification is deferred until the documented MX Linux 25.2 machine is available. Phase 5's `windows-latest` CI preparation is complete and passed two independent Luna reviews; `.github/workflows/windows.yml` has not run. Windows CI, clean-VM and real-GPU checks remain later platform gates.
