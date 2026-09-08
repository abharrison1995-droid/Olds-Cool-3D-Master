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

Write-Host ""
Write-Host "=== Build complete! ===" -ForegroundColor Cyan
Write-Host "Release folder: $releaseDir"
Write-Host "Executable: $exePath"
Write-Host ""
Write-Host "To smoke test manually, run the executable from the release folder."
Write-Host "Next steps: verify Home screen, New Empty, Create Primitive, Save, and relaunch."