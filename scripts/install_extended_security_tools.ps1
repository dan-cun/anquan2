param(
    [string]$Root = "D:\SecMind\security-tools"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$downloads = Join-Path $Root "downloads\extended-20260723"
New-Item -ItemType Directory -Force -Path $downloads | Out-Null

function Get-ReleaseFile {
    param(
        [Parameter(Mandatory)] [string]$Url,
        [Parameter(Mandatory)] [string]$Name,
        [string]$ExpectedSha256 = ""
    )
    $path = Join-Path $downloads $Name
    $needsDownload = -not (Test-Path -LiteralPath $path)
    if (-not $needsDownload -and $ExpectedSha256) {
        $current = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
        $needsDownload = $current -ne $ExpectedSha256.ToLowerInvariant()
    }
    if ($needsDownload) {
        & curl.exe --fail --location --retry 5 --retry-all-errors --retry-delay 2 `
            --continue-at - --output $path $Url
        if ($LASTEXITCODE -ne 0) {
            throw "Download failed: $Url"
        }
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($ExpectedSha256 -and $actual -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "SHA256 mismatch for ${Name}: expected $ExpectedSha256, got $actual"
    }
    [pscustomobject]@{ Name = $Name; Path = $path; Sha256 = $actual; Url = $Url }
}

function Expand-FreshArchive {
    param(
        [Parameter(Mandatory)] [string]$Archive,
        [Parameter(Mandatory)] [string]$Destination
    )
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
}

$artifacts = @()
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/aquasecurity/trivy/releases/download/v0.72.0/trivy_0.72.0_windows-64bit.zip" `
    -Name "trivy_0.72.0_windows-64bit.zip"
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/google/osv-scanner/releases/download/v2.4.0/osv-scanner_windows_amd64.exe" `
    -Name "osv-scanner_windows_amd64_2.4.0.exe"
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/VirusTotal/yara/releases/download/v4.5.5/yara-4.5.5-2368-win64.zip" `
    -Name "yara-4.5.5-2368-win64.zip"
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/volatilityfoundation/volatility3/releases/download/v2.28.0/volatility3-win-exes-2.28.0.zip" `
    -Name "volatility3-win-exes-2.28.0.zip"
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.11%2B10/OpenJDK21U-jdk_x64_windows_hotspot_21.0.11_10.zip" `
    -Name "OpenJDK21U-jdk_x64_windows_hotspot_21.0.11_10.zip" `
    -ExpectedSha256 "d3625e7cadf23787ea540229544b6e2ab494b3b54da1801879e583e1dfee0a64"
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.2_build/ghidra_12.1.2_PUBLIC_20260605.zip" `
    -Name "ghidra_12.1.2_PUBLIC_20260605.zip"
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/LaurieWired/GhidraMCP/releases/download/1.4/GhidraMCP-release-1-4.zip" `
    -Name "GhidraMCP-release-1-4.zip"
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/projectdiscovery/subfinder/releases/download/v2.14.0/subfinder_2.14.0_windows_amd64.zip" `
    -Name "subfinder_2.14.0_windows_amd64.zip"
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/projectdiscovery/dnsx/releases/download/v1.3.0/dnsx_1.3.0_windows_amd64.zip" `
    -Name "dnsx_1.3.0_windows_amd64.zip"
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/projectdiscovery/naabu/releases/download/v2.6.1/naabu_2.6.1_windows_amd64.zip" `
    -Name "naabu_2.6.1_windows_amd64.zip"
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/zaproxy/zaproxy/releases/download/v2.17.0/ZAP_2.17.0_Crossplatform.zip" `
    -Name "ZAP_2.17.0_Crossplatform.zip" `
    -ExpectedSha256 "94c8f767b1c2e94f0db66b3ae56514d5e3f5a728ee1b6c798e0c8fe2d61fbff0"
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/mandiant/capa/releases/download/v9.4.0/capa-v9.4.0-windows.zip" `
    -Name "capa-v9.4.0-windows.zip" `
    -ExpectedSha256 "670ab1a58b81f59cb57533bf4021ac1e7033fbe9b5d5cc180f796976081e3bb5"
$artifacts += Get-ReleaseFile `
    -Url "https://github.com/mandiant/flare-floss/releases/download/v3.1.1/floss-v3.1.1-windows.zip" `
    -Name "floss-v3.1.1-windows.zip"

Expand-FreshArchive $artifacts[0].Path (Join-Path $Root "trivy\0.72.0")
$osvRoot = Join-Path $Root "osv-scanner\2.4.0"
New-Item -ItemType Directory -Force -Path $osvRoot | Out-Null
Copy-Item -LiteralPath $artifacts[1].Path -Destination (Join-Path $osvRoot "osv-scanner.exe") -Force
Expand-FreshArchive $artifacts[2].Path (Join-Path $Root "yara\4.5.5")
Expand-FreshArchive $artifacts[3].Path (Join-Path $Root "volatility3\2.28.0")
Expand-FreshArchive $artifacts[4].Path (Join-Path $Root "runtimes\temurin-jdk\21.0.11_10")
Expand-FreshArchive $artifacts[5].Path (Join-Path $Root "ghidra\12.1.2")
Expand-FreshArchive $artifacts[6].Path (Join-Path $Root "ghidra-mcp\1.4")
Expand-FreshArchive $artifacts[7].Path (Join-Path $Root "subfinder\2.14.0")
Expand-FreshArchive $artifacts[8].Path (Join-Path $Root "dnsx\1.3.0")
Expand-FreshArchive $artifacts[9].Path (Join-Path $Root "naabu\2.6.1")
Expand-FreshArchive $artifacts[10].Path (Join-Path $Root "zap\2.17.0")
Expand-FreshArchive $artifacts[11].Path (Join-Path $Root "capa\9.4.0")
Expand-FreshArchive $artifacts[12].Path (Join-Path $Root "floss\3.1.1")

$git = "C:\wangan\gongju\Git\bin\git.exe"
$repositories = @(
    @{
        Path = Join-Path $Root "binwalk\3.1.0"
        Url = "https://github.com/ReFirmLabs/binwalk.git"
        Ref = "v3.1.0"
    },
    @{
        Path = Join-Path $Root "zap-mcp"
        Url = "https://github.com/ajtazer/ZAP-MCP.git"
        Ref = "main"
    }
)
foreach ($repository in $repositories) {
    if (-not (Test-Path (Join-Path $repository.Path ".git"))) {
        & $git clone --filter=blob:none --branch $repository.Ref --single-branch `
            $repository.Url $repository.Path
        if ($LASTEXITCODE -ne 0) {
            throw "Git clone failed: $($repository.Url)"
        }
    }
}

$artifacts | ConvertTo-Json -Depth 4 | Set-Content `
    -LiteralPath (Join-Path $downloads "download-record.json") -Encoding utf8
$artifacts | Select-Object Name, Sha256, Url | Format-Table -AutoSize
