<#
.SYNOPSIS
    Build the 3D MASTER:2005 Windows executable and stage a release folder.
.DESCRIPTION
    The Windows counterpart of build_linux.sh, step for step: an isolated
    build venv, the full test suite, both PyInstaller entry points (windowed
    GUI + headless recipe CLI), a bundled-Qt-plugin check, a packaged smoke
    run, a relocation check from a path with spaces and non-ASCII
    characters, a ZIP, its SHA-256, and a build-provenance file.
.PARAMETER SkipTests
    Skip step 3. The resulting build is NOT release-qualified and says so in
    its provenance file.
.PARAMETER CaptureLock
    Write requirements-lock-windows.txt from the build venv's resolved set,
    the Windows counterpart of requirements-lock-linux.txt. Run this once on
    a machine that has completed a full build, then commit the file.
#>
param(
    [switch]$SkipTests,
    [switch]$CaptureLock
)

$ErrorActionPreference = "Stop"
# This script lives at the repo root itself (not a subdirectory like
# scripts/), so the repo root IS $PSScriptRoot -- walking up a level here
# would build from the wrong directory (and clean up the wrong "dist"/
# "release" folders) whenever invoked from outside the repo.
$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

$BuildDir = Join-Path $RepoRoot "build\windows"
$VenvDir  = Join-Path $BuildDir "venv"
$DistDir  = Join-Path $BuildDir "dist"
$WorkDir  = Join-Path $BuildDir "work"

# Run a native command (pip/pytest/PyInstaller) without $ErrorActionPreference
# = "Stop" turning its own stderr output into a fatal error. PowerShell 5.1
# wraps ANY stderr line from a native exe in a terminating NativeCommandError
# under "Stop" -- e.g. pip's harmless "new version available" notice would
# abort the whole build even though the install succeeded. $LASTEXITCODE,
# checked by the caller right after, is the real signal; this only relaxes
# the wrapper around the call itself, not the rest of the script.
function Invoke-Native {
    param([ScriptBlock]$Command)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command } finally { $ErrorActionPreference = $prev }
}

Write-Host "=== 3D MASTER:2005 Windows Build ===" -ForegroundColor Cyan
Write-Host ""

# ---- 1. Isolated build environment ----
# A dedicated venv under build\windows, never the developer's own environment
# and never the ambient interpreter: a release payload must be built from the
# pinned set in requirements-dev.txt and nothing else, so a stray locally
# installed package cannot slip in -- and the build must not silently depend
# on the build machine happening to have pytest or PyInstaller installed
# globally (finding PKG-06).
Write-Host "Step 1: Preparing an isolated build environment..." -ForegroundColor Yellow

# `py -3` first: the Windows launcher is the only one of these that reliably
# resolves to a real CPython rather than the App Execution Alias stub that
# Windows puts on PATH as "python.exe", which exits 9009 and opens the Store.
$hostPy = $null
foreach ($cand in @(
        @{ Exe = "py";      Pre = @("-3") },
        @{ Exe = "python";  Pre = @() },
        @{ Exe = "python3"; Pre = @() })) {
    if (-not (Get-Command $cand.Exe -ErrorAction SilentlyContinue)) { continue }
    $pre = $cand.Pre
    $out = Invoke-Native {
        & $cand.Exe @pre -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
    }
    if ($LASTEXITCODE -eq 0 -and $out) {
        $hostPy = @{ Exe = $cand.Exe; Pre = $pre; Version = ("$out").Trim() }
        break
    }
}
if (-not $hostPy) {
    Write-Error "No working Python found. Install CPython 3.11+ from python.org (the Microsoft Store alias is not enough)."
    exit 1
}
# ENV-01: numpy 2.4.6 declares Requires-Python >=3.11, so the pinned set
# cannot be installed on 3.10 -- fail here with the reason rather than at a
# resolver error thirty seconds later.
if ([version]$hostPy.Version -lt [version]"3.11.0") {
    Write-Error "Python 3.11+ is required (found $($hostPy.Version)); see docs/SUPPORTED_PLATFORMS.md, ENV-01."
    exit 1
}
Write-Host "  Python (host): $($hostPy.Version) via $($hostPy.Exe)"

if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir }
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
$hostPre = $hostPy.Pre
Invoke-Native { & $hostPy.Exe @hostPre -m venv $VenvDir }
$py = Join-Path $VenvDir "Scripts\python.exe"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $py)) {
    Write-Error "Could not create the build venv at $VenvDir."
    exit 1
}
Write-Host "  Build venv: $VenvDir" -ForegroundColor Green

# Install the *dev* set, not requirements.txt: steps 3 and 4 need pytest,
# jsonschema and PyInstaller, none of which are runtime dependencies. That
# separation is deliberate (nothing in requirements-dev.txt may reach a
# release payload) -- the bug was installing only the runtime half and then
# calling tools from the other half.
Write-Host "Step 2: Installing pinned build dependencies..." -ForegroundColor Yellow
Invoke-Native { & $py -m pip install --quiet --upgrade pip }
$reqPath = Join-Path $RepoRoot "requirements-dev.txt"
Invoke-Native { & $py -m pip install --quiet -r $reqPath }
if ($LASTEXITCODE -ne 0) {
    Write-Error "Dependency installation failed!"
    exit 1
}
$frozen = Invoke-Native { & $py -m pip freeze }
Write-Host "  $(@($frozen).Count) packages installed from requirements-dev.txt" -ForegroundColor Green

if ($CaptureLock) {
    # The Windows counterpart of requirements-lock-linux.txt. It is captured
    # rather than hand-written because the transitive set differs by platform
    # (pywin32-ctypes and pefile are PyInstaller's Windows-only dependencies,
    # and there is no altgraph-free path to them).
    $lockPath = Join-Path $RepoRoot "requirements-lock-windows.txt"
    ($frozen | Sort-Object) -join "`n" | Out-File -FilePath $lockPath -Encoding ascii
    Write-Host "  Wrote $lockPath -- commit it." -ForegroundColor Green
}

# ---- 2. Run tests ----
Write-Host ""
Write-Host "Step 3: Running all tests..." -ForegroundColor Yellow
if ($SkipTests) {
    Write-Host "  SKIPPED (-SkipTests): this build is not release-qualified" -ForegroundColor Red
} else {
    # offscreen for parity with build_linux.sh, and so the suite does not
    # depend on the build machine having an interactive desktop session --
    # a Windows CI runner logs in without one.
    $prevQtPlatformTests = $env:QT_QPA_PLATFORM
    $env:QT_QPA_PLATFORM = "offscreen"
    try {
        Invoke-Native { & $py -m pytest am3d/ -q --tb=short }
    } finally {
        $env:QT_QPA_PLATFORM = $prevQtPlatformTests
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Tests failed! Aborting build."
        exit 1
    }
    Write-Host "All tests passed." -ForegroundColor Green
}

# ---- 3. Build executable ----
# --distpath/--workpath keep every build artefact under build\windows\ rather
# than the repo's top-level dist\ and build\, so a build cannot pick up
# leftovers from an unrelated one and the tree stays clean.
Write-Host ""
Write-Host "Step 4: Building executable with PyInstaller..." -ForegroundColor Yellow
foreach ($stale in @($DistDir, $WorkDir)) {
    if (Test-Path $stale) { Remove-Item -Recurse -Force $stale }
}

Invoke-Native {
    & $py -m PyInstaller --clean --noconfirm `
        --distpath $DistDir --workpath $WorkDir (Join-Path $RepoRoot "am3d.spec")
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed!"
    exit 1
}
Write-Host "Build completed." -ForegroundColor Green

# Packaged headless recipe entry point (am3d-recipe.exe) -- a separate,
# smaller onefile console build alongside the windowed GUI, so an external
# agent can drive recipes without installing Python or the GUI's Qt runtime.
Write-Host ""
Write-Host "Step 4b: Building packaged recipe CLI with PyInstaller..." -ForegroundColor Yellow
Invoke-Native {
    & $py -m PyInstaller --clean --noconfirm `
        --distpath $DistDir --workpath $WorkDir (Join-Path $RepoRoot "am3d_recipe.spec")
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller recipe CLI build failed!"
    exit 1
}
Write-Host "Recipe CLI build completed." -ForegroundColor Green

# ---- 3b. Bundled Qt platform plugins ----
# The Linux build hard-checks its Wayland/xcb/offscreen plugins because a
# bundle missing one starts on the build machine and dies on the user's. The
# Windows equivalent is qwindows.dll (every GUI launch) and qoffscreen.dll
# (the --smoke-test runs below, and any headless/CI use).
Write-Host ""
Write-Host "Step 5: Verifying the bundled Qt platform plugins..." -ForegroundColor Yellow
$guiDist = Join-Path $DistDir "3D MASTER 2005 Beta"
if (-not (Test-Path $guiDist)) {
    Write-Error "Expected GUI bundle at $guiDist"
    exit 1
}
foreach ($plugin in @("qwindows.dll", "qoffscreen.dll")) {
    $found = Get-ChildItem -Path $guiDist -Recurse -File -Filter $plugin -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $found) {
        Write-Error "The bundle has no $plugin platform plugin."
        exit 1
    }
    Write-Host "  $plugin -> $($found.FullName.Substring($guiDist.Length + 1))" -ForegroundColor Green
}


# ---- 4. Stage release folder ----
Write-Host ""
Write-Host "Step 6: Staging release folder..." -ForegroundColor Yellow
$releaseDir = Join-Path $RepoRoot "release\3D MASTER 2005 Beta"
if (Test-Path $releaseDir) {
    Remove-Item -Recurse -Force $releaseDir
}
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

# Copy the built executable and _internal folder
Copy-Item -Recurse -Force "$guiDist\*" $releaseDir

# Copy the packaged recipe CLI onefile exe alongside the GUI
$recipeExeSrc = Join-Path $DistDir "am3d-recipe.exe"
if (-not (Test-Path $recipeExeSrc)) {
    Write-Error "Recipe CLI executable not found at $recipeExeSrc"
    exit 1
}
Copy-Item -Force $recipeExeSrc (Join-Path $releaseDir "am3d-recipe.exe")

# Copy examples
$examplesSrc = Join-Path $RepoRoot "assets"
$examplesDst = Join-Path $releaseDir "examples"
if (Test-Path $examplesSrc) {
    Copy-Item -Recurse -Force $examplesSrc $examplesDst
}

# Finding PKG-04: examples/ carried recipe *outputs* but no recipe, so the
# bundle could not perform the documented "run a recipe with the shipped
# CLI, then open its output in the GUI" journey on its own.
$recipeExamplesDst = Join-Path $examplesDst "recipes"
New-Item -ItemType Directory -Force -Path $recipeExamplesDst | Out-Null
Copy-Item -Force (Join-Path $RepoRoot "docs\recipes\examples\*.json") $recipeExamplesDst
Copy-Item -Force (Join-Path $RepoRoot "docs\recipes\recipe-v1.schema.json") $recipeExamplesDst

# Copy README
Copy-Item -Force (Join-Path $RepoRoot "README.md") (Join-Path $releaseDir "README.txt")
foreach ($doc in @("QUICK_START.md", "CAPABILITY_MATRIX.md", "USER_GUIDE.md", "SUPPORTED_PLATFORMS.md")) {
    Copy-Item -Force (Join-Path $RepoRoot (Join-Path "docs" $doc)) (Join-Path $releaseDir $doc)
}

# Create LICENSES placeholder
$licenseDir = Join-Path $releaseDir "LICENSES"
New-Item -ItemType Directory -Path $licenseDir -Force | Out-Null
@"
3D MASTER:2005 Beta
Copyright (c) 2026

This software uses:
- PySide6 (LGPL-3.0)
- NumPy (BSD-3-Clause)
- msgpack (Apache-2.0)
- Pillow (MIT-CMU)
- ModernGL (MIT)

See the respective packages for full license terms.
"@ | Out-File -FilePath (Join-Path $licenseDir "NOTICE.txt") -Encoding utf8

Write-Host "Release staged at: $releaseDir" -ForegroundColor Green

# ---- 5. Smoke test ----
Write-Host ""
Write-Host "Step 6b: Verifying the staged executables and running the bundled recipe..." -ForegroundColor Yellow

# Basic smoke test: verify executable exists and can start
$exePath = Join-Path $releaseDir "3D MASTER 2005.exe"
if (Test-Path $exePath) {
    Write-Host "  Executable found: $exePath" -ForegroundColor Green
    Write-Host "  File size: $((Get-Item $exePath).Length / 1MB -as [int]) MB" -ForegroundColor Green
} else {
    Write-Error "Executable not found at $exePath"
    exit 1
}

# Recipe CLI smoke test: actually invoke it (--validate-only, no output
# written) against the bundled minimal example, so a broken onefile bundle
# (missing hidden import, etc.) fails the build instead of shipping silently.
$recipeExePath = Join-Path $releaseDir "am3d-recipe.exe"
if (Test-Path $recipeExePath) {
    Write-Host "  Recipe CLI found: $recipeExePath" -ForegroundColor Green
    $minimalRecipe = Join-Path $recipeExamplesDst "minimal.json"
    Invoke-Native { & $recipeExePath --recipe $minimalRecipe --validate-only }
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Packaged recipe CLI failed to validate the bundled example recipe!"
        exit 1
    }

    # Validation never touches geometry, exporters or writers, so the bundled
    # recipe is also actually built (journey 6) into a scratch directory
    # outside the release payload.
    $recipeOut = Join-Path ([System.IO.Path]::GetTempPath()) ("am3d_recipe_run_" + [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $recipeOut | Out-Null
    $recipeReport = Join-Path $recipeOut "report.json"
    Invoke-Native { & $recipeExePath --recipe $minimalRecipe --out $recipeOut } |
        Out-File -Encoding utf8 $recipeReport
    if ($LASTEXITCODE -ne 0) {
        Get-Content $recipeReport
        Write-Error "Packaged recipe CLI failed to build the bundled example recipe!"
        exit 1
    }
    $produced = Get-ChildItem -Recurse -File $recipeOut |
        Where-Object { $_.Name -ne "report.json" }
    if ($produced.Count -eq 0) {
        Write-Error "The packaged recipe reported success but wrote nothing!"
        exit 1
    }
    Remove-Item -Recurse -Force $recipeOut
    Write-Host "  Recipe CLI validated and built the bundled example recipe ($($produced.Count) file(s))." -ForegroundColor Green
} else {
    Write-Error "Recipe CLI executable not found at $recipeExePath"
    exit 1
}

# ---- 6. Packaged GUI smoke mode ----
# Drives the actual packaged .exe through a real workflow (blank startup,
# primitive/profile creation through undo commands, material reference,
# weighted action playback, multi-object software render, save/reopen,
# transformed export) via its own --smoke-test flag (see am3d/ui/smoke.py
# and MainWindow.main() in am3d/ui/app.py), instead of only checking that
# the file exists. Runs under QT_QPA_PLATFORM=offscreen so it works on a
# headless build machine; a timeout guards against a hang blocking CI
# forever, and the manifest is checked for completeness (every step "ok"),
# not just the process exit code, so a partially-run smoke test still
# fails the build instead of shipping as silent "missing evidence".
Write-Host ""
Write-Host "Step 7: Running packaged GUI smoke mode..." -ForegroundColor Yellow
# The manifest and the files the run produces go to a scratch directory,
# never into the payload: they name absolute build-machine paths, and the
# release folder must contain only what a user is meant to receive.
$smokeDir = Join-Path ([System.IO.Path]::GetTempPath()) ("am3d_build_smoke_" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $smokeDir | Out-Null
$manifestPath = Join-Path $smokeDir "smoke_manifest.json"
$prevQtPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
$smokeTimeoutMs = 60000
$smokeStdout = Join-Path $smokeDir "smoke_stdout.txt"
$smokeStderr = Join-Path $smokeDir "smoke_stderr.txt"
try {
    # Raw System.Diagnostics.Process, not Start-Process -PassThru: the
    # cmdlet has two sharp edges that both bit here empirically. (1) its
    # -ArgumentList joins array elements into a single command-line string
    # WITHOUT auto-quoting elements that contain spaces -- and $manifestPath
    # does, since the release folder is "3D MASTER 2005 Beta" -- so the
    # packaged exe's argv split "--out" from a truncated "...\release\3D",
    # and the smoke test (which ran and passed) silently wrote its real
    # manifest to that truncated path (a stray file literally named "3D"
    # next to the release folder) while this script reported "no manifest
    # produced" at the real path. (2) even after quoting fixed that, the
    # -PassThru process object's .ExitCode read back empty/unreliable
    # specifically when this script's own output was itself piped (e.g.
    # through Tee-Object, as a CI wrapper commonly does) -- constructing
    # and owning the Process object directly avoids both.
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exePath
    $psi.Arguments = "--smoke-test --out `"$manifestPath`""
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $smokeProc = [System.Diagnostics.Process]::Start($psi)
    $stdoutTask = $smokeProc.StandardOutput.ReadToEndAsync()
    $stderrTask = $smokeProc.StandardError.ReadToEndAsync()
    $finished = $smokeProc.WaitForExit($smokeTimeoutMs)
    if (-not $finished) {
        Stop-Process -Id $smokeProc.Id -Force -ErrorAction SilentlyContinue
        Write-Error "Packaged smoke test timed out after $($smokeTimeoutMs / 1000)s!"
        exit 1
    }
    $stdoutTask.Result | Out-File -FilePath $smokeStdout -Encoding utf8
    $stderrTask.Result | Out-File -FilePath $smokeStderr -Encoding utf8
    $smokeExitCode = $smokeProc.ExitCode
} finally {
    $env:QT_QPA_PLATFORM = $prevQtPlatform
}

if (-not (Test-Path $manifestPath)) {
    Write-Error "Packaged smoke test produced no manifest at $manifestPath (exit code $smokeExitCode)!"
    if (Test-Path $smokeStdout) { Write-Host "--- stdout ---"; Get-Content $smokeStdout | Write-Host }
    if (Test-Path $smokeStderr) { Write-Host "--- stderr ---"; Get-Content $smokeStderr | Write-Host }
    exit 1
}
$smokeManifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$incompleteSteps = $smokeManifest.steps | Where-Object { $_.status -ne "ok" }
if ($smokeExitCode -ne 0 -or $smokeManifest.ok -ne $true -or $incompleteSteps) {
    Write-Error "Packaged smoke test failed or is incomplete (exit code $smokeExitCode)!"
    Get-Content $manifestPath | Write-Host
    exit 1
}
Write-Host "  Smoke test passed: $($smokeManifest.steps.Count) steps, all ok." -ForegroundColor Green

# The payload must contain only what a user receives. A build-machine path
# inside it means a build artefact leaked into the release folder (this
# caught the smoke manifest, which used to be written straight into it).
Write-Host ""
Write-Host "Step 7c: Checking the payload for build-machine references..." -ForegroundColor Yellow
$leaked = Get-ChildItem -Path $releaseDir -Recurse -File |
    Where-Object { $_.Length -lt 4MB } |
    Where-Object {
        (Select-String -Path $_.FullName -SimpleMatch -Pattern $RepoRoot `
            -List -ErrorAction SilentlyContinue) -ne $null
    } | Select-Object -First 5
if ($leaked) {
    Write-Error ("Release payload references the build location:`n" +
        (($leaked | ForEach-Object { $_.FullName }) -join "`n"))
    exit 1
}
Write-Host "  No build-machine paths in the payload." -ForegroundColor Green

# ---- 7. Release ZIP and checksum ----
# Phase 6 bullet 5: ship a single reproducible archive plus its checksum,
# not just the loose release folder that Step 5 staged.
Write-Host ""
Write-Host "Step 8: Packaging release ZIP and checksum..." -ForegroundColor Yellow
$version = ((Invoke-Native { & $py -c "import am3d; print(am3d.__version__)" }) -join "").Trim()
$releaseParent = Split-Path $releaseDir -Parent
$zipName = "3D-MASTER-2005-Beta-$version-win64.zip"
$zipPath = Join-Path $releaseParent $zipName
if (Test-Path $zipPath) {
    Remove-Item -Force $zipPath
}
# Zips the release folder itself as the archive's single top-level entry
# (so extracting reproduces "3D MASTER 2005 Beta\..." rather than dumping
# loose files), matching how the recipient is expected to unpack it.
Compress-Archive -Path $releaseDir -DestinationPath $zipPath -CompressionLevel Optimal
$zipHash = Get-FileHash -Algorithm SHA256 -Path $zipPath
$checksumPath = "$zipPath.sha256"
# sha256sum-compatible format ("<hash> *<filename>") so it can be verified
# with either PowerShell or a standard sha256sum on the recipient's end.
"$($zipHash.Hash.ToLower()) *$zipName" | Out-File -FilePath $checksumPath -Encoding ascii -NoNewline
Write-Host "  Release ZIP: $zipPath" -ForegroundColor Green
Write-Host "  SHA-256: $($zipHash.Hash)" -ForegroundColor Green

# ---- 7b. Build provenance ----
# The counterpart of release/BUILD_PROVENANCE-linux.txt: what was built, from
# which commit, with which interpreter and which resolved package set. A
# release artifact without this cannot be traced back to a tree.
Write-Host ""
Write-Host "Step 8b: Writing build provenance..." -ForegroundColor Yellow
$gitCommit = Invoke-Native { & git -C $RepoRoot rev-parse HEAD }
if ($LASTEXITCODE -ne 0) { $gitCommit = "unknown" }
$gitDirty = Invoke-Native { & git -C $RepoRoot status --porcelain }
$gitState = "unknown"
if ($LASTEXITCODE -ne 0) { $gitState = "unknown" }
elseif ([string]::IsNullOrWhiteSpace(($gitDirty -join ""))) { $gitState = "clean" }
else { $gitState = "DIRTY -- built from uncommitted changes" }
$os = Get-CimInstance Win32_OperatingSystem
$pyBuildVersion = ((Invoke-Native { & $py -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" }) -join "").Trim()
$pyInstallerVersion = ((Invoke-Native { & $py -m PyInstaller --version }) -join "").Trim()
if ($SkipTests) { $testState = "SKIPPED -- not release-qualified" } else { $testState = "full suite passed" }
$provenance = @(
    "3D MASTER:2005 -- Windows build provenance"
    "archive          : $zipName"
    "sha256           : $($zipHash.Hash.ToLower())"
    "am3d version     : $version"
    "git commit       : $(($gitCommit -join '').Trim())"
    "git status       : $gitState"
    "built on         : $($os.Caption) $($os.Version) $($env:PROCESSOR_ARCHITECTURE)"
    "python (host)    : $($hostPy.Version)"
    "python (build)   : $pyBuildVersion"
    "pyinstaller      : $pyInstallerVersion"
    "tests            : $testState"
    ""
    "pinned build set (pip freeze):"
) + ($frozen | ForEach-Object { "  $_" })
$provenancePath = Join-Path $releaseParent "BUILD_PROVENANCE-windows.txt"
$provenance -join "`r`n" | Out-File -FilePath $provenancePath -Encoding utf8
Write-Host "  $provenancePath" -ForegroundColor Green

# ---- 8. Verify release contents from a relocated path ----
# Extracts the ZIP to a throwaway location with a space and a non-ASCII
# character in its name (Phase 6 bullet 5: "paths containing spaces/
# non-ASCII"), independent of the build/dist/release directories the build
# itself just produced, then re-runs both packaged entry points from there
# with inputs that are not the repo's own files -- so this step must fail if
# the packaged app secretly depends on an absolute path from the build
# machine (e.g. a leftover PyInstaller temp path) rather than being truly
# relocatable.
Write-Host ""
Write-Host "Step 9: Verifying release contents from a relocated path..." -ForegroundColor Yellow
$verifyRoot = Join-Path ([System.IO.Path]::GetTempPath()) "am3d verify éé $([System.Guid]::NewGuid().ToString('N').Substring(0,8))"
try {
    New-Item -ItemType Directory -Path $verifyRoot -Force | Out-Null
    Expand-Archive -Path $zipPath -DestinationPath $verifyRoot -Force
    $verifiedReleaseDir = Get-ChildItem -Path $verifyRoot -Directory | Select-Object -First 1
    if (-not $verifiedReleaseDir) {
        Write-Error "Extracted ZIP contains no release folder!"
        exit 1
    }
    $verifiedExe = Join-Path $verifiedReleaseDir.FullName "3D MASTER 2005.exe"
    $verifiedRecipeExe = Join-Path $verifiedReleaseDir.FullName "am3d-recipe.exe"
    if (-not (Test-Path $verifiedExe) -or -not (Test-Path $verifiedRecipeExe)) {
        Write-Error "Extracted release is missing an executable ($verifiedExe / $verifiedRecipeExe)!"
        exit 1
    }

    # Recipe entry point: validate a source-independent copy of the minimal
    # recipe (not a path back into the repo) from the relocated exe.
    $verifyRecipeJson = Join-Path $verifyRoot "standalone_recipe.json"
    Copy-Item -Force (Join-Path $RepoRoot "docs\recipes\examples\minimal.json") $verifyRecipeJson
    Invoke-Native { & $verifiedRecipeExe --recipe $verifyRecipeJson --validate-only }
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Relocated recipe CLI failed to validate a source-independent recipe!"
        exit 1
    }

    # GUI entry point: re-run the smoke test from the relocated copy, with
    # --out also pointing at a spaced/non-ASCII path, to confirm
    # software-only operation (QT_QPA_PLATFORM=offscreen) survives being
    # moved off the build machine's own directories.
    $verifyManifestPath = Join-Path $verifyRoot "verify_smoke_manifest.json"
    $prevQtPlatform2 = $env:QT_QPA_PLATFORM
    $env:QT_QPA_PLATFORM = "offscreen"
    try {
        $vpsi = New-Object System.Diagnostics.ProcessStartInfo
        $vpsi.FileName = $verifiedExe
        $vpsi.Arguments = "--smoke-test --out `"$verifyManifestPath`""
        $vpsi.UseShellExecute = $false
        $vpsi.CreateNoWindow = $true
        $vpsi.RedirectStandardOutput = $true
        $vpsi.RedirectStandardError = $true
        $vproc = [System.Diagnostics.Process]::Start($vpsi)
        $vStdoutTask = $vproc.StandardOutput.ReadToEndAsync()
        $vStderrTask = $vproc.StandardError.ReadToEndAsync()
        $vFinished = $vproc.WaitForExit($smokeTimeoutMs)
        if (-not $vFinished) {
            Stop-Process -Id $vproc.Id -Force -ErrorAction SilentlyContinue
            Write-Error "Relocated packaged smoke test timed out after $($smokeTimeoutMs / 1000)s!"
            exit 1
        }
        $vExitCode = $vproc.ExitCode
        $vStdoutTask.Result | Out-Null
        $vStderrTask.Result | Out-Null
    } finally {
        $env:QT_QPA_PLATFORM = $prevQtPlatform2
    }
    if (-not (Test-Path $verifyManifestPath)) {
        Write-Error "Relocated packaged smoke test produced no manifest (exit code $vExitCode)!"
        exit 1
    }
    $verifyManifest = Get-Content $verifyManifestPath -Raw | ConvertFrom-Json
    $verifyIncomplete = $verifyManifest.steps | Where-Object { $_.status -ne "ok" }
    if ($vExitCode -ne 0 -or $verifyManifest.ok -ne $true -or $verifyIncomplete) {
        Write-Error "Relocated packaged smoke test failed or is incomplete (exit code $vExitCode)!"
        Get-Content $verifyManifestPath | Write-Host
        exit 1
    }
    Write-Host "  Verified from: $verifyRoot" -ForegroundColor Green
    Write-Host "  Relocated recipe CLI and GUI smoke test both passed." -ForegroundColor Green
} finally {
    if (Test-Path $verifyRoot) {
        Remove-Item -Recurse -Force $verifyRoot -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "=== Build complete! ===" -ForegroundColor Cyan
Write-Host "Release folder: $releaseDir"
Write-Host "Release ZIP: $zipPath"
Write-Host "Checksum: $checksumPath"
Write-Host "Provenance: $provenancePath"
Write-Host "Executable: $exePath"
Write-Host ""
Write-Host "To smoke test manually, run the executable from the release folder."
Write-Host "Next steps: verify Home screen, New Empty, Create Primitive, Save, and relaunch."