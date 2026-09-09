<#
.SYNOPSIS
    Produce OBJ and GLB with the *frozen* Windows recipe CLI, then read them
    back with a verifier that shares no code with the exporters.
.DESCRIPTION
    The PowerShell twin of phase-e/export_check.sh. The verifier itself
    (phase-e/verify_exports.py) is unchanged and runs on both platforms: it
    imports nothing from am3d, so it needs a Python interpreter but not the
    project's environment. Any CPython 3 on the host will do -- it is
    deliberately NOT the build venv, because a verifier that ran inside the
    build environment would not be independent of it.

    .\export_check.ps1 -Bundle "release\3D MASTER 2005 Beta"
.PARAMETER Bundle
    The staged release folder to test.
#>
param(
    [string]$Bundle = "release\3D MASTER 2005 Beta"
)
$ErrorActionPreference = "Stop"

$BundleDir = (Resolve-Path $Bundle).Path
$Cli = Join-Path $BundleDir "am3d-recipe.exe"
if (-not (Test-Path $Cli)) { throw "no recipe CLI at $Cli" }

# phase-e, not phase-f: the verifier is shared, not duplicated. A second copy
# would be free to drift away from the Linux one, and then the two platforms
# would no longer be checked the same way.
$Verifier = Join-Path (Split-Path $PSScriptRoot -Parent) "phase-e\verify_exports.py"
if (-not (Test-Path $Verifier)) { throw "no verifier at $Verifier" }

$hostPy = $null
foreach ($cand in @(@{ Exe = "py"; Pre = @("-3") }, @{ Exe = "python"; Pre = @() })) {
    if (Get-Command $cand.Exe -ErrorAction SilentlyContinue) {
        $pre = $cand.Pre
        $probe = & $cand.Exe @pre -c "print(1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $hostPy = $cand; break }
    }
}
if (-not $hostPy) { throw "no host Python found to run the independent verifier" }

$Out = Join-Path ([System.IO.Path]::GetTempPath()) ("am3d_export_" + [System.Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $Out | Out-Null

# Identical to the Linux run's scene, so the two platforms' exports are
# compared against the same expectations: two distinct materials, and a
# second object placed by a transform that must be baked into the output.
$scene = @'
{
  "version": 1,
  "name": "export_check",
  "materials": [
    {"name": "mat_body", "color": [0.8, 0.2, 0.2], "objects": ["body"]},
    {"name": "mat_base", "color": [0.2, 0.4, 0.9], "objects": ["base"]}
  ],
  "objects": [
    {"name": "body", "primitive": "sphere",
     "params": {"radius": 1.0, "sections": 16, "rings": 8}},
    {"name": "base", "primitive": "box",
     "params": {"width": 2.0, "height": 0.4, "depth": 2.0},
     "transform": [[1,0,0,0],[0,1,0,-1.2],[0,0,1,0],[0,0,0,1]]}
  ],
  "exports": [
    {"format": "obj", "path": "scene"},
    {"format": "glb", "path": "scene"}
  ]
}
'@
$scenePath = Join-Path $Out "scene.json"
# ASCII, not the default UTF-16 of Out-File under PowerShell 5.1: a BOM or a
# UTF-16 payload makes the CLI's JSON parser fail on a file that looks fine
# in an editor.
$scene | Out-File -FilePath $scenePath -Encoding ascii

$reportPath = Join-Path $Out "report.json"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $Cli
$psi.Arguments = "--recipe `"$scenePath`" --out `"$Out`""
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$proc = [System.Diagnostics.Process]::Start($psi)
$outTask = $proc.StandardOutput.ReadToEndAsync()
$errTask = $proc.StandardError.ReadToEndAsync()
if (-not $proc.WaitForExit(120000)) { try { $proc.Kill() } catch { }; throw "the recipe CLI timed out" }
$outTask.Result | Out-File -FilePath $reportPath -Encoding utf8
if ($proc.ExitCode -ne 0) {
    Write-Host $outTask.Result
    Write-Host $errTask.Result
    throw "the frozen recipe CLI failed (rc=$($proc.ExitCode))"
}
Write-Host "recipe report: $($outTask.Result.Substring(0, [Math]::Min(200, $outTask.Result.Length)))"
Write-Host ""

$pre = $hostPy.Pre
& $hostPy.Exe @pre $Verifier (Join-Path $Out "scene.obj") (Join-Path $Out "scene.glb")
if ($LASTEXITCODE -ne 0) { throw "independent export verification failed" }
Write-Host ""
Write-Host "artifacts under $Out"
