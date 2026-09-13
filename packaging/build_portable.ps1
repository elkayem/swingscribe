<#
.SYNOPSIS
Build the portable SwingScribe folder and zip it (docs/packaging-plan.md, piece 3).

.DESCRIPTION
A copy, not a compile. The folder is a standalone CPython with every library
from the lock file installed into its own site-packages, SwingScribe's wheel,
ffmpeg, and the launcher scripts from packaging/portable. Nothing in it is a
freshly built binary: Smart App Control judges executables by the reputation
of their exact bytes, so the interpreter is pinned to the python-build-
standalone RELEASE (not just the version) that runs this project on the dev
machine, and its python.exe is checked against the recorded hash before
anything else happens.

Pins live at the top of this file. To move one: change it here, run the
build, launch the result on a machine with Smart App Control on, and record
the new hash. docs/packaging-plan.md, "Rebuilding a release", has the
sequence.

Needs: uv, git (beat_this is a git dependency in the lock), tar (in Windows
since 2018), and a network. Under OneDrive set UV_LINK_MODE=copy; behind
TLS interception UV_SYSTEM_CERTS=true (both set below).

.PARAMETER OutDir
Where to build. Default: %LOCALAPPDATA%\SwingScribe-build -- deliberately NOT
under the repo, which lives under OneDrive: OneDrive locks files inside a
directory being removed (WinError 5 on the final rmdir, CLAUDE.md), and a
1.5 GB build tree is not something to sync.

.PARAMETER SkipZip
Build the folder but do not zip it (faster while iterating on the scripts).
#>
param(
    [string]$OutDir = "",
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is 10x slower with the bar

# ── pins ────────────────────────────────────────────────────────────────────
# python-build-standalone: the release uv installed here (BUILD file under
# uv's python dir) and the interpreter that has been passing Smart App Control
# on the dev machine. install_only_stripped is the variant uv uses.
$PbsRelease  = "20260814"
$PbsAsset    = "cpython-3.11.16+20260814-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
$PbsSha256   = "c6de1a7781580d13f68dece33ac10b7a608c7ac21fc08cf0f4e0678a7d134905"
# sha256 of python.exe inside it, as measured on the dev machine 2026-09-13.
$PythonExeSha256 = "624b66d8178129ac5611f3cf32adf440ea0b7dc6b1bde60c5677d7ebc62e635d"

# ffmpeg: BtbN's builds, the LGPL variant (the gyan.dev builds winget installs
# are GPL, which would bind the whole folder). The release's checksums.sha256
# is fetched and the zip verified against it.
$FfmpegTag   = "autobuild-2026-09-13-14-50"
$FfmpegAsset = "ffmpeg-n8.1.2-52-g5a03dfa0f6-win64-lgpl-8.1.zip"

# torch's CPU wheels are not on PyPI; uv export emits no index lines.
$TorchIndex  = "https://download.pytorch.org/whl/cpu"
# ────────────────────────────────────────────────────────────────────────────

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutDir) { $OutDir = Join-Path $env:LOCALAPPDATA "SwingScribe-build" }
$OutDir = [System.IO.Path]::GetFullPath($OutDir)
$downloads = Join-Path $OutDir "downloads"
$stage = Join-Path $OutDir "SwingScribe"
$env:UV_LINK_MODE = "copy"
$env:UV_SYSTEM_CERTS = "true"

$version = (Select-String -Path (Join-Path $repo "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "SwingScribe $version -> $stage"

function Sha256([string]$path) { (Get-FileHash -Algorithm SHA256 $path).Hash.ToLower() }

# Native tools through cmd, streams merged: Windows PowerShell 5.1 turns a
# native program's stderr into an ErrorRecord whenever the output is
# redirected, and uv reports progress on stderr -- so a plain `uv export`
# under $ErrorActionPreference = Stop dies on "Resolved 105 packages".
function Native([string]$commandLine) {
    Write-Host "  > $commandLine"
    cmd /c "$commandLine 2>&1"
    if ($LASTEXITCODE -ne 0) { throw "failed ($LASTEXITCODE): $commandLine" }
}

function Fetch([string]$url, [string]$path, [string]$sha) {
    if ((Test-Path $path) -and (-not $sha -or (Sha256 $path) -eq $sha)) {
        Write-Host "  cached  $(Split-Path -Leaf $path)"
        return
    }
    Write-Host "  fetch   $url"
    Invoke-WebRequest -Uri $url -OutFile $path -UseBasicParsing -Headers @{ "User-Agent" = "swingscribe-build" }
    if ($sha) {
        $got = Sha256 $path
        if ($got -ne $sha) { throw "checksum mismatch for $(Split-Path -Leaf $path): got $got, want $sha" }
    }
}

# ── 0. clean stage ──────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force $downloads | Out-Null
if (Test-Path $stage) {
    # Retried: a file in a tree being removed can be held briefly by a
    # sync client or an indexer, and 5.1 reports that as "access denied".
    # On the dev machine Norton's data protector also PROMPTS here and
    # refuses until allowed (folder.gif, then libcrypto-3-x64.dll) -- it is
    # this script deleting its own previous output; allow it.
    foreach ($attempt in 1..5) {
        try { Remove-Item -Recurse -Force $stage -ErrorAction Stop; break }
        catch { if ($attempt -eq 5) { throw }; Start-Sleep -Seconds 2 }
    }
}
New-Item -ItemType Directory -Force $stage | Out-Null

# ── 1. the interpreter ──────────────────────────────────────────────────────
Write-Host "1. Python (python-build-standalone $PbsRelease)"
$pbsPath = Join-Path $downloads $PbsAsset
Fetch "https://github.com/astral-sh/python-build-standalone/releases/download/$PbsRelease/$([uri]::EscapeDataString($PbsAsset))" $pbsPath $PbsSha256
$unpack = Join-Path $downloads "pbs-unpacked"
if (Test-Path $unpack) { Remove-Item -Recurse -Force $unpack }
New-Item -ItemType Directory -Force $unpack | Out-Null
Native "tar -xzf `"$pbsPath`" -C `"$unpack`""
Move-Item (Join-Path $unpack "python") (Join-Path $stage "python")
$py = Join-Path $stage "python\python.exe"
$gotExe = Sha256 $py
if ($gotExe -ne $PythonExeSha256) {
    throw "python.exe in $PbsAsset hashes $gotExe, not the recorded $PythonExeSha256 -- a different file with its own reputation. Re-measure on a Smart App Control machine before updating the pin."
}
Write-Host "  python.exe matches the recorded hash"

# ── 2. the libraries, from the lock file ────────────────────────────────────
Write-Host "2. libraries (uv export -> uv pip install into the interpreter)"
$req = Join-Path $OutDir "requirements.txt"
Push-Location $repo
try {
    Native "uv export --group ml --group gui --group roformer --no-hashes --no-emit-project --no-dev -o `"$req`""
    # unsafe-best-match: consider every index for each name so the lock's
    # exact pins win; with the default first-index strategy a package that
    # merely EXISTS on the torch index (numpy does) is taken from there and
    # the pinned version may not be.
    Native "uv pip install --python `"$py`" --index $TorchIndex --index-strategy unsafe-best-match -r `"$req`""
    $dist = Join-Path $OutDir "dist"
    if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
    Native "uv build --wheel -o `"$dist`""
    $wheel = Get-ChildItem $dist -Filter "swingscribe-*.whl" | Select-Object -First 1
    Native "uv pip install --python `"$py`" --no-deps `"$($wheel.FullName)`""
} finally { Pop-Location }

# ── 3. strip what a user never runs ─────────────────────────────────────────
Write-Host "3. strip"
# Console-script stubs are per-install binaries with no reputation, and
# nothing in the folder calls them.
$scripts = Join-Path $stage "python\Scripts"
if (Test-Path $scripts) { Get-ChildItem $scripts -Filter "*.exe" | Remove-Item -Force }
Get-ChildItem (Join-Path $stage "python") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# ── 4. ffmpeg ───────────────────────────────────────────────────────────────
Write-Host "4. ffmpeg ($FfmpegTag, LGPL)"
$sums = Join-Path $downloads "ffmpeg-checksums-$FfmpegTag.sha256"
Fetch "https://github.com/BtbN/FFmpeg-Builds/releases/download/$FfmpegTag/checksums.sha256" $sums ""
$line = Get-Content $sums | Where-Object { $_ -match [regex]::Escape($FfmpegAsset) } | Select-Object -First 1
if (-not $line) { throw "$FfmpegAsset is not in $FfmpegTag's checksums.sha256" }
$ffSha = ($line -split '\s+')[0].ToLower()
$ffZip = Join-Path $downloads $FfmpegAsset
Fetch "https://github.com/BtbN/FFmpeg-Builds/releases/download/$FfmpegTag/$FfmpegAsset" $ffZip $ffSha
$ffUnpack = Join-Path $downloads "ffmpeg-unpacked"
if (Test-Path $ffUnpack) { Remove-Item -Recurse -Force $ffUnpack }
Expand-Archive $ffZip -DestinationPath $ffUnpack
$ffRoot = Get-ChildItem $ffUnpack -Directory | Select-Object -First 1
$ffDest = Join-Path $stage "ffmpeg"
New-Item -ItemType Directory -Force $ffDest | Out-Null
Copy-Item (Join-Path $ffRoot.FullName "bin\ffmpeg.exe") $ffDest
Copy-Item (Join-Path $ffRoot.FullName "LICENSE.txt") (Join-Path $ffDest "LICENSE.txt")
Set-Content -Encoding ascii (Join-Path $ffDest "SOURCE.txt") "ffmpeg from https://github.com/BtbN/FFmpeg-Builds/releases/tag/$FfmpegTag`r`n$FfmpegAsset (LGPL build)`r`nsha256 $ffSha"

# ── 5. the folder's own files ───────────────────────────────────────────────
Write-Host "5. launcher, setup, uninstall, config, notices"
Copy-Item (Join-Path $repo "packaging\portable\*") $stage
Copy-Item (Join-Path $repo "src\swingscribe\default-config.yaml") (Join-Path $stage "swingscribe.yaml")
Copy-Item (Join-Path $repo "assets\swingscribe.ico") $stage
Copy-Item (Join-Path $repo "packaging\NOTICES.md") $stage
Copy-Item (Join-Path $repo "LICENSE") (Join-Path $stage "LICENSE.txt")
[System.IO.File]::WriteAllText((Join-Path $stage "VERSION"), $version)   # Set-Content -NoNewline wrote nothing here

# ── 6. zip ──────────────────────────────────────────────────────────────────
$folderMB = [math]::Round((Get-ChildItem $stage -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "folder: $folderMB MB"
if (-not $SkipZip) {
    $zipBase = Join-Path $OutDir "SwingScribe-$version-windows-x64"
    Write-Host "6. zip -> $zipBase.zip"
    if (Test-Path "$zipBase.zip") { Remove-Item -Force "$zipBase.zip" }
    # The built interpreter zips its own folder: Compress-Archive is slow and
    # its own path handling is the weakest part of PowerShell 5.1.
    Native "`"$py`" -I -c `"import shutil, sys; shutil.make_archive(sys.argv[1], 'zip', root_dir=sys.argv[2], base_dir='SwingScribe')`" `"$zipBase`" `"$OutDir`""
    $zipMB = [math]::Round((Get-Item "$zipBase.zip").Length / 1MB)
    Write-Host "zip: $zipMB MB"
    Write-Host "sha256: $(Sha256 "$zipBase.zip")"
}
Write-Host "done"
