# Full locked Windows build start

Source input7f90f1092eff741a399397f540a5cf3a38bb0902d249f7d3aaa0cfb7d4022a92, complete LOCKED_SOURCE_INPUTS.json; version1.0.0.dev1; baseline HEAD3f6f7f03d32b4d1a3af06af4fdc0724bf0436945 with authorized uncommitted changes. Windows10 IoT Enterprise LTSC19044 x64, explicit Python3.12.14. Source Windows lock SHA0a9a1b4086add4515dab3eed56cb585331b6526ef4de72e9fa83e4c38024d4d6 has all38 application/build dependencies. Bootstrap failure and supplemental capture are described precisely in BOOTSTRAP_RETRY2_TAIL_FAILURE.md.

Exact command:

```powershell
& ./build_windows.ps1 -HostPython 'C:\Users\Alex\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' *> docs/evidence/v1/phase-10/locked-build.log
```

No CaptureLock or SkipTests. The script creates a fresh isolated environment, validates the complete installed set against source lock, runs the full regression and both builds/frozen/relocation/end-identity gates. Start status running, not PASS. No source/bundled edits during the run. Final archive/payload/OS credential/independent export-reader and review evidence remains necessary. Read-only capability and external Win11/Mint/live/human/native desktop/GPU gates remain unpassed. No push/publication/release authorized or performed.
