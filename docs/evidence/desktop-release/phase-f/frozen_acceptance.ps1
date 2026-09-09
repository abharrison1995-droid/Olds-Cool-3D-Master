<#
.SYNOPSIS
    Windows acceptance run against a *frozen* bundle.
.DESCRIPTION
    The PowerShell twin of phase-e/frozen_acceptance.sh, section for
    section, so the two platforms produce comparable evidence rather than
    one being trusted.

    Every launch goes through a scrubbed environment (the equivalent of the
    Linux run's `env -i`): only the variables a real Windows logon session
    provides, with nothing Python-related and no virtualenv on PATH, so a
    bundle that secretly needs the build machine's interpreter fails here.

    Sections 1-8 mirror the Linux script. Sections 9-11 have no Linux
    counterpart and exist because they are the Windows-specific ways this
    application can break.

    .\frozen_acceptance.ps1 -Bundle "release\3D MASTER 2005 Beta"

    Prints one line per check and exits non-zero if any failed.
.PARAMETER Bundle
    The staged release folder to test.
.PARAMETER SkipInteractive
    Skip section 2 (the three timed GUI launches), for a headless runner
    with no desktop session. The skipped checks are reported as SKIP, never
    as PASS.
#>
param(
    [string]$Bundle = "release\3D MASTER 2005 Beta",
    [switch]$SkipInteractive
)

# Not "Stop": this script is a test harness. A failing check must be
# recorded and the run must continue, exactly as the bash version does.
$ErrorActionPreference = "Continue"

$BundleDir = (Resolve-Path $Bundle).Path
$App  = Join-Path $BundleDir "3D MASTER 2005.exe"
$Cli  = Join-Path $BundleDir "am3d-recipe.exe"
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ("am3d_accept_" + [System.Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $Work | Out-Null

$script:Pass = 0
$script:Fail = 0
$script:Skip = 0
function Write-Pass($m) { Write-Host "  [PASS] $m"; $script:Pass++ }
function Write-Fail($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red; $script:Fail++ }
function Write-Skip($m) { Write-Host "  [SKIP] $m" -ForegroundColor Yellow; $script:Skip++ }
function Write-Note($m) { Write-Host "  [note] $m" }
function Check($ok, $label, $detail) {
    if ($ok) { Write-Pass $label } else { Write-Fail ("$label" + $(if ($detail) { " -- $detail" } else { "" })) }
}

# The variables a real Windows logon session genuinely provides. Everything
# else is dropped -- in particular PYTHON*, PYTHONPATH, PYTHONHOME,
# VIRTUAL_ENV, CONDA_*, QT_* and any developer PATH entries. SystemRoot and
# a system32 PATH are mandatory: without them Windows cannot even load the
# CRT, which would fail the bundle for the wrong reason.
function New-SessionProcess {
    param(
        [string]$FilePath,
        [string]$Arguments = "",
        [hashtable]$Extra = @{},
        [string]$WorkingDirectory = $null
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = $Arguments
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }
    $psi.EnvironmentVariables.Clear()
    $sysRoot = $env:SystemRoot
    $keep = @{
        "SystemRoot"             = $sysRoot
        "windir"                 = $sysRoot
        "SystemDrive"            = $env:SystemDrive
        "ComSpec"                = (Join-Path $sysRoot "system32\cmd.exe")
        "PATH"                   = ((Join-Path $sysRoot "system32") + ";" + $sysRoot + ";" + (Join-Path $sysRoot "system32\Wbem"))
        "PATHEXT"                = ".COM;.EXE;.BAT;.CMD"
        "USERPROFILE"            = $env:USERPROFILE
        "LOCALAPPDATA"           = $env:LOCALAPPDATA
        "APPDATA"                = $env:APPDATA
        "TEMP"                   = $env:TEMP
        "TMP"                    = $env:TMP
        "NUMBER_OF_PROCESSORS"   = $env:NUMBER_OF_PROCESSORS
        "PROCESSOR_ARCHITECTURE" = $env:PROCESSOR_ARCHITECTURE
    }
    foreach ($k in $keep.Keys) {
        if ($keep[$k]) { $psi.EnvironmentVariables[$k] = $keep[$k] }
    }
    foreach ($k in $Extra.Keys) { $psi.EnvironmentVariables[$k] = $Extra[$k] }
    return $psi
}

# Runs to completion under the scrubbed environment and returns
# @{ ExitCode; StdOut; StdErr; TimedOut }. TimeoutMs guards against a hang
# blocking the run forever; a timeout is a FAIL, never a silent pass.
function Invoke-Session {
    param(
        [string]$FilePath,
        [string]$Arguments = "",
        [hashtable]$Extra = @{},
        [int]$TimeoutMs = 120000,
        [string]$WorkingDirectory = $null
    )
    $psi = New-SessionProcess -FilePath $FilePath -Arguments $Arguments -Extra $Extra -WorkingDirectory $WorkingDirectory
    $proc = [System.Diagnostics.Process]::Start($psi)
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()
    $finished = $proc.WaitForExit($TimeoutMs)
    if (-not $finished) {
        try { $proc.Kill() } catch { }
        return @{ ExitCode = -1; StdOut = ""; StdErr = ""; TimedOut = $true }
    }
    return @{
        ExitCode = $proc.ExitCode
        StdOut   = $outTask.Result
        StdErr   = $errTask.Result
        TimedOut = $false
    }
}

# Quote every path argument: the bundle folder is "3D MASTER 2005 Beta" and
# the scratch paths below deliberately contain spaces and non-ASCII
# characters, and ProcessStartInfo.Arguments is a single command line that
# the child re-splits on unquoted whitespace.
function Q($s) { return '"' + $s + '"' }

Write-Host "=== Frozen bundle acceptance (Windows): $BundleDir"
Write-Host "=== $(Get-Date -Format o)  host: $((Get-CimInstance Win32_OperatingSystem).Caption) $([System.Environment]::OSVersion.Version)"
Write-Host ""

foreach ($required in @($App, $Cli)) {
    if (-not (Test-Path $required)) {
        Write-Host "FATAL: $required does not exist -- nothing to accept." -ForegroundColor Red
        exit 2
    }
}

# ---- 1. The bundle carries its own runtime --------------------------------
Write-Host "1. The bundle carries its own runtime"
$smokeJson = Join-Path $Work "smoke.json"
$r = Invoke-Session -FilePath $App -Arguments ("--smoke-test --out " + (Q $smokeJson)) -Extra @{ QT_QPA_PLATFORM = "offscreen" }
if ($r.TimedOut) {
    Write-Fail "packaged smoke test (all workflows) timed out"
} else {
    Check ($r.ExitCode -eq 0) "packaged smoke test (all workflows) exits 0" "rc=$($r.ExitCode)"
}
$manifest = $null
if (Test-Path $smokeJson) {
    $manifest = Get-Content $smokeJson -Raw | ConvertFrom-Json
    $bad = @($manifest.steps | Where-Object { $_.status -ne "ok" } | ForEach-Object { $_.name })
    Write-Note "smoke steps: $($manifest.steps.Count), not ok: $(if ($bad.Count) { $bad -join ', ' } else { 'none' })"
    Write-Note "gpu/software parity: $($manifest.artifacts.gpu_parity)"
} else {
    Write-Fail "smoke manifest was not written"
    if ($r.StdErr) { Write-Note ($r.StdErr -split "`n" | Select-Object -Last 3) }
}
Write-Host ""

# ---- 2. Graphics routes ----------------------------------------------------
# Windows has one platform plugin (qwindows) rather than the Linux
# Wayland/xcb pair, so the routes that differ here are the GPU backend and
# the software fallback.
Write-Host "2. Graphics routes (each launched for 10 s, then closed)"
function Test-Route {
    param([string]$Label, [hashtable]$Extra = @{})
    $psi = New-SessionProcess -FilePath $App -Extra $Extra
    $psi.RedirectStandardOutput = $false
    $psi.RedirectStandardError = $false
    $proc = [System.Diagnostics.Process]::Start($psi)
    Start-Sleep -Seconds 10
    if ($proc.HasExited) {
        Write-Fail "$($Label): exited early (rc=$($proc.ExitCode))"
    } else {
        # CloseMainWindow first: the app is expected to shut down cleanly on
        # a real close request, which Kill would not prove.
        $closed = $proc.CloseMainWindow()
        if (-not $proc.WaitForExit(15000)) { try { $proc.Kill() } catch { } ; $closed = $false }
        if ($closed) {
            Write-Pass "$($Label): still running after 10 s, exited on close"
        } else {
            Write-Fail "$($Label): did not exit on a close request within 15 s"
        }
    }
}
if ($SkipInteractive) {
    Write-Skip "native GPU session -- no desktop session on this runner (-SkipInteractive)"
    Write-Skip "software-OpenGL session -- no desktop session on this runner (-SkipInteractive)"
} else {
    Test-Route -Label "native-session"
    # LIBGL_ALWAYS_SOFTWARE is Mesa's switch and does nothing on Windows.
    # QT_OPENGL=software is the real equivalent: it makes Qt use the bundled
    # software rasteriser instead of the installed GL driver, which is what a
    # machine with a broken or absent OpenGL driver effectively has.
    #
    # This is NOT the same thing as the application's own forced-software
    # renderer -- there is no environment variable for that; it is the render
    # dialog's checkbox and viewport3d.force_software, and it is exercised by
    # the packaged smoke run in section 1 (which renders with
    # force_software=True) rather than here.
    Test-Route -Label "qt-software-opengl" -Extra @{ QT_OPENGL = "software" }
}
Write-Host ""

# ---- 3. Recipe CLI (journey 6) --------------------------------------------
Write-Host "3. Recipe CLI (journey 6)"
$recipeSrc = Join-Path $BundleDir "examples\recipes\minimal.json"
$recipeOut = Join-Path $Work "recipe_out"
New-Item -ItemType Directory -Force -Path $recipeOut | Out-Null
$r = Invoke-Session -FilePath $Cli -Arguments ("--recipe " + (Q $recipeSrc) + " --out " + (Q $recipeOut))
Check ($r.ExitCode -eq 0) "bundled recipe builds with the packaged CLI" "rc=$($r.ExitCode)"
$produced = @(Get-ChildItem -Recurse -File $recipeOut -ErrorAction SilentlyContinue)
Check ($produced.Count -gt 0) "the recipe wrote output files" "$($produced.Count) file(s)"

$missing = Join-Path $Work "does-not-exist.json"
$r = Invoke-Session -FilePath $Cli -Arguments ("--recipe " + (Q $missing))
Check ($r.ExitCode -ne 0) "a failing recipe exits non-zero" "rc=$($r.ExitCode)"
Check (($r.StdOut + $r.StdErr) -match "recipe_read_error") "the failure names a machine-readable error code"
Write-Host ""

# ---- 4. Unicode and space in the working paths ----------------------------
Write-Host "4. Unicode and space in the working paths"
$uni = Join-Path $Work "prosjekt aeoa 走 test"
New-Item -ItemType Directory -Force -Path $uni | Out-Null
$uniRecipe = Join-Path $uni "oppskrift æøå.json"
Copy-Item -Force $recipeSrc $uniRecipe
$uniOut = Join-Path $uni "ut"
New-Item -ItemType Directory -Force -Path $uniOut | Out-Null
$r = Invoke-Session -FilePath $Cli -Arguments ("--recipe " + (Q $uniRecipe) + " --out " + (Q $uniOut))
Check ($r.ExitCode -eq 0) "the CLI handles non-ASCII recipe and output paths" "rc=$($r.ExitCode) $($r.StdErr)"
Write-Host ""

# ---- 5. Read-only installation directory ----------------------------------
# The Windows equivalent of `chmod -R a-w`: an explicit Deny-Write ACE for
# the running user on the copied install. Program Files is read-only to a
# non-elevated user in exactly this way.
Write-Host "5. Read-only installation directory"
$ro = Join-Path $Work "readonly"
Copy-Item -Recurse -Force $BundleDir $ro
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$acl = Get-Acl $ro
$denyWrite = New-Object System.Security.AccessControl.FileSystemAccessRule(
    $me, "Write,Delete", "ContainerInherit,ObjectInherit", "None", "Deny")
$acl.AddAccessRule($denyWrite)
Set-Acl -Path $ro -AclObject $acl
try {
    $roOut = Join-Path $Work "ro_out"
    New-Item -ItemType Directory -Force -Path $roOut | Out-Null
    $r = Invoke-Session -FilePath (Join-Path $ro "am3d-recipe.exe") `
        -Arguments ("--recipe " + (Q (Join-Path $ro "examples\recipes\minimal.json")) + " --out " + (Q $roOut))
    Check ($r.ExitCode -eq 0) "the CLI runs from a read-only install, writing elsewhere" "rc=$($r.ExitCode)"
    $roSmoke = Join-Path $Work "ro_smoke.json"
    $r = Invoke-Session -FilePath (Join-Path $ro "3D MASTER 2005.exe") `
        -Arguments ("--smoke-test --out " + (Q $roSmoke)) -Extra @{ QT_QPA_PLATFORM = "offscreen" }
    Check ($r.ExitCode -eq 0 -and (Test-Path $roSmoke)) "the GUI's full workflow run works from a read-only install" "rc=$($r.ExitCode)"
} finally {
    $acl = Get-Acl $ro
    $acl.RemoveAccessRule($denyWrite) | Out-Null
    Set-Acl -Path $ro -AclObject $acl
}
Write-Host ""

# ---- 6. Relocation to a path with spaces and non-ASCII characters ---------
Write-Host "6. Relocation to a path with spaces and non-ASCII characters"
$moved = Join-Path (Join-Path $Work "flyttet æøå") "3D MASTER 2005 Beta"
New-Item -ItemType Directory -Force -Path (Split-Path $moved -Parent) | Out-Null
Copy-Item -Recurse -Force $BundleDir $moved
$movedManifest = Join-Path $Work "moved.json"
$r = Invoke-Session -FilePath (Join-Path $moved "3D MASTER 2005.exe") `
    -Arguments ("--smoke-test --out " + (Q $movedManifest)) -Extra @{ QT_QPA_PLATFORM = "offscreen" }
Check ($r.ExitCode -eq 0 -and (Test-Path $movedManifest)) "the relocated bundle passes the full workflow run" "rc=$($r.ExitCode)"
Write-Host ""

# ---- 7. No source-tree references in the payload --------------------------
Write-Host "7. No source-tree references in the payload"
# The repo root as the build script would have seen it: two levels above
# this script's own directory.
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
$leaked = @(Get-ChildItem -Path $BundleDir -Recurse -File -Include *.py, *.json, *.txt, *.md, *.cmd, *.bat -ErrorAction SilentlyContinue |
    Where-Object { $_.Length -lt 4MB } |
    Where-Object { (Select-String -Path $_.FullName -SimpleMatch -Pattern $repoRoot -List -ErrorAction SilentlyContinue) } |
    Select-Object -First 3)
if ($leaked.Count -gt 0) {
    Write-Fail "the payload references its build location"
    $leaked | ForEach-Object { Write-Note $_.FullName }
} else {
    Write-Pass "no build-location references in the payload's text files"
}
Write-Host ""

# ---- 8. The pose on screen reaches the exported file ----------------------
# Reads the two OBJs the packaged smoke run exported at both ends of an
# action, with a parser that shares no code with the exporter.
Write-Host "8. The pose on screen reaches the exported file"
function Get-ObjVertices([string]$Path) {
    $verts = New-Object System.Collections.ArrayList
    foreach ($line in [System.IO.File]::ReadLines($Path)) {
        if ($line.StartsWith("v ")) {
            $p = $line.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)
            [void]$verts.Add(@([double]$p[1], [double]$p[2], [double]$p[3]))
        }
    }
    return $verts
}
$posed = $null
if ($manifest) { $posed = $manifest.artifacts.posed_export }
if (-not $posed) {
    Write-Fail "the smoke run recorded no posed export"
} elseif (-not (Test-Path $posed.rest) -or -not (Test-Path $posed.bent)) {
    Write-Fail "the posed exports named in the manifest do not exist"
} else {
    $a = Get-ObjVertices $posed.rest
    $b = Get-ObjVertices $posed.bent
    if ($a.Count -ne $b.Count -or $a.Count -eq 0) {
        Write-Fail "posed exports disagree on vertex count: $($a.Count) vs $($b.Count)"
    } else {
        $shift = 0.0
        for ($i = 0; $i -lt $a.Count; $i++) {
            for ($j = 0; $j -lt 3; $j++) {
                $d = [Math]::Abs($a[$i][$j] - $b[$i][$j])
                if ($d -gt $shift) { $shift = $d }
            }
        }
        if ($shift -lt 1e-3) {
            Write-Fail "both poses exported identical geometry (bind pose written)"
        } else {
            Write-Pass ("the two exported poses differ by {0:N3} over {1} vertices, read back independently" -f $shift, $a.Count)
        }
    }
}
Write-Host ""

# ---- 9. Long paths (>260 characters) --------------------------------------
# Windows-specific, no Linux counterpart. Without a long-path-aware manifest
# (or the LongPathsEnabled policy) a Win32 open() past MAX_PATH fails with
# ERROR_PATH_NOT_FOUND, which a user hits simply by keeping projects in a
# deeply nested OneDrive folder. Whichever way this lands, it must land
# visibly and not as a silent truncated write.
Write-Host "9. Long output paths (MAX_PATH)"
$segment = "d" * 60
$deep = $Work
for ($i = 0; $i -lt 5; $i++) { $deep = Join-Path $deep $segment }
$longSupported = $true
try { New-Item -ItemType Directory -Force -Path $deep -ErrorAction Stop | Out-Null }
catch { $longSupported = $false }
if (-not $longSupported) {
    Write-Fail "could not even create a >260-character directory: LongPathsEnabled is off on this machine, so the application cannot be tested here (this is itself the user-visible limit -- record it)"
} else {
    Write-Note "deep path length: $($deep.Length) characters"
    $deepOut = Join-Path $deep "out"
    New-Item -ItemType Directory -Force -Path $deepOut | Out-Null
    $r = Invoke-Session -FilePath $Cli -Arguments ("--recipe " + (Q $recipeSrc) + " --out " + (Q $deepOut))
    $wrote = @(Get-ChildItem -Recurse -File $deepOut -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne "report.json" })
    if ($r.ExitCode -eq 0 -and $wrote.Count -gt 0) {
        Write-Pass "the CLI writes into a >260-character path ($($wrote.Count) file(s))"
    } elseif ($r.ExitCode -ne 0) {
        Write-Fail "the CLI failed on a >260-character path -- but it FAILED rather than reporting a success it did not achieve: rc=$($r.ExitCode)"
    } else {
        Write-Fail "the CLI reported success on a >260-character path but wrote nothing"
    }
}
Write-Host ""

# ---- 10. Drive-relative paths (ENV-03a) -----------------------------------
# "D:outside_file" is not an absolute path: Windows resolves it against the
# per-drive current directory, so it can land anywhere. The escape check was
# fixed to reject it (ENV-03a) but has only ever been exercised on Linux,
# where the syntax is meaningless. This runs it on the OS where it is real.
Write-Host "10. Drive-relative output paths are rejected (ENV-03a)"
$driveRelative = Join-Path $Work "drive_relative.json"
$escapeRecipe = @'
{
  "version": 1,
  "name": "drive_relative_escape",
  "objects": [
    {"name": "body", "primitive": "box", "params": {"width": 1, "height": 1, "depth": 1}}
  ],
  "exports": [{"format": "obj", "path": "C:outside_file"}]
}
'@
$escapeRecipe | Out-File -FilePath $driveRelative -Encoding utf8
$escapeOut = Join-Path $Work "escape_out"
New-Item -ItemType Directory -Force -Path $escapeOut | Out-Null
$r = Invoke-Session -FilePath $Cli -Arguments ("--recipe " + (Q $driveRelative) + " --out " + (Q $escapeOut))
$report = $r.StdOut + $r.StdErr
# Any file named outside_file anywhere on the drive would be the failure this
# check exists for; the per-drive current directory it would resolve against
# is this process's, so that is where to look.
$stray = @(
    @(Get-ChildItem -Recurse -File $escapeOut -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "outside_file*" }) +
    @(Get-ChildItem -File (Get-Location).Path -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "outside_file*" })
)
if ($stray.Count -gt 0) {
    Write-Fail "a drive-relative export path was written to $($stray[0].FullName) -- ENV-03a does not hold on Windows"
} elseif ($report -match "output_path_escape") {
    Write-Pass "a drive-relative export path is refused with the output_path_escape error code"
} else {
    Write-Fail "a drive-relative export path wrote nothing but produced no output_path_escape record: rc=$($r.ExitCode)"
}
Write-Host ""

# ---- 11. User-data location -----------------------------------------------
# The Linux run asserts autosaves land in the application's own directory
# under ~/.local/share (finding PATH-01). The Windows equivalent is
# %LOCALAPPDATA%\3DMASTER2005 -- NOT a folder beside the executable, which
# would be unwritable in a Program Files install, and not the generic
# "PySideApp" directory Qt gives an unnamed application.
Write-Host "11. User-data location"
if (-not $manifest) {
    Write-Fail "no smoke manifest -- the autosave location could not be read"
} else {
    $dir = "$($manifest.artifacts.autosave_dir)"
    Write-Note "autosave directory: $dir"
    $inLocalAppData = $dir.StartsWith($env:LOCALAPPDATA, [System.StringComparison]::OrdinalIgnoreCase)
    $named = $dir -match "3DMASTER2005"
    $besideExe = $dir.StartsWith($BundleDir, [System.StringComparison]::OrdinalIgnoreCase)
    Check ($inLocalAppData -and $named -and -not $besideExe) `
        "autosaves live under %LOCALAPPDATA% in this application's own folder" `
        "localappdata=$inLocalAppData named=$named beside_exe=$besideExe"
    $recovered = @($manifest.artifacts.autosave_recovered_objects)
    Check ($recovered.Count -gt 0) "a snapshot was recovered after the document was lost" "recovered=$($recovered -join ',')"
}
Write-Host ""

Write-Host "$($script:Pass) passed, $($script:Fail) failed, $($script:Skip) skipped"
Write-Host "artifacts under $Work"
if ($script:Fail -gt 0) { exit 1 }
exit 0
