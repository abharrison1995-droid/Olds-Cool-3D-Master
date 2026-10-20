# 3D MASTER:2005 — development-source quick start

The current checkout declares version `1.0.0.dev1` and contains the in-app
**Create with AI...** source workflow. This is a development test candidate,
not a release candidate or stable V1 artifact. Live-provider, benchmark,
human-quality and selected-platform acceptance remain open. Local frozen/test
results apply to the exact candidate identified in its companion build
provenance, inputs, checksum and acceptance reports; they do not alone qualify
V1. The accepted Mint preview archive is older, has a different identity, and
does not qualify this source workflow. See
[`SUPPORTED_PLATFORMS.md`](SUPPORTED_PLATFORMS.md).

## Run from a source checkout

With a supported Python source environment and the development dependencies
installed, start the desktop application and recipe CLI with:

```text
python -m am3d.ui
python -m am3d.recipes --recipe docs/recipes/examples/minimal.json --out ./generated/minimal
```

The GUI and CLI are separate workflows. The recipe CLI takes declarative
`recipe-v1` JSON; it does not call a model provider. It prints a JSON result
and artifact manifest on standard output, with diagnostics on standard
error. Use `--validate-only` to check a recipe without generating files.

## Create a project from a brief

1. On Home, choose **Create with AI...**.
2. Enter the asset description in **Brief**. No project is transmitted by
   starting the workspace or typing the brief.
3. Open **AI Settings…**. Set the exact model name supported by your provider
   account. There is no default model. The current source accepts HTTPS on
   `api.openai.com`; other hosts are rejected.
4. Choose **System credential store** or **Session-only key (memory)**. Enter
   the API key in the password field and select **Save**. The key is not
   written to application preferences. The persistent option explicitly uses
   Windows Credential Manager or Linux Secret Service where available; the
   session option keeps the key only in memory for the running process.
5. Choose **Generate…**. Read the destination, model, request-content
   disclosure, limits and cost statement. The provider call begins only if
   you choose **Send request**. **Cancel** closes the confirmation without
   sending the request.
6. Follow **Run status**, **Stage**, **Attempt** and **Elapsed**. The source
   pipeline permits at most four candidate slots and five semantic provider
   calls; its adapter permits up to ten HTTP attempts overall. An HTTP
   attempt is limited to 90 seconds, the shared run deadline to 600 seconds,
   and each worker attempt to 180 seconds. Cancellation completes only after
   the active operation acknowledges it.
7. A completed result includes a checked whole-scene preview, a project
   summary, limitations and the accepted recipe/check report. The checks
   cover structure, selected request requirements, bounded files and native
   reopenability. They do not score artistic quality.
8. Choose **Open in Editor** to open a verified writable copy. The regular
   document dirty guard protects an existing project; cancelling the guard
   leaves the current project open and the generated result available.

## Review history and refine

In **Saved generations and refinements**, choose **Refresh History**. Select
a completed row to verify its saved files, native project and checked
preview. The detail view includes the accepted brief, parent/child lineage,
limitations and recipe-change summary. Choose **Restore Selected in Editor**
to open a new writable copy through the normal dirty-document guard; the
saved history record itself remains unchanged. Interrupted rows remain
unsuccessful until explicitly retried. **Delete Selected** requires
confirmation, and deleting a parent requires another confirmation; children
are never deleted automatically.

To refine, enter a change and choose **Refine Selected…**. The explicit
confirmation shows the selected parent and change request. The request sends
the saved parent's accepted brief and recipe, verified parent-child identity
and your change; it returns a full replacement recipe. The current project,
its files, images, manual edits and paths are not sent or merged. The change
field is limited to 4 KiB, and transmission still requires **Send request**.

If the current authored session differs from the verified saved generation,
the app offers **Save manual copy**, **Refine original generation**, or
**Cancel**. Saving a manual copy follows the normal Save As path before
starting a child from the original saved recipe. Refining the original keeps
the current session open and uses that same saved recipe. Cancel preserves
the session and undo history. No automatic merge occurs. These history and
refinement flows have owner-run offline UI evidence and passed a bounded
independent local preservation/refinement review. The exact locked Windows
development candidate has also passed the full source regression and fixed
offline frozen history/refinement checks. The repository `PROGRESS.md` and
`docs/evidence/v1/ACCEPTANCE_LEDGER.md` record current independent-review
dispositions and the exact local candidate identity.
Windows 11 and Mint target qualification, native/read-only/GPU gates,
live-provider and human-quality gates, and overall V1/RC acceptance remain
open.

Generation costs are unknown. The configured limits bound local calls and
worker time; they do not cap provider input-token billing or dollar spend.
Do not put credentials or private information in the brief. The confirmation
dialog describes what is sent before each request.

## Data and provider setup

For a new generation, the request can include the text brief, normalized
requirements produced from it, candidate recipes, fixed recipe schema and
capability context, and bounded sanitized repair or check feedback. The
current project, project files, images and local filesystem paths are not
sent. The API key is sent in the authorization header.

Provider endpoint, exact model name and credential-storage choice are kept in
application preferences; the credential itself is stored only in the selected
OS store or in the process-memory session store. The provider is contacted
only after the confirmation step. Run records and checked files are saved
locally. The request-confirmation dialog shows the local run-record location.
**Help → Diagnostics...** reports an allowlisted support summary: runtime and
toolkit versions, a shortened validated source/build identity when available,
renderer route and preference, AI-job stage and bounded attempt, saved/unsaved
and modified/clean state, object/action/undo counts, and autosave interval. It
omits filenames, local paths, prompts and credentials.

## Historical preview bundle

The accepted Linux Mint 22.3 preview archive is identified by SHA-256
`4d41c0cf7cbf069edf907483cbf16ff4b0f8dcc54130aa791a16a049568d6433` and
build-input digest
`6e62c8cdf6ecfb578885f852391b5d8b50d118a6405b9f4817cb36aa0fd60283`. Its
recorded GUI checks used Qt offscreen mode and software rendering; it is not
a V1-qualified native desktop build and does not contain the current V1
workflow. The older MX 25.2 build is a separate artifact, not a substitute for
the Mint preview or a qualification of current source.

Windows 11 and Linux Mint 22.3 remain the selected V1 targets and their V1
qualification remains open. A local frozen candidate or offscreen check does
not establish native display, DPI, physical GPU, clean-machine, live-provider,
or target acceptance; consult the companion reports for results tied to a
specific candidate.

## Modeling and export limits

The editor can create primitive patches and spline profiles. Recipe-generated
lathe/extrude surfaces retain editable source profiles in the current source;
this does not provide a general arbitrary patch control-net editor. An open
construction spline by itself has no surface triangles. OBJ and GLB export a
static tessellated pose and do not contain skeletons, weights or keyframes.
Recipe sprite/toon/animation sheets are CPU-rendered images. See
[`MODELLING_SCOPE.md`](MODELLING_SCOPE.md) and
[`CAPABILITY_MATRIX.md`](CAPABILITY_MATRIX.md).
