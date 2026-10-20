# 3D MASTER:2005 — source user guide

This guide describes the current `1.0.0.dev1` development test candidate. It
is not a release candidate or stable V1 build and does not describe the older
accepted Mint preview bundle, which predates the in-app AI workflow.
The AI source path has passed focused offline checks on Windows 10 in Qt
offscreen mode; live-provider behavior and V1 platform qualification remain
open. For release status, see [`SUPPORTED_PLATFORMS.md`](SUPPORTED_PLATFORMS.md)
and [`PROGRESS.md`](../PROGRESS.md).

## Home and work areas

On launch the app opens Home. Source labels include **Create with AI...**,
**New Empty Project**, **Open Project**, **Enter Editor**, **Quick Start**,
**Diagnostics**, **About** and **Exit**. The current editor workspaces are
**Layout**, **Model**, **Rig**, **Animate** and **Render**. The AI creation
work area is separate from the editor, so opening it does not replace the
current editable document.

## Create with AI

### Configure the provider

From **Create with AI...**, choose **AI Settings…**. The settings dialog
contains **HTTPS endpoint**, **Model name**, **Key storage** and **API key**.
There is no model selected by default. Enter the exact model name supported
by your provider account; the current endpoint allowlist permits HTTPS on
`api.openai.com` only.

For **Key storage**, choose **System credential store** or **Session-only key
(memory)**. The first option constructs the Windows Credential Manager or
Linux Secret Service backend explicitly; availability depends on the host
service. The second option keeps the key in a memory-only store for the
running process. The key field is masked, and **Delete key from selected
store** removes the entry for that choice. The key is never written to
application preferences. Endpoint, model and storage choice are preferences.
Leaving the key field blank keeps the selected store's current key; entering a
new value replaces it.

The source checks that the entered and existing key values do not match
endpoint, model or saved preference text. If the system store is unavailable,
select the explicit session-only option or make the OS credential service
available. Do not copy a key into the brief, recipe, file path, or support
report.

### Review and send a new request

1. Enter the asset request in **Brief**.
2. Choose **Generate…**. A confirmation dialog displays **Destination**,
   **Model**, what request content may be sent, the call/time limits, the
   local run-record location and the cost limitation.
3. Choose **Send request** to authorize that provider call. Choose **Cancel**
   in the dialog to stop before transmission.

For a new generation the disclosed content is the brief, normalized
requirements, candidate recipes, the fixed `recipe-v1` schema/capability
context, and bounded sanitized repair or check feedback. The current project,
project files, images and local filesystem paths are not sent. The API key is
sent in the authorization header. Run records and checked artifacts are
stored locally. Avoid entering credentials or private information in a
brief.

The source limits one run to at most four candidate slots and five semantic
provider calls. The adapter permits two HTTP attempts per semantic call (up to
ten attempts for the run); one HTTP attempt is limited to 90 seconds. The
shared run deadline is 600 seconds, and each worker attempt is limited to 180
seconds. These bounds do not set a provider input-token or dollar-cost cap;
cost is unavailable. The transport does not report the actual HTTP-attempt
count.

During work, **Run status** reports the current message with **Stage**,
**Attempt** and **Elapsed**. Choose **Cancel** to request cancellation. The
status remains in its cancellation state until the operation acknowledges and
finishes; it does not suggest that an HTTP request has stopped before that
acknowledgement.

### Inspect and open a checked result

A completed source run shows a preview in **Checked result**, a project/file
summary, limitations and the accepted recipe plus deterministic check report.
The checker verifies bounded files, safe artifact paths and hashes, selected
scene/request properties, native-project reopenability, and that the fixed
whole-scene preview is a decoded nonblank image. It is a structural gate, not
an artistic-quality score or guarantee that the design looks right.

Choose **Open in Editor** to open a verified writable copy. The normal dirty
document guard applies. If you cancel that guard or the copy cannot be
opened, the current project remains active and the checked result remains
available. If a history sidecar is missing, the app explains that the full
generation history is unavailable; the ordinary **File → Open .am3d...**
path can still open a native project manually.

### Review saved history and refine

In **Saved generations and refinements**, choose **Refresh History** to load
local records and recover interrupted runs. Completed rows are verified when
selected: the app checks the saved artifact manifest, native project and
preview before showing the accepted brief, generation lineage, checked files,
limitations and deterministic recipe-change summary. Failed, cancelled and
interrupted attempts remain visible; interrupted attempts stay unsuccessful
until explicitly retried.

For a verified completed row, **Restore Selected in Editor** creates a new
writable copy and opens it through the ordinary dirty-document guard. The
saved generation remains an immutable history record. If the generation
sidecar is missing, full history is unavailable, but **File > Open** remains
available for the native project. **Delete Selected** asks before removing a
record and its saved files. Deleting a parent with child refinements requires
a second choice, **Delete parent only** or **Keep parent**; children are never
deleted automatically.

To create a child, enter a change in the refinement field and choose
**Refine Selected…**. The request confirmation identifies the selected parent
and change request. It sends the saved generation's accepted brief and
recipe, verified parent-child identity, and the explicit change request; the
model returns a full replacement recipe. The current project, files, images,
manual edits and local paths are not sent or merged. The UI limits this change
request to 4 KiB. As for a new generation, nothing is transmitted until
**Send request** is chosen.

Before refinement, the app compares the current authored session—including
unsaved action/keyframe state—with the verified saved generation. If the
content differs, choose **Save manual copy**, **Refine original generation**,
or **Cancel**. **Save manual copy** uses the regular Save As path and, if it
succeeds, starts a child from the original saved recipe.
**Refine original generation** leaves the current session open and starts
from that same saved recipe. **Cancel** leaves the session and undo history
unchanged. Manual edits are not merged into a generated child. These Phase 7
flows have owner-run offline UI evidence and passed a bounded independent
local preservation/refinement review. The exact locked Windows development
candidate has also passed the full source regression and fixed offline frozen
history/refinement checks. The repository `PROGRESS.md` and
`docs/evidence/v1/ACCEPTANCE_LEDGER.md` record current independent-review
dispositions and the exact local candidate identity.
Windows 11 and Mint target qualification, native/read-only/GPU gates,
live-provider and human-quality gates, and overall V1/RC acceptance remain
open.

## Existing editor scope

The editor workspaces expose object transforms, material properties, spline
construction/profile editing, bone creation and binding, pose/keyframe work,
and render settings. Recipe-generated lathe/extrude surfaces retain editable
source profiles in the current source, and their profile points change the
surface. A separate guide spline does not reshape a baked patch; the desktop
does not expose a general arbitrary patch control-net editor. See
[`MODELLING_SCOPE.md`](MODELLING_SCOPE.md) and
[`CAPABILITY_MATRIX.md`](CAPABILITY_MATRIX.md) for the tested scope.

OBJ and GLB are static snapshots of the evaluated tessellated surface at one
pose. They do not carry a skeleton, weights or keyframes. The native `.am3d`
project retains supported scene, rig and action data. Recipe sprite, toon
and animation sheets use CPU software rendering.

## Local paths and diagnostics

Preferences are held in application settings; provider keys use the selected
credential store described above. Generation records and artifacts are kept
under the application's local data root. The request-confirmation dialog
shows the local run-record location. **Help → Diagnostics...** reports an
allowlisted support summary: runtime and toolkit versions, a shortened
validated source/build identity when available, renderer route and preference,
AI-job stage and bounded attempt, saved/unsaved and modified/clean state,
object/action/undo counts, and autosave interval. It omits filenames, local
paths, prompts and credentials.
