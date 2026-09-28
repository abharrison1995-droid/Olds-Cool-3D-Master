# External agent recipe trial 2

## Commands and results

Initial deliberately invalid run:

```sh
python -m am3d.recipes --recipe /tmp/am3d-agent-recipe-trial-2/recipe-initial.json --out /tmp/am3d-agent-recipe-trial-2/failed-output
```

Exit code: `1`. Complete captured streams are `failed.stdout` and `failed.stderr`; exact status is in `failed.exitcode`.

Correction: using `error_records[0].message` from `failed.stdout` (`unknown pattern 'scales'`, allowed values `bricks`, `checker`, `gradient`, `noise`, `solid`), changed only `materials[0].pattern` from `scales` to `checker`. The checker parameters already present in the initial recipe were retained. The corrected recipe is `recipe-corrected.json`.

Corrected validation:

```sh
python -m am3d.recipes --recipe /tmp/am3d-agent-recipe-trial-2/recipe-corrected.json --out /tmp/am3d-agent-recipe-trial-2/validation-output --validate-only
```

Exit code: `0`. Complete streams are `validate.stdout` and `validate.stderr`; exact status is in `validate.exitcode`.

Successful export:

```sh
python -m am3d.recipes --recipe /tmp/am3d-agent-recipe-trial-2/recipe-corrected.json --out /tmp/am3d-agent-recipe-trial-2/successful-output
```

Exit code: `0`. Complete streams are `export.stdout` and `export.stderr`; exact status is in `export.exitcode`.

## Animation check

Yes. The animation sheet visibly shows the leg geometry changing position across sampled walk frames. I inspected frames 0, 1, 3, and 11; the lower leg silhouettes shift between frames. The legs remain small under the rounded shell in this preview.

## Limitations

The supported checker pattern gives a patterned copper shell but does not reproduce literal scale shapes. The animation sheet is a flat-color preview, and the OBJ and GLB are static pose snapshots; the editable `.am3d` project retains the rig/action. The sheet shows a rounded shell with small low-profile legs, so the beetle silhouette is simple.

## Files

- `recipe-initial.json`
- `recipe-corrected.json`
- `failed.stdout`, `failed.stderr`, `failed.exitcode`
- `validate.stdout`, `validate.stderr`, `validate.exitcode`
- `export.stdout`, `export.stderr`, `export.exitcode`
- `walk_frames_inspection.png` (inspection montage made from the exported sheet)
- `successful-output/clockwork_beetle_project.am3d`
- `successful-output/clockwork_beetle_mesh.obj`
- `successful-output/clockwork_beetle_mesh.mtl`
- `successful-output/clockwork_beetle_mesh_shell.png`
- `successful-output/clockwork_beetle_snapshot.glb`
- `successful-output/clockwork_beetle_walk_sheet.png`
- `successful-output/shell_atlas.png`
