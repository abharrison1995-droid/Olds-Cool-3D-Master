<#
.SYNOPSIS
    Build the 3D MASTER:2005 Windows executable and stage a release folder.
.DESCRIPTION
    Verifies Python environment, runs tests, builds with PyInstaller,
    runs a packaged smoke test, and stages the release.
#>

$ErrorActionPreference = "Stop"
# This script lives at the repo root itself (not a subdirectory like
# scripts/), so the repo root IS $PSScriptRoot -- walking up a level here
# would build from the wrong directory (and clean up the wrong "dist"/
# "release" folders) whenever invoked from outside the repo.
$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot

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

# ---- 1. Verify Python environment ----
Write-Host "Step 1: Verifying Python environment..." -ForegroundColor Yellow
$py = "python"
try {
    $ver = & $py --version
    Write-Host "  Python: $ver"
} catch {
    Write-Error "Python not found. Make sure Python 3.10+ is installed."
    exit 1
}

# Install pinned dependencies from requirements.txt -- the single source of
# truth for reproducible versions, instead of an unpinned per-package list
# that can silently drift (or, as before, reference packages am3d no
# longer uses at all).
Write-Host "Step 2: Installing pinned dependencies from requirements.txt..." -ForegroundColor Yellow
$reqPath = Join-Path $RepoRoot "requirements.txt"
Invoke-Native { & $py -m pip install -r $reqPath }
if ($LASTEXITCODE -ne 0) {
    Write-Error "Dependency installation failed!"
    exit 1
}

# ---- 2. Run tests ----
Write-Host ""
Write-Host "Step 3: Running all tests..." -ForegroundColor Yellow
Invoke-Native { & $py -m pytest am3d/ -q --tb=short }
if ($LASTEXITCODE -ne 0) {
    Write-Error "Tests failed! Aborting build."
    exit 1
}
Write-Host "All tests passed." -ForegroundColor Green

# ---- 3. Build executable ----
Write-Host ""
Write-Host "Step 4: Building executable with PyInstaller..." -ForegroundColor Yellow
$buildDir = Join-Path $RepoRoot "dist"
if (Test-Path $buildDir) {
    Remove-Item -Recurse -Force $buildDir
}

Invoke-Native { & $py -m PyInstaller --clean am3d.spec }
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
Invoke-Native { & $py -m PyInstaller --clean am3d_recipe.spec }
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller recipe CLI build failed!"
    exit 1
}
Write-Host "Recipe CLI build completed." -ForegroundColor Green

# ---- 4. Stage release folder ----
Write-Host ""
Write-Host "Step 5: Staging release folder..." -ForegroundColor Yellow
$releaseDir = Join-Path $RepoRoot "release\3D MASTER 2005 Beta"
if (Test-Path $releaseDir) {
    Remove-Item -Recurse -Force $releaseDir
}
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

# Copy the built executable and _internal folder
$distDir = Join-Path $RepoRoot "dist\3D MASTER 2005 Beta"
if (Test-Path $distDir) {
    Copy-Item -Recurse -Force "$distDir\*" $releaseDir
}

# Copy the packaged recipe CLI onefile exe alongside the GUI
$recipeExeSrc = Join-Path $RepoRoot "dist\am3d-recipe.exe"
if (Test-Path $recipeExeSrc) {
    Copy-Item -Force $recipeExeSrc (Join-Path $releaseDir "am3d-recipe.exe")
}

# Copy examples
$examplesSrc = Join-Path $RepoRoot "assets"
$examplesDst = Join-Path $releaseDir "examples"
if (Test-Path $examplesSrc) {
    Copy-Item -Recurse -Force $examplesSrc $examplesDst
}

# Copy README
Copy-Item -Force (Join-Path $RepoRoot "README.md") (Join-Path $releaseDir "README.txt")

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
- Numba (BSD-2-Clause)

See the respective packages for full license terms.
"@ | Out-File -FilePath (Join-Path $licenseDir "NOTICE.txt") -Encoding utf8

Write-Host "Release staged at: $releaseDir" -ForegroundColor Green

# ---- 5. Smoke test ----
Write-Host ""
Write-Host "Step 6: Running packaged smoke test..." -ForegroundColor Yellow

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
    $minimalRecipe = Join-Path $RepoRoot "docs\recipes\examples\minimal.json"
    Invoke-Native { & $recipeExePath --recipe $minimalRecipe --validate-only }
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Packaged recipe CLI failed to validate the bundled example recipe!"
        exit 1
    }
    Write-Host "  Recipe CLI validated the bundled example recipe." -ForegroundColor Green
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
$manifestPath = Join-Path $releaseDir "smoke_manifest.json"
if (Test-Path $manifestPath) {
    Remove-Item -Force $manifestPath
}
$prevQtPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = "offscreen"
$smokeTimeoutMs = 60000
$smokeStdout = Join-Path $releaseDir "smoke_stdout.txt"
$smokeStderr = Join-Path $releaseDir "smoke_stderr.txt"
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

Write-Host ""
Write-Host "=== Build complete! ===" -ForegroundColor Cyan
Write-Host "Release folder: $releaseDir"
Write-Host "Executable: $exePath"
Write-Host ""
Write-Host "To smoke test manually, run the executable from the release folder."
Write-Host "Next steps: verify Home screen, New Empty, Create Primitive, Save, and relaunch."
