# Phase 7 — external-agent trial report

Evidence for: "Give an external LLM only the shipped contract/guide/examples
and an asset brief... Exercise both a simple asset and a bound/textured/
animated character; include a rejected request followed by a successful
correction." (`docs/V3_FUNCTIONAL_IMPLEMENTATION_PLAN.md` Phase 7.)

## Methodology and its honest limitations

There is no access to a genuinely separate AI vendor from this environment.
After discussing this with the user, the agreed approach (their explicit
choice, offered as "Isolated substitute agent (Recommended)") was:

> Spawn a fresh subagent with zero context from this conversation or the
> codebase — it only ever sees the shipped guide, schema, examples, and an
> asset brief written by the orchestrating session. It authors and iterates
> on the recipe blind, exactly like an external caller would.

This is **weaker than a truly independent AI vendor** (it is a different
instance of the same underlying model family, spawned via the `Agent` tool
rather than called over an external API), but it is a real test of whether
the shipped contract *by itself* is sufficient for an agent with no access
to this repository's source code to author working recipes, including
recovering from a real rejection using only the tool's own error output.

Two methodological errors were made and self-corrected during this trial;
both are recorded here in full rather than omitted, per this project's
existing no-overclaiming practice.

### Error 1 (caught before any trial output was treated as final): embellished guide text

The first pair of trial-agent prompts pasted a "guide" that included
sentences **not present** in the real `EXTERNAL_AGENT_GUIDE.md` — e.g. an
explicit hint that `sections=6` on a torus gives "a hexagonal cross-section"
for the lantern brief, and extra prose steering weight/pattern choices for
the sentinel brief. This spoon-fed answers the real shipped guide does not
give, defeating the point of testing contract sufficiency. It was caught
before treating those runs as trial evidence and discarded.

**Fix:** the guide, schema, and both examples were concatenated with `cat`
directly from the shipped files, md5-verified against the source files, and
read back in full before reuse, into
[`shipped_packet_verbatim.txt`](shipped_packet_verbatim.txt) (404 lines).
Every subsequent agent prompt pastes from this byte-exact file, never a
paraphrase.

### Error 2 (caught immediately, before any code fix was based on it): a "continuation" prompt that spawned a fully-tooled agent instead

To feed the first rejection's error text back to the same isolated agent,
a follow-up `Agent` call was made with a prompt beginning `"to: <agentId>"`,
on the mistaken belief this would resume that agent's isolated context.
The `Agent` tool has no such mechanism — every call spawns a brand-new,
fully-tooled `general-purpose` agent. That agent, despite its prompt's own
"no filesystem/tool access" instruction, used `Grep`/`Read` to inspect the
real `am3d/recipes/primitives.py` and `am3d/recipes/schema.py` source and
based its "correction" on reading the source directly, not on reasoning
from the error text — and also rewrote the recipe substantially rather than
making a minimal fix. This was discarded before being used as evidence.

**Fix:** every correction step below was instead done as a **fresh**
`general-purpose` agent call that re-supplies the full original packet, the
agent's own prior JSON, and the exact raw CLI rejection, with an explicit,
repeated "you have no tool access, reason only from the pasted text" framing.
This is a *good-faith instruction-following isolation*, not a hard technical
sandbox — the `general-purpose` agent type has tool access available to it
in principle. Each correction call's own `tool_uses` count (visible in the
agent's own usage metadata) was checked afterward to confirm 0 tool calls
were actually made; both corrections below show `tool_uses: 0`.

## Trial A — simple asset: `garden_lantern`

**Brief:** [`brief_simple_lantern.txt`](brief_simple_lantern.txt) — a
hexagonal, faceted lantern body/frame with a flat base and a tapering glass
shade, `wrought_iron` + `amber_glass` materials, `.obj` + `.glb` + `.am3d`
exports.

**Attempt 1** (agent's raw, unedited output):
[`simple_lantern/attempt1_garden_lantern.json`](simple_lantern/attempt1_garden_lantern.json).
The agent, working only from the verbatim packet, used a `torus` primitive
for the lantern's collar/frame ring and — following the shipped guide's own
(as it turns out, incorrect) documentation — passed `sections`/`rings`.

**Rejected.** Run via `python -m am3d.recipes --recipe ... --out ...`:
```json
{"ok": false, "objects": ["base", "frame_body"], ...,
 "errors": ["ValueError: primitive 'torus' got bad params {...}: make_torus() got an unexpected keyword argument 'sections'"],
 "error_records": [{"code": "execution_error", "stage": "runtime", "path": "recipe",
   "message": "ValueError: primitive 'torus' got bad params {...}: make_torus() got an unexpected keyword argument 'sections'"}]}
```
This is a **genuine product bug**, not an agent mistake: the shipped guide
documented the torus primitive's tessellation params as `sections`/`rings`,
copying the pattern used for sphere/cylinder/cone, but the real
`make_torus()` function takes `major_sections`/`minor_sections` instead (see
"Confirmed bugs found and fixed" below). The agent followed the shipped
contract correctly and was rejected anyway.

**Correction** (fresh, isolated agent, given only its own prior JSON and the
exact raw rejection above — `tool_uses: 0`): the agent noted the error names
`sections` as bad but the correct name is not stated anywhere in what it had
access to (neither the guide nor the two examples use a torus), so guessing
a replacement name risked trading one rejection for another; it made the
conservative choice to drop both unconfirmed keys and let the primitive fall
back to its own defaults, changing nothing else in the recipe. Saved as
[`simple_lantern/attempt2_garden_lantern_corrected.json`](simple_lantern/attempt2_garden_lantern_corrected.json).

**Result: success.** Re-run through both `python -m am3d.recipes` and the
packaged `am3d-recipe.exe` — identical `ok: true`, all 4 objects, both
materials, all 3 exports written
([`simple_lantern/attempt2_cli_result.json`](simple_lantern/attempt2_cli_result.json)).

## Trial B — bound/textured/animated character: `sentinel_bot`

**Brief:** [`brief_complex_sentinel.txt`](brief_complex_sentinel.txt) — a
boxy-torso/spherical-head/two-leg robot, a hip/spine/leg-left/leg-right
skeleton, hand-tuned `cp_weights` on one bone in addition to normal binding,
a metallic *patterned* (non-flat) material, `idle` + `walk` actions, and
`.obj` + `.glb` + `animation_sheet` + `.am3d` exports.

**Attempt 1**: [`complex_character/attempt1_sentinel_bot.json`](complex_character/attempt1_sentinel_bot.json).
Correctly built all 4 mesh objects bound to a `sentinel` skeleton with
`hip → spine`, `hip → leg_l` (with explicit `cp_weights` override), and
`hip → leg_r`; both actions; all 4 exports. For "not a flat single color,"
the agent invented the pattern name `"paneled_grate"` — a plausible-sounding
name that is not one the shipped tool actually implements, since **the
guide never documents the `pattern` field or its valid values at all** (see
below).

**Rejected**:
```json
{"ok": false, ..., "errors": ["ValueError: unknown pattern 'paneled_grate' (choose from ['bricks', 'checker', 'gradient', 'noise', 'solid'])"]}
```
Unlike the torus case, this error message itself names the valid choices.

**Correction** (fresh, isolated agent, `tool_uses: 0`): given only the error
text and the original brief's "grated/paneled metal" intent, the agent
reasoned through the 5 valid names and picked `checker` (regular repeating
cells reading as panel seams), explaining why the other four fit worse, and
changed only that one field. Saved as
[`complex_character/attempt2_sentinel_bot_corrected.json`](complex_character/attempt2_sentinel_bot_corrected.json).

**Result: success.** Re-run through both `python -m am3d.recipes` and the
packaged `am3d-recipe.exe` — identical `ok: true`; all 4 mesh objects + the
skeleton; the `chassis_metal` material; both actions; 9 files written
(obj, mtl, glb, animation_sheet PNG, am3d, and 4 per-object texture atlas
PNGs)
([`complex_character/attempt2_cli_result.json`](complex_character/attempt2_cli_result.json)).

## Confirmed bugs found and fixed

All three were found organically by the trial agents working only from the
shipped docs, not by auditing the source first. `docs/recipes/EXTERNAL_AGENT_GUIDE.md`
was corrected for each:

1. **Torus params wrong.** Guide said `sections`/`rings`; `make_torus()`
   actually takes `major_sections`/`minor_sections`. This is the rejection
   exercised in Trial A above. Fixed.
2. **`pattern` field undocumented entirely.** The guide never mentioned
   `materials[].pattern` or its 5 valid values (`solid`, `checker`,
   `gradient`, `noise`, `bricks`), or their own optional sub-params. This is
   what caused Trial B's rejection (the agent had to invent a name with zero
   guidance). Added a new "3a. Material Patterns" section.
3. **`plane`/`lathe`/`extrude` params wrong**, found during an audit of the
   rest of section 3 prompted by the two bugs above (not hit by either
   trial, since neither brief used these primitives): the guide said
   `plane` takes `width`/`depth` but the real function takes `width`/
   `height`; it said `lathe` takes `sections`/`angle` (no `angle` parameter
   exists) and `extrude` sweeps along the Z-axis with `depth`/`cap_start`/
   `cap_end` (none of those exist), when the real functions take an explicit
   `profile` array plus `axis`/`sections` (lathe) or `height`/`twist_deg`/
   `rings` (extrude, which sweeps along +Y, not Z). Fixed.

No confirmed bug remains unresolved; both live rejections were fully
diagnosed to a working correction without any hand-editing of the agents'
JSON by the orchestrating session.

## Deterministic CI regression fixtures

Separate from this live trial, `docs/recipes/examples/knight_full.json` and
`scripts/knight_recipe.json` are already exercised as deterministic
regressions in `am3d/recipes/test_executor.py` and `test_schema.py` — this
plan requirement was already satisfied before this phase and needed no new
work.

## Inspecting results in the shipped desktop application

See [`gui_inspection.md`](gui_inspection.md): interactive GUI automation of
the built `.exe` was not possible from this session (it isn't a
Start-Menu-registered application computer-use can attach to — recorded as
an environment exclusion). Both final `.am3d` files were instead verified
by loading them through the real, unmocked `am3d.ui.app.MainWindow` class
(the same class the packaged smoke test drives) headlessly, confirming all
objects/materials/actions/bones round-trip correctly and both scenes
software-render without error.
