[CmdletBinding()]
param(
    [string]$Commit = "HEAD",
    [string]$Path
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Push-Location $repoRoot
try {
    $resolvedCommit = (& git rev-parse $Commit).Trim()
    if ($LASTEXITCODE -ne 0 -or $resolvedCommit -notmatch "^[0-9a-f]{40}$") {
        throw "Cannot resolve commit: $Commit"
    }
    $shortCommit = $resolvedCommit.Substring(0, 12)
    if (-not $Path) {
        $parent = Split-Path $repoRoot -Parent
        $leaf = Split-Path $repoRoot -Leaf
        $Path = Join-Path $parent "$leaf-baseline-$shortCommit"
    }
    $target = [System.IO.Path]::GetFullPath($Path)

    if (Test-Path -LiteralPath $target) {
        $existingCommit = (& git -C $target rev-parse HEAD).Trim()
        $existingDirty = & git -C $target status --porcelain
        if ($LASTEXITCODE -ne 0 -or $existingCommit -ne $resolvedCommit -or $existingDirty) {
            throw "Existing target is not a clean worktree at $resolvedCommit`: $target"
        }
    }
    else {
        & git worktree add --detach $target $resolvedCommit
        if ($LASTEXITCODE -ne 0) {
            throw "git worktree add failed"
        }
    }

    [ordered]@{
        path = $target
        commit = $resolvedCommit
        short_commit = $shortCommit
        detached = $true
        clean = $true
    } | ConvertTo-Json
}
finally {
    Pop-Location
}
