# V1 benchmark protocol

This document preserves the old draft's useful benchmark detail while
applying rev. 3's order. Candidate brief texts below are not frozen release
fixtures. M3 measures provider behavior after repair exists; M4 runs a
development baseline on about 15 briefs and freezes the release set, rubric,
provider/model, prompt context, and thresholds from evidence. The old `27/30`
target is an aspiration until that freeze. Never silently remove failures or
change frozen prompts without rerunning the full set.

## Run stages

**M3 provider bake-off — 20 runs.** Use five discovery briefs on each of four
providers, one run per pair: Codex Luna xhigh, Claude Code Sonnet 5.5 low,
opencode with DeepSeek v4.1 medium/high, and the best local candidate. Spread
runs over 2–3 days. Compare first-pass validity, checked success, wall time,
repair counts/tokens, and quota use. A field unavailable from a provider is
`null`, never zero. Select one default cloud and one default local model from
results, not reputation or speed alone.

**M4 development baseline — about 15 briefs.** Use the selected model and
retain every run. Use results to assess transform rebasing, repeated parts,
symmetry, and repair cost. Add arrays/mirror only for repeated evidence;
add a strict JSON Patch subset only if repair exceeds about 30% of run tokens.
Freeze benchmark/rubric/thresholds only after this baseline.

**M6 release evidence.** Two complete runs on the default cloud provider and
one on the default local model. The planning budget is 60 cloud generations
and 30 local generations. Keep failures in the denominator and report
provider/infrastructure errors separately without omitting them from
end-to-end success. Other subscriptions repeat only the five discovery
briefs.

## Candidate release briefs

Retained from the superseded draft as a starting pool. Each needs an
independently authored check for the listed parts, placement, material, or
motion; the model cannot define its own passing rubric.

| ID | Brief | Required check |
| --- | --- | --- |
| 01 | Chunky blue enamel RPG mug | Body, handle, blue body; OBJ/GLB. |
| 02 | Red low-poly desk lamp | Base, stem, head, colour. |
| 03 | Brown wooden crate | Box and at least four separate reinforcement slats. |
| 04 | Green metal watering can | Body, spout beyond body, handle. |
| 05 | Round red stool | Seat and three correctly placed wood legs. |
| 06 | Compact wooden writing desk | Top, four legs, drawer/front. |
| 07 | Early-2000s grey office chair | Seat/back/stem/base/wheels. |
| 08 | Medieval blacksmith anvil on wood block | Block/body/horn; profile approximation disclosed. |
| 09 | Wooden treasure chest | Base/lid/brass straps with separate materials. |
| 10 | Stylised iron lantern | Cage/base/top/yellow insert. |
| 11 | Fantasy sword | Blade/guard/grip along long axis. |
| 12 | Industrial barrel | Cylinder and two dark hoops. |
| 13 | Chunky factory pipe | Right-angle elbow and flanges; no CSG claim. |
| 14 | Yellow road barrier | Beam/two feet/black markings. |
| 15 | 2001 beige CRT monitor | Case/dark screen/stand. |
| 16 | Retro grey game console | Shell/two slot approximations; disclose recess limit. |
| 17 | Small red British telephone kiosk | Frame/roof/panels. |
| 18 | Simple cottage | Walls/flatter pitched roof/chimney/front door and bounds. |
| 19 | Stone arch gateway | Separate chunky blocks, posts/top/open passage. |
| 20 | Early-2000s British bus shelter | Green frame, roof, stylised glass-like panels, bench. |
| 21 | Grey park bench | Supports plus wooden seat/back slats. |
| 22 | Green litter bin | Body/dark opening/small feet. |
| 23 | Simplified red compact car | Body/cabin/four black wheels; static exterior. |
| 24 | Chunky blue delivery van | Cabin/cargo body/four wheels and relative size. |
| 25 | Stylised unrigged toy robot | Red torso/head/paired long arms/legs. |
| 26 | Simple rounded green rigged creature | Body/limbs/bones/weights. |
| 27 | Humanoid robot waving right arm | Rig/action, right-arm deformation, sheet/native project. |
| 28 | Copper clockwork beetle walking in place | Shell/legs/shared-rig binding/visible motion. |
| 29 | Blue mascot doing a small jump | Torso/legs/rig/jump and geometry movement. |
| 30 | Rigged guard breathing idly | Torso/limbs/action and visible deformation. |

Keep these discovery challenges separate from release denominator: 20-step
spiral staircase; bicycle with thin spokes; worn shelter with truly
transparent glass; expressive lip motion; translated rig limbs; 5,000 bolts;
negative-scale mirrored textured chair; animated GLB. Expect explicit
refusal, approximation, or policy rejection and record why.

## Measurements and rubric to freeze

Record raw schema pass, semantic/preflight pass, direct execution, repair
success and counts, deterministic checked result, nonblank preview,
save/reopen, required parts/materials, animation deformation, independent
export parse, security bounds, duration, usage/quota, and human score. Report
each stage and all failed runs. Pin model version when available and disclose
provider drift.

The old draft proposed ≥27/30 deterministic success in each of two complete
runs, with floors of 20/25 static and 4/5 rig/animation. It also proposed at
least 24/30 human-acceptable candidates per run, two independent reviewers,
and a four-attribute 0–2 rubric (recognisable silhouette, essential parts,
useful proportions/appearance, editability), ≥6/8 with no essential part
missing. These are reference aspirations only; M4 must freeze or revise them
from baseline evidence before release measurement. Human quality stays
separate from deterministic integrity checks. Security failures never pass
because an aggregate score is high.
