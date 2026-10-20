# V1 Phase 0 baseline and documentation acceptance

Date: 2026-10-13. Starting implementation HEAD:
`3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`; original tracked working tree clean.
No repository `AGENTS.md` or ancestor instruction file was found in the checked
paths. Historical `.agents/artifacts/` contains an archived execution checkpoint,
not current instructions.

Host: Windows 10 IoT Enterprise LTSC x86-64, build `10.0.19044`.
Python: isolated `.venv`, CPython 3.12.14 from the desktop bundled runtime.
Installed pinned development requirements; no global environment was changed.
`environment-windows.txt` is the resolved environment snapshot, including the
two new Phase 1 dependencies installed during baseline work. It is not a
release Windows lock or a Linux environment capture.

## Executed checks

| Command | Result |
| --- | --- |
| `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest am3d/ -q --ignore=am3d/ai` | Exit 0; 738 passed, four existing Qt mouse-event deprecation warnings, 610.41 seconds. Full output: `baseline-tests.txt`. Existing implementation suite only; new AI files excluded. |
| `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m am3d.ui --smoke-test --out work/v1/baseline-smoke.json` | Exit 0; `ok:true`, all 14 steps passed. Full output: `baseline-smoke.txt`; generated assets retained in ignored `work/v1/`. |
| `git diff --check` after documentation edits | Exit 0. Git's LF-to-CRLF advisory is not a whitespace failure. |

The baseline source suite and smoke launch used separate processes; their
execution overlapped briefly. No failing tests were observed. Existing runtime
files were unchanged when these checks began; Phase 1's separate new modules
were excluded from the baseline source collection. This is current Windows 10
offscreen/source evidence, not Windows 11 native, frozen, DPI or GPU acceptance.

## Review and disposition

The fresh read-only plan review passed; see `PLAN_REVIEW.md`. A separate Luna
implementer reconciled the assigned documents. The orchestrator inspected the
diff and entry-point consistency: V1 active authority, implemented versus
planned workflow, distinct historical archive checksums, accurate recipe graph
and limited helper capabilities, CPU sheet boundary, and candidate versus
supported release production. Historical evidence was preserved. Provider
reviewer may supply an additional bounded documentation check independently.

Phase 0 is **complete** for plan authority, documentation reconciliation and
baseline recording. New AI phases and platform acceptance remain distinct and
unpassed until their own evidence exists. User approval authorizes implementation,
not remote pushes or publication.
