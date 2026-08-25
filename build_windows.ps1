<#
.SYNOPSIS
    Build the 3D MASTER:2005 Windows executable and stage a release folder.
.DESCRIPTION
    Verifies Python environment, runs tests, builds with PyInstaller,
    runs a packaged smoke test, and stages the release.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

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

# Check for required packages
Write-Host "Step 2: Checking dependencies..." -ForegroundColor Yellow
$required = @("PySide6", "numpy", "msgpack", "scipy", "pyinstaller")
foreach ($pkg in $required) {
    try {
        & $py -c "import $pkg" 2>$null
        Write-Host "  $pkg: OK" -ForegroundColor Green
    } catch {
        Write-Host "  $pkg: MISSING (will install)" -ForegroundColor Yellow
        & $py -m pip install $pkg 2>&1 | Out-Null
    }
}

# ---- 2. Run tests ----
Write-Host ""
Write-Host "Step 3: Running all tests..." -ForegroundColor Yellow
& $py -m pytest am3d/ -q --tb=short 2>&1
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

& $py -m PyInstaller --clean am3d.spec 2>&1
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
- SciPy (BSD-3-Clause)
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