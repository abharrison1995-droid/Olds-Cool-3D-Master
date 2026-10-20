# Windows bootstrap source freeze

Started2026-10-13 23:17:49 UTC (2026-10-14 Europe/London). Baseline HEAD3f6f7f03d32b4d1a3af06af4fdc0724bf0436945 with authorized uncommitted V1 changes. Version1.0.0.dev1. Complete frozen input digest6c570bdd18102fb51f76e3e74626e8ecfd78c05e6d043c3ac47972089579aa9b; exact entries are in BOOTSTRAP_SOURCE_INPUTS.json. Git whitespace check passed with LF/CRLF advisories only. No implementation/source/bundled-document edits are permitted during this build.

Phase9 local gate is independently accepted; receipt SHA-256dcb410dc53e0e4bb2771d703cd332f7c30809606086240ed4d5de184093cf440. Earlier phase/source evidence retains its own hashes and qualification limits; it does not replace this integrated regression.

Command from repository root:

```powershell
& ./build_windows.ps1 -CaptureLock -HostPython 'C:\Users\Alex\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' *> docs/evidence/v1/phase-10/bootstrap-build.log
```

HostWindows10 IoT Enterprise LTSC19044 x64, explicit basePython3.12.14; script creates an isolated build/windows/venv. Tests run offscreen with --maxfail=1 --tb=short to retain the first named failure. A successful bootstrap proposes a lock only after source/build/frozen/relocation checks. It does not create a final locked candidate; source-lock promotion and another full build are required. TargetWindows11/Mint, live provider, native display/scaling/GPU and human quality remain unpassed. Read-only capability may remain UNPASSED on this execution token; no ACL mutation is allowed before successful restore preflight.

Status at this receipt: running, not PASS. Final exit/result/identities will be appended separately; do not infer success from process startup.
