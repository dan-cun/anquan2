[CmdletBinding()]
param(
    [ValidateSet("Both", "Online", "Benchmark")]
    [string]$Target = "Both",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stateDir = Join-Path $repoRoot "benchmark\.state"
$manifestPath = Join-Path $stateDir "deployment.json"
$contractPath = Join-Path $repoRoot "config\runtime-contract.json"

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

function Get-StringSha256 {
    param([string]$Value)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return -join ($algorithm.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") })
    }
    finally {
        $algorithm.Dispose()
    }
}

Push-Location $repoRoot
try {
    $dirty = (& git status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect Git status" }
    if ($dirty) {
        throw "Refusing immutable deployment from a dirty worktree. Commit or stash all changes first."
    }

    $commit = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $commit) { throw "Cannot resolve Git HEAD" }
    $shortCommit = $commit.Substring(0, 12)
    $imageRef = "secmind-backend:git-$shortCommit"

    if (-not $SkipBuild) {
        Invoke-Checked docker @(
            "build", "--pull", "--build-arg", "SECMIND_SOURCE_COMMIT=$commit",
            "--file", "docker/backend.Dockerfile", "--tag", $imageRef, "secmind/backend"
        )
    }
    $imageDigest = (& docker image inspect --format "{{.Id}}" $imageRef).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $imageDigest.StartsWith("sha256:")) {
        throw "Cannot resolve immutable image ID for $imageRef"
    }

    $contract = Get-Content -Raw -Encoding UTF8 $contractPath | ConvertFrom-Json
    $versions = [ordered]@{}
    foreach ($property in $contract.version_sources.PSObject.Properties) {
        $source = $property.Value
        $sourcePath = Join-Path $repoRoot $source.path
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            throw "Version source does not exist: $($source.path)"
        }
        $entry = [ordered]@{
            version = $source.version
            path = ($source.path -replace "\\", "/")
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath).Hash.ToLowerInvariant()
        }
        if ($property.Name -eq "model") {
            $rawPublicConfig = @{}
            foreach ($line in Get-Content -LiteralPath $sourcePath -Encoding UTF8) {
                $trimmed = $line.Trim()
                if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
                $parts = $trimmed.Split("=", 2)
                if ($parts.Count -ne 2) { throw "Invalid public model setting: $trimmed" }
                if ($parts[0] -match "(?i)(KEY|SECRET|TOKEN|PASSWORD)") {
                    throw "Sensitive setting is not allowed in public model config: $($parts[0])"
                }
                $rawPublicConfig[$parts[0].Trim()] = $parts[1].Trim()
            }
            $publicConfig = [ordered]@{}
            foreach ($key in ($rawPublicConfig.Keys | Sort-Object)) {
                $publicConfig[$key] = $rawPublicConfig[$key]
            }
            $entry.config = $publicConfig
            $canonicalConfig = ($publicConfig | ConvertTo-Json -Compress)
            $entry.config_sha256 = Get-StringSha256 $canonicalConfig
            $entry.sha256 = $entry.config_sha256
        }
        elseif ($property.Name -eq "mcp") {
            $mcpConfig = Get-Content -Raw -Encoding UTF8 -LiteralPath $sourcePath |
                ConvertFrom-Json
            $canonicalMcpConfig = $mcpConfig | ConvertTo-Json -Compress -Depth 20
            $entry.sha256 = Get-StringSha256 $canonicalMcpConfig
        }
        $versions[$property.Name] = $entry
    }

    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    $manifest = [ordered]@{
        schema_version = "1.0"
        deployed_at = [DateTimeOffset]::UtcNow.ToString("o")
        source_commit = $commit
        image = [ordered]@{ reference = $imageRef; digest = $imageDigest }
        runtime_contract_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $contractPath).Hash.ToLowerInvariant()
        versions = $versions
        targets = @($Target.ToLowerInvariant())
    }
    $previousImage = $env:SECMIND_BACKEND_IMAGE
    $previousCommit = $env:SECMIND_SOURCE_COMMIT
    $previousDigest = $env:SECMIND_IMAGE_DIGEST
    try {
        $env:SECMIND_BACKEND_IMAGE = $imageRef
        $env:SECMIND_SOURCE_COMMIT = $commit
        $env:SECMIND_IMAGE_DIGEST = $imageDigest
        if ($Target -in @("Both", "Online")) {
            Invoke-Checked docker @(
                "compose", "-f", "compose.yaml", "up", "-d", "--no-build",
                "--force-recreate", "--wait", "--wait-timeout", "180", "migrate", "backend"
            )
        }
        if ($Target -in @("Both", "Benchmark")) {
            Invoke-Checked docker @(
                "compose", "-f", "compose.benchmark.yaml", "up", "-d", "--no-build",
                "--force-recreate", "--wait", "--wait-timeout", "180", "backend"
            )
        }
    }
    finally {
        $env:SECMIND_BACKEND_IMAGE = $previousImage
        $env:SECMIND_SOURCE_COMMIT = $previousCommit
        $env:SECMIND_IMAGE_DIGEST = $previousDigest
    }

    $manifestJson = $manifest | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText(
        $manifestPath,
        $manifestJson + [Environment]::NewLine,
        (New-Object System.Text.UTF8Encoding($false))
    )

    Write-Output $manifestJson
}
finally {
    Pop-Location
}
