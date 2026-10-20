# Independent export parser — retained source acceptance artifacts

2026-10-13, Windows 10 IoT Enterprise LTSC 19044 x64. This is local source evidence, not frozen or target-platform qualification. The source acceptance report is the exact retained report identified in strict-source-followup.json (SHA-256 677a536874343ccda3642a74063072c65d8a0717bbc9a2d8bc783b43e5ee6911). Its source input was still moving; no final candidate identity is asserted.

The QA-only developer-environment reader is Trimesh 5.1.1 (installation provenance in ROOT_EXTERNAL_READER_SETUP.md). It is absent from product requirements and isolated build inputs. The trusted host-selected input was the retained self-test records/generations directory, with Windows extended-path spelling to access its long paths.

Command, from repository root:

```powershell
.venv/Scripts/python.exe work/v1/external_reader_probe.py '\\?\C:\Users\Alex\Desktop\Olds-Cool-3D-Master\work\v1\phase10-source-acceptance-b38a5a81b5834ddb8ba7d0476588cf08\test_source_acceptance_runs_fi0\selftest-output\phase10-ai-self-test\records\generations' > docs/evidence/v1/phase-10/source-independent-reader.json
```

Exit 0. Both parent and child OBJ and GLB parsed with remote loading disabled and processing disabled. Each contained 2,700 faces, finite vertices, valid indices and nonzero bounds. Paired OBJ/GLB face counts and world bounds matched; parent dimensions were 1×1×1 and child 1×1.5×1. Each format exposed blue RGBA material [20,61,230,255], consistent with the fixed fixture. The JSON receipt records exact artifact hashes, geometry, bounds and materials. Parser SHA-256: 5ddd92fa9e3d43aab6d9a60c2dc44cc35ff27f8031d4429a3034f9bc61e77dad. Receipt SHA-256: 640ecf3fadebbea9dc4a1702e921ffe08a436cdfcbaf4ab6f2227c09e77c8b6c.

This does not establish live asset quality, native DCC import, a frozen build, Windows 11/Mint acceptance or physical GPU behavior. Repeat the independent parser against retained outputs from the exact final frozen candidate before accepting its export gate.
