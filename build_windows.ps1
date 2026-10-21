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
    After all tests and packaged checks pass, write a proposed Windows lock
    under ignored build output. Copy it to requirements-lock-windows.txt and
    rerun without this switch so the final candidate uses that exact input.
#>
param(
    [switch]$SkipTests,
    [switch]$CaptureLock,
    [string]$HostPython = "C:\Users\Alex\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
)

$ErrorActionPreference = "Stop"
# This script lives at the repo root itself (not a subdirectory like
# scripts/), so the repo root IS $PSScriptRoot -- walking up a level here
# would build from the wrong directory (and clean up the wrong "dist"/
# "release" folders) whenever invoked from outside the repo.
$RepoRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
Set-Location $RepoRoot

$BuildDir = Join-Path $RepoRoot "build\windows"
$VenvDir  = Join-Path $BuildDir "venv"
$DistDir  = Join-Path $BuildDir "dist"
$WorkDir  = Join-Path $BuildDir "work"
$ReleaseRoot = Join-Path $RepoRoot "release"
. (Join-Path $RepoRoot "scripts\phase10_safety.ps1")

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

# PyInstaller resolves non-system DLL imports from PATH while building. Keep
# that search limited to the isolated build interpreter, its selected base
# Python runtime, and this Windows installation so unrelated tools on the
# developer's PATH cannot supply runtime DLLs to the frozen payload.
# PHASE10_PYINSTALLER_SEARCH_PATH_HELPERS_BEGIN
function Get-Phase10PyInstallerSearchPath {
    param(
        [Parameter(Mandatory)][string]$HostPythonPath,
        [Parameter(Mandatory)][string]$VenvScriptsPath
    )

    $hostPythonFull = [System.IO.Path]::GetFullPath($HostPythonPath)
    $venvScriptsFull = [System.IO.Path]::GetFullPath($VenvScriptsPath)
    if (-not (Test-Path -LiteralPath $hostPythonFull -PathType Leaf)) {
        throw "The selected host Python disappeared before PyInstaller dependency discovery."
    }
    if (-not (Test-Path -LiteralPath $venvScriptsFull -PathType Container)) {
        throw "The isolated build interpreter directory is unavailable for PyInstaller dependency discovery."
    }

    $windowsRoot = [System.Environment]::GetFolderPath(
        [System.Environment+SpecialFolder]::Windows)
    if ([string]::IsNullOrWhiteSpace($windowsRoot)) {
        throw "Could not resolve the Windows installation directory for PyInstaller dependency discovery."
    }
    $windowsRoot = [System.IO.Path]::GetFullPath($windowsRoot)
    $systemDirectory = [System.IO.Path]::GetFullPath(
        (Join-Path $windowsRoot "System32"))

    $trustedDirectories = @(
        $systemDirectory,
        $windowsRoot,
        $venvScriptsFull,
        [System.IO.Path]::GetDirectoryName($hostPythonFull)
    )
    $uniqueDirectories = New-Object 'System.Collections.Generic.List[string]'
    $seenDirectories = New-Object 'System.Collections.Generic.HashSet[string]' `
        ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($directory in $trustedDirectories) {
        if ([string]::IsNullOrWhiteSpace($directory) -or
            -not (Test-Path -LiteralPath $directory -PathType Container)) {
            throw "A trusted PyInstaller dependency-search directory is unavailable."
        }
        $fullDirectory = [System.IO.Path]::GetFullPath($directory)
        if ($seenDirectories.Add($fullDirectory)) {
            [void]$uniqueDirectories.Add($fullDirectory)
        }
    }
    return ($uniqueDirectories -join [System.IO.Path]::PathSeparator)
}

function Invoke-Phase10WithPyInstallerSearchPath {
    param(
        [Parameter(Mandatory)][string]$HostPythonPath,
        [Parameter(Mandatory)][string]$VenvScriptsPath,
        [Parameter(Mandatory)][ScriptBlock]$Action
    )

    $previousPath = $env:PATH
    try {
        $env:PATH = Get-Phase10PyInstallerSearchPath `
            -HostPythonPath $HostPythonPath -VenvScriptsPath $VenvScriptsPath
        & $Action
    } finally {
        $env:PATH = $previousPath
    }
}
# PHASE10_PYINSTALLER_SEARCH_PATH_HELPERS_END

# Keep normalization available both when a captured source lock exists and
# during the initial -CaptureLock bootstrap where that lock is intentionally
# absent. The locked comparison and proposal path use this same function.
# PHASE10_LOCK_NORMALIZER_BEGIN
function Normalize-Phase10LockEntries {
    param([Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Lines)

    @($Lines | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            if ($line -notmatch '^([A-Za-z0-9_.-]+)==([^;\s]+)$') {
                throw "Unsupported non-pinned Windows lock entry: $line"
            }
            $name = ($Matches[1] -replace '[-_.]+', '-').ToLowerInvariant()
            $lockedVersion = $Matches[2]
            # Pip is only the installer for this resolved set; keep build
            # dependencies such as setuptools and wheel in the exact lock.
            if ($name -ne "pip") {
                "$name==$lockedVersion"
            }
        }
    } | Sort-Object)
}
# PHASE10_LOCK_NORMALIZER_END

Write-Host "=== 3D MASTER:2005 Windows Build ===" -ForegroundColor Cyan
Write-Host ""
Assert-Phase10PathWithinRoot -Target $BuildDir -AllowedRoot $RepoRoot | Out-Null
Assert-Phase10PathWithinRoot -Target $ReleaseRoot -AllowedRoot $RepoRoot | Out-Null

if ($CaptureLock -and $SkipTests) {
    throw "-CaptureLock requires the full tests and frozen acceptance checks; it cannot be combined with -SkipTests."
}
$lockPath = Join-Path $RepoRoot "requirements-lock-windows.txt"
if (-not (Test-Path -LiteralPath $lockPath) -and -not $CaptureLock) {
    throw "The Windows lock is missing. Run a full bootstrap pass with -CaptureLock, then copy build\windows\proposed-requirements-lock-windows.txt to requirements-lock-windows.txt and rerun."
}
if ($CaptureLock -and (Test-Path -LiteralPath $lockPath)) {
    throw "-CaptureLock only creates a proposal when no committed Windows lock exists; refusing to replace the existing lock."
}

# ---- 1. Isolated build environment ----
# A dedicated venv under build\windows, never the developer's own environment
# and never the ambient interpreter. It uses the pinned direct build set for
# the initial Windows lock capture, then the captured platform lock on later
# runs. A stray locally installed package cannot slip in, and the build does
# not depend on pytest or PyInstaller being installed globally (PKG-06).
Write-Host "Step 1: Preparing an isolated build environment..." -ForegroundColor Yellow

$hostPythonFull = [System.IO.Path]::GetFullPath($HostPython)
if (-not (Test-Path -LiteralPath $hostPythonFull -PathType Leaf)) {
    Write-Error "The explicit -HostPython path is not a Python executable: $hostPythonFull"
    exit 1
}
$hostPythonVersionOutput = Invoke-Native {
    & $hostPythonFull -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
}
if ($LASTEXITCODE -ne 0 -or -not $hostPythonVersionOutput) {
    Write-Error "-HostPython did not start successfully: $hostPythonFull"
    exit 1
}
$hostPythonVersion = ("$hostPythonVersionOutput").Trim()
# ENV-01: numpy 2.4.6 declares Requires-Python >=3.11, so the pinned set
# cannot be installed on 3.10 -- fail here with the reason rather than at a
# resolver error thirty seconds later.
if ([version]$hostPythonVersion -lt [version]"3.11.0") {
    Write-Error "Python 3.11+ is required (found $hostPythonVersion); see docs/SUPPORTED_PLATFORMS.md, ENV-01."
    exit 1
}
Write-Host "  Python (host): $hostPythonVersion via explicit path"

Remove-Phase10Directory -Target $VenvDir -AllowedRoot $BuildDir
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
Invoke-Native { & $hostPythonFull -m venv $VenvDir }
$py = Join-Path $VenvDir "Scripts\python.exe"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $py)) {
    Write-Error "Could not create the build venv at $VenvDir."
    exit 1
}
Write-Host "  Build venv: $VenvDir" -ForegroundColor Green

# Install the full Windows lock once it is present in the source tree. On the
# first bootstrap run, fall back to the directly pinned dev set and let
# -CaptureLock propose the platform's resolved dependency set after checks. Steps 3 and 4
# need pytest, jsonschema and PyInstaller; none of the dev packages reach the
# release payload. This retains the runtime/dev separation while making later
# Windows builds use captured transitive versions too.
Write-Host "Step 2: Installing pinned build dependencies..." -ForegroundColor Yellow
Invoke-Native { & $py -m pip install --quiet --upgrade pip }
if ($LASTEXITCODE -ne 0) {
    Write-Error "Could not upgrade pip in the isolated build environment."
    exit 1
}
if (Test-Path $lockPath) {
    $reqPath = $lockPath
    Write-Host "  Installing captured Windows lock: $lockPath" -ForegroundColor Cyan
} else {
    $reqPath = Join-Path $RepoRoot "requirements-dev.txt"
    Write-Host "  Windows lock not present; bootstrapping from requirements-dev.txt" -ForegroundColor Yellow
}
Invoke-Native { & $py -m pip install --quiet -r $reqPath }
if ($LASTEXITCODE -ne 0) {
    Write-Error "Dependency installation failed!"
    exit 1
}
$frozen = Invoke-Native { & $py -m pip freeze }
if ($LASTEXITCODE -ne 0 -or @($frozen).Count -eq 0) {
    Write-Error "Could not capture a non-empty dependency freeze from the build venv."
    exit 1
}
Write-Host "  $(@($frozen).Count) resolved build packages installed from $([System.IO.Path]::GetFileName($reqPath))" -ForegroundColor Green
if (Test-Path -LiteralPath $lockPath) {
    $lockedEntries = @(Normalize-Phase10LockEntries -Lines @(Get-Content -LiteralPath $lockPath))
    $resolvedEntries = @(Normalize-Phase10LockEntries -Lines @($frozen))
    $lockDifference = Compare-Object -ReferenceObject @($lockedEntries) -DifferenceObject @($resolvedEntries)
    if ($lockDifference) {
        Write-Error "The installed Windows environment does not exactly match requirements-lock-windows.txt."
        $lockDifference | Format-Table | Out-String | Write-Host
        exit 1
    }
}

$sourceDigestBefore = (Invoke-Native {
    & $py (Join-Path $RepoRoot "scripts\build_input_digest.py") `
        --root $RepoRoot --digest-only
}) -join ""
if ($LASTEXITCODE -ne 0 -or $sourceDigestBefore -notmatch '^[0-9a-f]{64}$') {
    Write-Error "Could not capture the complete starting build-input digest."
    exit 1
}
Write-Host "  Build input SHA-256: $sourceDigestBefore" -ForegroundColor Cyan
Invoke-Native {
    & $py (Join-Path $RepoRoot "scripts\write_build_identity.py") `
        --root $RepoRoot --platform windows --digest $sourceDigestBefore
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "Could not write the compact Windows bundle identity."
    exit 1
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
        Invoke-Native { & $py -m pytest am3d/ -q --maxfail=1 --tb=short }
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
$previousIdentityPath = $env:AM3D_BUILD_IDENTITY_PATH
$env:AM3D_BUILD_IDENTITY_PATH = Join-Path $BuildDir "build_identity.json"
foreach ($stale in @($DistDir, $WorkDir)) {
    Remove-Phase10Directory -Target $stale -AllowedRoot $BuildDir
}

$venvScriptsPath = Join-Path $VenvDir "Scripts"
Invoke-Phase10WithPyInstallerSearchPath -HostPythonPath $hostPythonFull `
    -VenvScriptsPath $venvScriptsPath -Action {
        Invoke-Native {
            & $py -m PyInstaller --clean --noconfirm `
                --distpath $DistDir --workpath $WorkDir (Join-Path $RepoRoot "am3d.spec")
        }
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
Invoke-Phase10WithPyInstallerSearchPath -HostPythonPath $hostPythonFull `
    -VenvScriptsPath $venvScriptsPath -Action {
        Invoke-Native {
            & $py -m PyInstaller --clean --noconfirm `
                --distpath $DistDir --workpath $WorkDir (Join-Path $RepoRoot "am3d_recipe.spec")
        }
    }
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller recipe CLI build failed!"
    exit 1
}
$env:AM3D_BUILD_IDENTITY_PATH = $previousIdentityPath
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
$releaseDir = Join-Path $ReleaseRoot "3D MASTER 2005 Beta"
Remove-Phase10Directory -Target $releaseDir -AllowedRoot $RepoRoot
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

# Copy the installed runtime wheels' upstream license texts and record their
# package metadata. The helper fails if any explicitly bundled package is absent.
$licenseDir = Join-Path $releaseDir "LICENSES"
New-Item -ItemType Directory -Path $licenseDir -Force | Out-Null
Invoke-Native {
    & $py (Join-Path $RepoRoot "scripts\write_runtime_licenses.py") `
        --root $RepoRoot --output $releaseDir --platform windows
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "Could not write truthful runtime dependency license notices."
    exit 1
}

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
    $produced = @(
        Get-ChildItem -Recurse -File $recipeOut |
            Where-Object { $_.Name -ne "report.json" }
    )
    if ($produced.Count -eq 0) {
        Write-Error "The packaged recipe reported success but wrote nothing!"
        exit 1
    }

    $invalidRecipePath = Join-Path $recipeOut "invalid_recipe.json"
    [System.IO.File]::WriteAllText($invalidRecipePath, "{`"version`":1,", [System.Text.Encoding]::UTF8)
    $invalidRecipeOutput = Invoke-Native {
        & $recipeExePath --recipe $invalidRecipePath --validate-only
    }
    $invalidRecipeExitCode = $LASTEXITCODE
    if ($invalidRecipeExitCode -ne 1) {
        Write-Error "Packaged recipe CLI did not reject malformed JSON with exit 1."
        exit 1
    }
    $invalidRecipeReport = ($invalidRecipeOutput -join "`n") | ConvertFrom-Json
    if ($invalidRecipeReport.ok -ne $false -or
        @($invalidRecipeReport.error_records).Count -eq 0 -or
        $invalidRecipeReport.error_records[0].code -ne "recipe_read_error" -or
        $invalidRecipeReport.error_records[0].stage -ne "parse") {
        Write-Error "Packaged recipe CLI did not return a structured parse error."
        exit 1
    }
    Remove-Phase10FreshTempDirectory -Target $recipeOut -RequiredPrefix "am3d_recipe_run_"
    Write-Host "  Recipe CLI validated, built the bundled example recipe, and returned a structured malformed-input error ($($produced.Count) file(s))." -ForegroundColor Green
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
Write-Host "  Smoke test passed: $(@($smokeManifest.steps).Count) steps, all ok." -ForegroundColor Green

Write-Host ""
Write-Host "Step 7a: Running the fixed offline AI acceptance flow..." -ForegroundColor Yellow
$aiTestHost = Join-Path $smokeDir "ai-self-test-host"
New-Item -ItemType Directory -Path $aiTestHost | Out-Null
$aiTestReportPath = Join-Path $aiTestHost "phase10-ai-self-test\acceptance.json"
$aiTestStdout = Join-Path $smokeDir "ai_self_test_stdout.txt"
$aiTestStderr = Join-Path $smokeDir "ai_self_test_stderr.txt"
$aiPsi = New-Object System.Diagnostics.ProcessStartInfo
$aiPsi.FileName = $exePath
$aiPsi.Arguments = "--ai-self-test --out `"$aiTestHost`""
$aiPsi.UseShellExecute = $false
$aiPsi.CreateNoWindow = $true
$aiPsi.RedirectStandardOutput = $true
$aiPsi.RedirectStandardError = $true
$aiProc = [System.Diagnostics.Process]::Start($aiPsi)
$aiStdoutTask = $aiProc.StandardOutput.ReadToEndAsync()
$aiStderrTask = $aiProc.StandardError.ReadToEndAsync()
$aiFinished = $aiProc.WaitForExit(120000)
if (-not $aiFinished) {
    Stop-Process -Id $aiProc.Id -Force -ErrorAction SilentlyContinue
    Write-Error "Fixed AI acceptance timed out after 120s."
    exit 1
}
$aiStdoutTask.Result | Out-File -FilePath $aiTestStdout -Encoding utf8
$aiStderrTask.Result | Out-File -FilePath $aiTestStderr -Encoding utf8
if ($aiProc.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $aiTestReportPath)) {
    Get-Content $aiTestStdout, $aiTestStderr | Write-Host
    Write-Error "Fixed offline AI acceptance failed (exit $($aiProc.ExitCode))."
    exit 1
}
$aiTestReport = Get-Content -LiteralPath $aiTestReportPath -Raw | ConvertFrom-Json
if ($aiTestReport.ok -ne $true -or $aiTestReport.mode -ne "frozen" `
        -or $aiTestReport.qualification -ne "offline-fixed-mock-transport" `
        -or $aiTestReport.live_network_used -ne $false `
        -or $aiTestReport.provider_requests -ne 4 `
        -or $aiTestReport.credential_sentinel_written -ne $false `
        -or $aiTestReport.worker_and_checks -ne "passed" `
        -or $aiTestReport.refinement -ne "passed") {
    Get-Content $aiTestReportPath | Write-Host
    Write-Error "Fixed AI acceptance produced incomplete or unqualified evidence."
    exit 1
}
Write-Host "  Fixed mock-transport AI acceptance passed; no live provider/network qualification is claimed." -ForegroundColor Green

# The payload must contain only what a user receives. A build-machine path
# inside it means a build artefact leaked into the release folder (this
# caught the smoke manifest, which used to be written straight into it).
Write-Host ""
Write-Host "Step 7c: Checking the payload for build-machine references..." -ForegroundColor Yellow
Invoke-Native {
    & $py (Join-Path $RepoRoot "scripts\audit_build_payload.py") `
        --payload $releaseDir --forbidden-root $RepoRoot
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "The complete release payload audit found a build path or could not inspect every payload file."
    exit 1
}
Write-Host "  Complete payload scan passed (no size-based file omission)." -ForegroundColor Green

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
    Remove-Phase10File -Target $zipPath -AllowedRoot $RepoRoot
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

# ---- 7b. Build provenance inputs ----
# Keep the final provenance write until after relocation and ACL checks.
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
    "python (host)    : $hostPythonVersion"
    "python (build)   : $pyBuildVersion"
    "pyinstaller      : $pyInstallerVersion"
    "tests            : $testState"
    ""
    "pinned build set (pip freeze):"
) + ($frozen | ForEach-Object { "  $_" })
$provenancePath = Join-Path $releaseParent "BUILD_PROVENANCE-windows.txt"

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
$script:preserveVerifyRoot = $false
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

    # The relocated CLI is exercised with an external recipe for validation,
    # actual artifact-producing execution, and a malformed file. This checks
    # the structured machine error contract after extraction as well.
    $relocatedRecipeOut = Join-Path $verifyRoot "relocated_recipe_output"
    New-Item -ItemType Directory -Path $relocatedRecipeOut | Out-Null
    $relocatedBuildOutput = Invoke-Native {
        & $verifiedRecipeExe --recipe $verifyRecipeJson --out $relocatedRecipeOut
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Relocated recipe CLI failed to build the external example."
        exit 1
    }
    $relocatedBuildReport = ($relocatedBuildOutput -join "`n") | ConvertFrom-Json
    $relocatedArtifacts = @(
        Get-ChildItem -LiteralPath $relocatedRecipeOut -Recurse -File |
            Where-Object { $_.Name -ne "report.json" }
    )
    if ($relocatedBuildReport.ok -ne $true -or $relocatedArtifacts.Count -eq 0) {
        Write-Error "Relocated recipe CLI reported success without producing artifacts."
        exit 1
    }

    $malformedRecipe = Join-Path $verifyRoot "malformed_recipe.json"
    [System.IO.File]::WriteAllText($malformedRecipe, "{`"version`":1,", [System.Text.Encoding]::UTF8)
    $malformedOutput = Invoke-Native {
        & $verifiedRecipeExe --recipe $malformedRecipe --validate-only
    }
    $malformedExitCode = $LASTEXITCODE
    if ($malformedExitCode -ne 1) {
        Write-Error "Relocated recipe CLI did not reject malformed JSON with exit 1."
        exit 1
    }
    $malformedReport = ($malformedOutput -join "`n") | ConvertFrom-Json
    if ($malformedReport.ok -ne $false -or
        @($malformedReport.error_records).Count -eq 0 -or
        $malformedReport.error_records[0].code -ne "recipe_read_error" -or
        $malformedReport.error_records[0].stage -ne "parse") {
        Write-Error "Relocated recipe CLI did not return a structured parse error."
        exit 1
    }
    Write-Host "  Relocated CLI validated, built $($relocatedArtifacts.Count) artifact(s), and returned a structured malformed-input error." -ForegroundColor Green

    # Apply a real Windows access-control deny, attempt writes to an existing
    # payload file and a new payload path, then restore the exact saved ACLs.
    # If ACL control is unavailable, provenance records UNPASSED explicitly.
    $script:readOnlyStatus = "UNPASSED: Windows ACL tools unavailable"
    $script:readOnlyWorkflowStatus = "UNPASSED: payload write denial could not be proven"
    $icacls = Get-Command icacls.exe -ErrorAction SilentlyContinue
    if ($icacls) {
        $aclBackupPath = Join-Path $verifyRoot "phase10-acls.txt"
        $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $aclRestoreParent = [System.IO.Path]::GetDirectoryName($verifiedReleaseDir.FullName)
        $aclMutationAttempted = $false
        $aclRestoreError = $null
        $writeWasAllowed = $false
        try {
            Invoke-Native { & $icacls.Source $verifiedReleaseDir /save $aclBackupPath /t /c }
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $aclBackupPath)) {
                throw "Could not save relocated payload ACLs."
            }
            # Prove that the saved ACL can be restored through the parent
            # directory before adding a deny entry. Numeric SIDs require '*'
            # in icacls trustee syntax; restoration uses the parent because
            # /save records paths relative to the payload child directory.
            Invoke-Native { & $icacls.Source $aclRestoreParent /restore $aclBackupPath /c }
            if ($LASTEXITCODE -ne 0) {
                $script:readOnlyStatus = "UNPASSED: Windows ACL restore capability unavailable"
                $script:readOnlyWorkflowStatus = "UNPASSED: restore capability not proven; payload ACL was not changed"
            } else {
                # Set this before invoking icacls: a failing command can still
                # have applied some of the recursive deny entries.
                $aclMutationAttempted = $true
                $denyOutput = @(Invoke-Native {
                    & $icacls.Source $verifiedReleaseDir /deny "*$($currentSid):(OI)(CI)(W)" /t /c 2>&1
                })
                $denyOutputText = ($denyOutput | ForEach-Object { "$_" }) -join "`n"
                $denySummary = [regex]::Match(
                    $denyOutputText,
                    "(?im)Successfully processed\s+(\d+)\s+files?;\s*Failed processing\s+(\d+)\s+files?")
                $denyFailedCount = if ($denySummary.Success) { [int]$denySummary.Groups[2].Value } else { -1 }
                $denySucceededCount = if ($denySummary.Success) { [int]$denySummary.Groups[1].Value } else { 0 }
                $denyReportedAccessError = $denyOutputText -match "(?i)Access is denied"
                if ($LASTEXITCODE -ne 0 -or -not $denySummary.Success -or
                    $denyFailedCount -ne 0 -or $denySucceededCount -eq 0 -or
                    $denyReportedAccessError) {
                    $script:readOnlyStatus = "UNPASSED: Windows ACL denial could not be applied completely"
                    $script:readOnlyWorkflowStatus = "UNPASSED: payload write denial could not be proven"
                    foreach ($line in ($denyOutputText -split "`r?`n" | Where-Object {
                                $_ -match "(?i)Access is denied|Successfully processed|Failed processing"
                            })) {
                        Write-Host "  icacls denial result: $line" -ForegroundColor Yellow
                    }
                } else {
                    $blockedWrites = 0
                    try {
                        Add-Content -LiteralPath (Join-Path $verifiedReleaseDir "README.txt") -Value "phase10-write-probe"
                        $writeWasAllowed = $true
                    } catch { $blockedWrites++ }
                    try {
                        [System.IO.File]::WriteAllText((Join-Path $verifiedReleaseDir "phase10-write-probe.txt"), "probe")
                        $writeWasAllowed = $true
                    } catch { $blockedWrites++ }
                    if (-not $writeWasAllowed -and $blockedWrites -eq 2) {
                        $script:readOnlyStatus = "passed"
                    }
                    if ($script:readOnlyStatus -eq "passed") {
                        # Keep evidence writable outside the denied payload, then
                        # exercise the fixed frozen AI path while its files reject
                        # writes.
                        $readOnlyAiHost = Join-Path $verifyRoot "readonly_ai_self_test_host"
                        if (Test-Path -LiteralPath $readOnlyAiHost) {
                            throw "Read-only AI acceptance output path already exists."
                        }
                        Assert-Phase10PathWithinRoot -Target $readOnlyAiHost `
                            -AllowedRoot $verifyRoot | Out-Null
                        $readOnlyAiHostFull = [System.IO.Path]::GetFullPath($readOnlyAiHost)
                        $readOnlyPayloadFull = [System.IO.Path]::GetFullPath($verifiedReleaseDir.FullName).TrimEnd('\') + '\'
                        if ($readOnlyAiHostFull.StartsWith(
                                $readOnlyPayloadFull,
                                [System.StringComparison]::OrdinalIgnoreCase)) {
                            throw "Read-only AI acceptance output must stay outside the payload."
                        }
                        New-Item -ItemType Directory -Path $readOnlyAiHost | Out-Null
                        $readOnlyAiReportPath = Join-Path $readOnlyAiHost `
                            "phase10-ai-self-test\acceptance.json"
                        $readOnlyAiStdout = Join-Path $readOnlyAiHost "readonly_ai_self_test_stdout.txt"
                        $readOnlyAiStderr = Join-Path $readOnlyAiHost "readonly_ai_self_test_stderr.txt"
                        $prevQtPlatformReadOnly = $env:QT_QPA_PLATFORM
                        $env:QT_QPA_PLATFORM = "offscreen"
                        try {
                            $readOnlyAiPsi = New-Object System.Diagnostics.ProcessStartInfo
                            $readOnlyAiPsi.FileName = $verifiedExe
                            $readOnlyAiPsi.Arguments = "--ai-self-test --out `"$readOnlyAiHost`""
                            $readOnlyAiPsi.UseShellExecute = $false
                            $readOnlyAiPsi.CreateNoWindow = $true
                            $readOnlyAiPsi.RedirectStandardOutput = $true
                            $readOnlyAiPsi.RedirectStandardError = $true
                            $readOnlyAiProc = [System.Diagnostics.Process]::Start($readOnlyAiPsi)
                            $readOnlyAiStdoutTask = $readOnlyAiProc.StandardOutput.ReadToEndAsync()
                            $readOnlyAiStderrTask = $readOnlyAiProc.StandardError.ReadToEndAsync()
                            $readOnlyAiFinished = $readOnlyAiProc.WaitForExit(120000)
                            if (-not $readOnlyAiFinished) {
                                Stop-Process -Id $readOnlyAiProc.Id -Force -ErrorAction SilentlyContinue
                                $readOnlyAiWorkflowPassed = $false
                            } else {
                                $readOnlyAiStdoutTask.Result | Out-File -FilePath $readOnlyAiStdout -Encoding utf8
                                $readOnlyAiStderrTask.Result | Out-File -FilePath $readOnlyAiStderr -Encoding utf8
                                $readOnlyAiWorkflowPassed = $false
                                if ($readOnlyAiProc.ExitCode -eq 0 -and
                                    (Test-Path -LiteralPath $readOnlyAiReportPath)) {
                                    $readOnlyAiReport = Get-Content -LiteralPath $readOnlyAiReportPath -Raw |
                                        ConvertFrom-Json
                                    $readOnlyAiWorkflowPassed = (
                                        $readOnlyAiReport.ok -eq $true -and
                                        $readOnlyAiReport.mode -eq "frozen" -and
                                        $readOnlyAiReport.qualification -eq "offline-fixed-mock-transport" -and
                                        $readOnlyAiReport.live_network_used -eq $false -and
                                        $readOnlyAiReport.provider_requests -eq 4 -and
                                        $readOnlyAiReport.credential_sentinel_written -eq $false -and
                                        $readOnlyAiReport.worker_and_checks -eq "passed" -and
                                        $readOnlyAiReport.refinement -eq "passed")
                                }
                            }
                            if ($readOnlyAiWorkflowPassed) {
                                $script:readOnlyWorkflowStatus = "passed"
                            } else {
                                $script:readOnlyWorkflowStatus = "UNPASSED: fixed offline AI workflow failed under write-denied payload"
                            }
                        } catch {
                            $script:readOnlyWorkflowStatus = "UNPASSED: fixed offline AI workflow could not be verified"
                        } finally {
                            $env:QT_QPA_PLATFORM = $prevQtPlatformReadOnly
                        }
                    } elseif ($writeWasAllowed) {
                        $script:readOnlyStatus = "UNPASSED: payload write was allowed despite ACL denial"
                    } else {
                        $script:readOnlyStatus = "UNPASSED: payload write denial could not be proven"
                    }
                }
            }
        } catch {
            if ($script:readOnlyStatus -eq "passed") {
                $script:readOnlyWorkflowStatus = "UNPASSED: fixed offline AI workflow could not be verified"
            } else {
                $script:readOnlyStatus = "UNPASSED: Windows ACL probe unavailable"
            }
        } finally {
            if ($aclMutationAttempted) {
                Invoke-Native { & $icacls.Source $aclRestoreParent /restore $aclBackupPath /c }
                if ($LASTEXITCODE -ne 0) {
                    $aclRestoreError = "Could not restore the relocated payload ACLs."
                }
            }
        }
        if ($aclRestoreError) {
            $script:preserveVerifyRoot = $true
            Write-Host "  Relocated payload read-only check: $($script:readOnlyStatus)" -ForegroundColor $(if ($script:readOnlyStatus -eq "passed") { "Green" } else { "Yellow" })
            Write-Host "  Read-only frozen AI workflow: $($script:readOnlyWorkflowStatus)" -ForegroundColor $(if ($script:readOnlyWorkflowStatus -eq "passed") { "Green" } else { "Yellow" })
            throw $aclRestoreError
        }
        if ($writeWasAllowed) {
            Write-Host "  Relocated payload read-only check: $($script:readOnlyStatus)" -ForegroundColor $(if ($script:readOnlyStatus -eq "passed") { "Green" } else { "Yellow" })
            Write-Host "  Read-only frozen AI workflow: $($script:readOnlyWorkflowStatus)" -ForegroundColor $(if ($script:readOnlyWorkflowStatus -eq "passed") { "Green" } else { "Yellow" })
            throw "Relocated payload accepted a write while its ACL denied writes."
        }
    }
    Write-Host "  Relocated payload read-only check: $($script:readOnlyStatus)" -ForegroundColor $(if ($script:readOnlyStatus -eq "passed") { "Green" } else { "Yellow" })
    Write-Host "  Read-only frozen AI workflow: $($script:readOnlyWorkflowStatus)" -ForegroundColor $(if ($script:readOnlyWorkflowStatus -eq "passed") { "Green" } else { "Yellow" })
    if ($script:readOnlyStatus -eq "passed" -and
        $script:readOnlyWorkflowStatus -ne "passed") {
        throw "Fixed offline AI workflow failed while the relocated payload was write-denied."
    }
} finally {
    if ($script:preserveVerifyRoot) {
        Write-Host "Preserving relocated payload for ACL recovery at: $verifyRoot" -ForegroundColor Red
    } else {
        Remove-Phase10FreshTempDirectory -Target $verifyRoot -RequiredPrefix "am3d verify "
    }
}

# Provenance is written only after relocation and the ACL probe have finished.
# The detailed input manifest remains beside (not inside) the user payload.
$sourceDigestAfter = ((Invoke-Native {
    & $py (Join-Path $RepoRoot "scripts\build_input_digest.py") `
        --root $RepoRoot --digest-only
}) -join "").Trim()
if ($LASTEXITCODE -ne 0 -or $sourceDigestAfter -ne $sourceDigestBefore) {
    Write-Error "Build inputs changed during the candidate build."
    exit 1
}
$inputManifestPath = Join-Path $releaseParent "BUILD_INPUTS-windows.json"
Invoke-Native {
    & $py (Join-Path $RepoRoot "scripts\build_input_digest.py") `
        --root $RepoRoot --write-manifest $inputManifestPath --digest-only
}
if ($LASTEXITCODE -ne 0) { Write-Error "Could not write the complete build input manifest."; exit 1 }
Write-Host "  Final build input SHA-256: $sourceDigestAfter" -ForegroundColor Cyan

if ($CaptureLock) {
    # Propose the resolved set only after every source/frozen/relocation gate
    # has passed. Keep it in ignored build output; the caller must promote it
    # to the source lock and perform another locked build.
    $proposedLockPath = Join-Path $BuildDir "proposed-requirements-lock-windows.txt"
    $captureLines = @(Normalize-Phase10LockEntries -Lines @($frozen))
    if ($captureLines.Count -eq 0) {
        Write-Error "Could not form the complete resolved Windows lock proposal."
        exit 1
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($proposedLockPath, [string[]]$captureLines, $utf8NoBom)
    $proposalHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $proposedLockPath).Hash.ToLowerInvariant()
    $provenance += "proposed lock sha256: $proposalHash"
    Write-Host "  Proposed Windows lock: $proposedLockPath" -ForegroundColor Green
    Write-Host "  Proposed lock SHA-256: $proposalHash" -ForegroundColor Green
    Write-Host "  Copy this proposal to requirements-lock-windows.txt, then rerun without -CaptureLock." -ForegroundColor Yellow
}

$provenance += @(
    "host python      : $hostPythonVersion"
    "build inputs sha256: $sourceDigestAfter"
    "input manifest   : release/BUILD_INPUTS-windows.json"
    "frozen AI acceptance: offline fixed MockTransport passed; no live network qualification"
    "relocated CLI    : validation/build/malformed structured error passed"
    "relocated read-only write-denial: $($script:readOnlyStatus)"
    "read-only frozen AI workflow: $($script:readOnlyWorkflowStatus)"
    "Windows 11 qualification: not claimed (builder OS: $($os.Caption) $($os.Version))"
    "candidate status : development candidate evidence; no release, store, or publication qualification"
    $(if ($CaptureLock) { "lock capture     : bootstrap proposal only; a second build with the captured source lock is required" } else { "lock capture     : captured source lock installed and exact set verified" })
    $(if ($CaptureLock) { "bootstrap digest : excludes the not-yet-present source Windows lock; not a final candidate identity" } else { "captured lock sha256: $((Get-FileHash -Algorithm SHA256 -LiteralPath $lockPath).Hash.ToLowerInvariant())" })
)
$provenance -join "`r`n" | Out-File -FilePath $provenancePath -Encoding utf8
Write-Host "  $provenancePath" -ForegroundColor Green

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
