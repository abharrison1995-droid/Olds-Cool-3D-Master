# Windows bootstrap retry 1

The new source snapshot is 840c4e12518e9d279cf713c4e5f0fba3701c3bf9b4ffb29a85d31ee5eedfe41f; complete entries are in BOOTSTRAP_RETRY1_SOURCE_INPUTS.json. Baseline HEAD remains3f6f7f03d32b4d1a3af06af4fdc0724bf0436945, with authorized uncommitted changes. This attempt follows independently verified test-selection and credential guard fixes. It preserves the first failure and its source manifest/log. Windows10 IoT Enterprise LTSC19044 x64, explicit Python3.12.14. No source or bundled-document edits during the run.

Command: `./build_windows.ps1 -CaptureLock -HostPython <explicit bundled Python3.12.14>` with full stdout/stderr redirected to bootstrap-build-retry1.log. No test skipping. A successful bootstrap is only a lock proposal; a full locked rebuild remains required. Start status: running, not PASS. External target/live/human/physical desktop gates remain unpassed.

Exact invoked command from the repository root:

```powershell
& ./build_windows.ps1 -CaptureLock -HostPython 'C:\Users\Alex\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' *> docs/evidence/v1/phase-10/bootstrap-build-retry1.log
```

Observed at2026-10-14 00:57 Europe/London:38 resolved dependencies installed, start digest matched840c4e12518e9d279cf713c4e5f0fba3701c3bf9b4ffb29a85d31ee5eedfe41f, full regression at13% without a reported failure. This is a running observation only.
