# Phase 6 generated-profile edit correction

Status: the confirmed source-pipeline gap is corrected and covered by offline tests. The Phase 6 gate remains open pending fresh independent review and the separately required frozen/native acceptance. This evidence does not claim a general patch control-net editor.

The pre-change read-only reproduction used HEAD `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945` and executor SHA-256 `2454d5c759ed1ddee47b2814d8d74deb8e466aead2d6b47decd52f49f45b1a6a`. It found that recipe `lathe` and `extrude` patches had no generator, and moving the extra `guide` spline left referenced rendered triangles unchanged. The original receipt remains at [profile-gap-before.json](profile-gap-before.json).

`RecipeExecutor` now adds a deterministic, collision-safe source spline after every explicitly authored spline for recipe `lathe` and `extrude` objects. Lathe profiles retain the existing X=radius/Y=axial source convention for each revolution axis; extrude profiles retain their three coordinates. Their patches now store the existing `core.generators` operation and whitelisted parameters. Every recipe-built patch also stores the degree values returned by its primitive builder. No recipe vocabulary, schema, geometry engine, renderer, provenance code, or generic net editor changed.

The focused tests confirm that both profile primitives keep their initial control nets, generator parameters, and degrees through actual recipe execution and native `.am3d` export/reopen. Moving the referenced profile changes vertices used by rendered triangles; exact undo and redo restore the prior and edited meshes. The fixture covers a Z-axis lathe and a twisted extrusion, preserves an authored spline whose name collides with the helper's base name, keeps existing explicit-weight indices, and checks finite auto-rig deformation. Legacy primitive nets and effective degrees still match their builders. A record-store fixture also confirms that a saved manual profile edit marks the working native project as diverged while its immutable history hash and manifest remain unchanged.

Verification used `.venv\Scripts\python.exe` on the Windows 10 IoT Enterprise LTSC 19044 host with `QT_QPA_PLATFORM=offscreen`:

- `am3d/recipes/test_executor.py`: 101 passed.
- `am3d/ui/test_generated_profile_edit.py` and `am3d/ui/test_edit_surface.py`: 16 passed.

Exact commands and pytest summaries are recorded in [profile-edit-gap.stdout.txt](profile-edit-gap.stdout.txt). [profile-edit-gap-source-identity.json](profile-edit-gap-source-identity.json) records the baseline commit and SHA-256 identities of the owned source and test files. The worktree contains other V1 edits; this identity covers only the files owned by this bounded correction.

The supported edit is the lathe/extrude source profile through the existing spline control-point commands. A separate guide spline still does not reshape a baked primitive, and arbitrary patch-net editing remains outside this change. No model/provider call, live UI run, frozen build, commit, push, or release was performed.
