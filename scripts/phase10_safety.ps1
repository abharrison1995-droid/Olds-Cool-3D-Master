Set-StrictMode -Version Latest

function Get-Phase10FullPath {
    param([Parameter(Mandatory)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-Phase10PathWithinRoot {
    param(
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$AllowedRoot
    )
    $targetFull = Get-Phase10FullPath $Target
    $rootFull = (Get-Phase10FullPath $AllowedRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $prefix = $rootFull + [System.IO.Path]::DirectorySeparatorChar
    if (-not $targetFull.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing a path outside its allowed root."
    }

    $current = $targetFull
    while ($true) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing a path containing a link or junction."
            }
        }
        if ([string]::Equals($current, $rootFull,
                [System.StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $parent = [System.IO.Path]::GetDirectoryName($current)
        if ([string]::IsNullOrEmpty($parent) -or
            [string]::Equals($parent, $current,
                [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing an unresolved path outside its allowed root."
        }
        $current = $parent
    }
    return $targetFull
}

function Remove-Phase10Directory {
    param(
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$AllowedRoot
    )
    $targetFull = Assert-Phase10PathWithinRoot -Target $Target -AllowedRoot $AllowedRoot
    if (-not (Test-Path -LiteralPath $targetFull)) { return }
    $item = Get-Item -LiteralPath $targetFull -Force
    if (-not $item.PSIsContainer) { throw "Refusing to recursively remove a non-directory." }
    foreach ($child in Get-ChildItem -LiteralPath $targetFull -Force -Recurse -ErrorAction Stop) {
        if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to recursively remove a tree containing a link or junction."
        }
    }
    Remove-Item -LiteralPath $targetFull -Recurse -Force
}

function Remove-Phase10FreshTempDirectory {
    param(
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$RequiredPrefix
    )
    $targetFull = Get-Phase10FullPath $Target
    $tempFull = (Get-Phase10FullPath ([System.IO.Path]::GetTempPath())).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar)
    $current = $tempFull
    while ($true) {
        if (Test-Path -LiteralPath $current) {
            $parentItem = Get-Item -LiteralPath $current -Force
            if (($parentItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Refusing a temporary path beneath a link or junction."
            }
        }
        $parent = [System.IO.Path]::GetDirectoryName($current)
        if ([string]::IsNullOrEmpty($parent) -or
            [string]::Equals($parent, $current,
                [System.StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $current = $parent
    }
    $parent = [System.IO.Path]::GetDirectoryName($targetFull)
    $leaf = [System.IO.Path]::GetFileName($targetFull)
    if (-not [string]::Equals($parent, $tempFull,
            [System.StringComparison]::OrdinalIgnoreCase) -or
        -not $leaf.StartsWith($RequiredPrefix, [System.StringComparison]::Ordinal)) {
        throw "Refusing to remove a path that is not the exact generated temporary directory."
    }
    if (-not (Test-Path -LiteralPath $targetFull)) { return }
    $item = Get-Item -LiteralPath $targetFull -Force
    if (-not $item.PSIsContainer -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to recursively remove an unsafe temporary path."
    }
    foreach ($child in Get-ChildItem -LiteralPath $targetFull -Force -Recurse -ErrorAction Stop) {
        if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to recursively remove a temporary tree containing a link or junction."
        }
    }
    Remove-Item -LiteralPath $targetFull -Recurse -Force
}

function Remove-Phase10File {
    param(
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$AllowedRoot
    )
    $targetFull = Assert-Phase10PathWithinRoot -Target $Target -AllowedRoot $AllowedRoot
    if (-not (Test-Path -LiteralPath $targetFull)) { return }
    $item = Get-Item -LiteralPath $targetFull -Force
    if ($item.PSIsContainer -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to remove a non-regular file."
    }
    Remove-Item -LiteralPath $targetFull -Force
}
