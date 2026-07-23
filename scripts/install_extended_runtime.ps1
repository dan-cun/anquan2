param(
    [string]$SecMindRoot = "D:\SecMind",
    [string]$Distro = "SecMind-Ubuntu"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Python = "C:\Users\12241\AppData\Local\Programs\Python\Python311\python.exe"
$ToolRoot = Join-Path $SecMindRoot "security-tools"
$DownloadRoot = Join-Path $ToolRoot "downloads\ubuntu-wsl-24.04"
$Archive = Join-Path $DownloadRoot "ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz"
$ArchiveUrl = "https://cloud-images.ubuntu.com/wsl/releases/24.04/current/ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz"
$ArchiveSha256 = "2a790896740b14d637dbdc583cce1ba081ac53b9e9cdb46dc09a2f73abbd9934"
$WslRoot = Join-Path $SecMindRoot "wsl\Ubuntu"

New-Item -ItemType Directory -Force -Path $DownloadRoot, (Split-Path -Parent $WslRoot) | Out-Null

if (-not (Test-Path -LiteralPath $Archive)) {
    & curl.exe --fail --location --retry 5 --retry-all-errors --retry-delay 2 `
        --continue-at - --output $Archive $ArchiveUrl
    if ($LASTEXITCODE -ne 0) { throw "Ubuntu rootfs download failed" }
}
$actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToLowerInvariant()
if ($actualSha256 -ne $ArchiveSha256) {
    throw "Ubuntu rootfs SHA256 mismatch: expected $ArchiveSha256, got $actualSha256"
}

$distros = @(& wsl.exe --list --quiet) -replace "`0", ""
if ($distros -notcontains $Distro) {
    & wsl.exe --import $Distro $WslRoot $Archive --version 2
    if ($LASTEXITCODE -ne 0) { throw "WSL import failed" }
}

$oleVenv = Join-Path $ToolRoot "oletools\0.60.2\venv"
if (-not (Test-Path (Join-Path $oleVenv "Scripts\python.exe"))) {
    & $Python -m venv $oleVenv
}
& "$oleVenv\Scripts\python.exe" -m pip install --disable-pip-version-check `
    "pip==25.1.1" "oletools==0.60.2"
if ($LASTEXITCODE -ne 0) { throw "oletools installation failed" }
& "$oleVenv\Scripts\python.exe" -m pip freeze |
    Set-Content -Encoding utf8 (Join-Path (Split-Path -Parent $oleVenv) "requirements.lock.txt")

$wheelhouse = Join-Path $ToolRoot "downloads\wsl-wheelhouse"
New-Item -ItemType Directory -Force -Path $wheelhouse | Out-Null
& $Python -m pip download --dest $wheelhouse `
    --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 `
    --python-version 3.12 --implementation cp --abi cp312 --only-binary=:all: `
    "pwntools==4.15.0" "ROPgadget==7.7" "uv==0.8.22"
if ($LASTEXITCODE -ne 0) { throw "WSL wheelhouse download failed" }
& $Python -m pip download --dest $wheelhouse `
    --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 `
    --python-version 3.12 --implementation cp --abi cp312 --only-binary=:all: `
    --no-deps "ziglang==0.14.1" "unicorn==2.1.4" "pwntools==4.14.1" "uv==0.9.28"
if ($LASTEXITCODE -ne 0) { throw "Pwndbg locked wheel download failed" }
& $Python -m pip download --dest $wheelhouse "pip==25.1.1"
if ($LASTEXITCODE -ne 0) { throw "Pinned pip wheel download failed" }

$rustupRoot = Join-Path $ToolRoot "downloads\rustup"
$rustup = Join-Path $rustupRoot "rustup-init"
$rustupSha = Join-Path $rustupRoot "rustup-init.sha256"
New-Item -ItemType Directory -Force -Path $rustupRoot | Out-Null
if (-not (Test-Path $rustup)) {
    & curl.exe --fail --location --retry 5 --output $rustup `
        "https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init"
}
if (-not (Test-Path $rustupSha)) {
    & curl.exe --fail --location --retry 5 --output $rustupSha `
        "https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init.sha256"
}
$expectedRustupSha = ((Get-Content $rustupSha) -split "\s+")[0].ToLowerInvariant()
$actualRustupSha = (Get-FileHash -Algorithm SHA256 $rustup).Hash.ToLowerInvariant()
if ($actualRustupSha -ne $expectedRustupSha) { throw "rustup-init SHA256 mismatch" }

$bootstrap = @'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::ForceIPv4=true -o Acquire::Languages=none \
  -o Acquire::IndexTargets::deb::DEP-11::DefaultEnabled=false update
apt-get -o Acquire::ForceIPv4=true install -y --no-install-recommends \
  ca-certificates curl git build-essential gdb gdbserver checksec \
  python3 python3-venv python3-dev python3-pip pkg-config libfontconfig1-dev \
  liblzma-dev liblzo2-dev zlib1g-dev libbz2-dev libmagic-dev cargo rustc \
  binutils file lzop p7zip-full squashfs-tools sleuthkit
python3 -m venv /opt/secmind-pwn
/opt/secmind-pwn/bin/python -m pip install --no-index \
  --find-links /mnt/d/SecMind/security-tools/downloads/wsl-wheelhouse pip==25.1.1
/opt/secmind-pwn/bin/pip install --no-index \
  --find-links /mnt/d/SecMind/security-tools/downloads/wsl-wheelhouse \
  pwntools==4.15.0 ROPgadget==7.7
/opt/secmind-pwn/bin/pip freeze > /opt/secmind-pwn/requirements.lock.txt
install -m 0755 /mnt/d/SecMind/security-tools/downloads/rustup/rustup-init /tmp/rustup-init
RUSTUP_INIT_SKIP_PATH_CHECK=yes /tmp/rustup-init -y --profile minimal --default-toolchain 1.81.0
cd /mnt/d/SecMind/security-tools/binwalk/3.1.0
/root/.cargo/bin/cargo build --release --locked
install -m 0755 target/release/binwalk /usr/local/bin/binwalk
if [ ! -d /opt/pwndbg/.git ]; then
  git clone --filter=blob:none --branch 2026.02.18 --single-branch \
    https://github.com/pwndbg/pwndbg.git /opt/pwndbg
fi
test "$(git -C /opt/pwndbg rev-parse HEAD)" = "ea3801b666efb1be21db8ef9c8c8d5b6bd0c61de"
python3 -m venv /opt/pwndbg/.venv
/opt/pwndbg/.venv/bin/pip install --no-index \
  --find-links /mnt/d/SecMind/security-tools/downloads/wsl-wheelhouse uv==0.8.22
/opt/pwndbg/.venv/bin/pip install --no-index --no-deps \
  --find-links /mnt/d/SecMind/security-tools/downloads/wsl-wheelhouse \
  ziglang==0.14.1 unicorn==2.1.4 pwntools==4.14.1 uv==0.9.28
cd /opt/pwndbg
PWNDBG_VENV_PATH=/opt/pwndbg/.venv /opt/pwndbg/.venv/bin/uv sync --frozen
'@
& wsl.exe -d $Distro --user root -- bash -lc $bootstrap
if ($LASTEXITCODE -ne 0) { throw "WSL security tool installation failed" }

Write-Host "Extended runtime installation completed for $Distro"
