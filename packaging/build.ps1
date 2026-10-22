# Build a FileMorph release on Windows (same steps CI runs).
#   Requires: Python 3.11+ (python.org) and the .NET 8+ SDK (for Velopack's `vpk` tool)
#   Run from the repo root:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#   Output: Releases\FileMorph-win-Setup.exe (installer) + update packages
#   Add -Publish to upload the release to GitHub (needs $env:GITHUB_TOKEN with repo access).
param([switch]$Publish, [switch]$SkipBuild)   # -SkipBuild: reuse dist\FileMorph, just test + package
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"          # Python reads/writes UTF-8 regardless of the console code page
$env:PYTHONIOENCODING = "utf-8"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE) - see the lines above" } }

if (-not (Test-Path .venv)) {
  # Prefer a Python that every dependency ships ready-made wheels for (3.12/3.13), then any 3.x
  $made = $false
  if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in "3.12", "3.13") {
      $installed = (& py --list | Out-String) -match "-V:$v|-$v"   # don't call a missing version
      if (-not $installed) { continue }
      & py "-$v" -m venv .venv
      if ($LASTEXITCODE -eq 0 -and (Test-Path .venv\Scripts\python.exe)) { $made = $true; Write-Host "Using Python $v"; break }
    }
  }
  if (-not $made) { python -m venv .venv; Check "Creating the virtual environment" }
}
$py = ".venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
Check "Upgrading pip"
& $py -m pip install -r requirements.txt pyinstaller
Check "Installing requirements"
& $py packaging\make_version_info.py
Check "Writing version info"

$version = & $py -c "import filemorph; print(filemorph.__version__)"
$repoUrl = & $py -c "import filemorph; print(filemorph.UPDATE_URL)"
Write-Host "Building FileMorph $version (updates from $repoUrl)" -ForegroundColor Cyan
& $py packaging\release_notes.py $version -o notes.md
if ($LASTEXITCODE -ne 0) { throw "Couldn't read release notes for $version from CHANGELOG.md (see the error above)" }

if (-not $SkipBuild -or -not (Test-Path "dist\FileMorph\FileMorph.exe")) {
  & $py packaging\make_icon.py
  Check "Making the icon"
  & .venv\Scripts\pyinstaller.exe packaging\filemorph.spec --noconfirm --clean
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (see above)" }
}

Write-Host "Self-testing the packaged app..." -ForegroundColor Cyan
$report = Join-Path $root "selftest.json"
$crash = Join-Path $env:LOCALAPPDATA "FileMorph\logs\crash.log"
Remove-Item $report, $crash -ErrorAction SilentlyContinue
$exe = Join-Path $root "dist\FileMorph\FileMorph.exe"
# Note: in Windows PowerShell 5.1, `Start-Process -Wait -PassThru` can leave ExitCode blank, so the
# verdict comes from the report itself (every step "ok", no crash), not the exit code.
$p = Start-Process $exe -ArgumentList "--selftest", "`"$report`"" -WorkingDirectory $root -PassThru
$null = $p.Handle   # cache the handle so ExitCode is available after exit
$p.WaitForExit()
if (-not (Test-Path $report) -and (Test-Path $crash)) { Get-Content $crash }
& $py packaging\check_selftest.py $report
if ($LASTEXITCODE -ne 0) { throw "Self-test failed - see the lines above" }

if (-not (Get-Command vpk -ErrorAction SilentlyContinue)) {
  $vp = & $py -c "import importlib.metadata as m; print(m.version('velopack'))"
  dotnet tool install -g vpk --version $vp
  if ($LASTEXITCODE -ne 0) { dotnet tool install -g vpk; Check "Installing vpk (needs the .NET SDK)" }
  $tools = Join-Path $env:USERPROFILE ".dotnet\tools"   # new installs aren't on PATH until a new terminal
  if ($env:PATH -notlike "*$tools*") { $env:PATH = "$env:PATH;$tools" }
}
$tokenArgs = @(); if ($env:GITHUB_TOKEN) { $tokenArgs = @("--token", $env:GITHUB_TOKEN) }
vpk download github --repoUrl $repoUrl @tokenArgs   # previous release -> small delta update
if ($LASTEXITCODE -ne 0) { Write-Host "No previous release downloaded (fine for the first release) - building a full package only." -ForegroundColor Yellow }
vpk pack --packId FileMorph --packVersion $version --packDir dist\FileMorph --mainExe FileMorph.exe `
         --packTitle FileMorph --icon assets\icon.ico --releaseNotes notes.md
if ($LASTEXITCODE -ne 0) { throw "vpk pack failed" }

if ($Publish) {
  vpk upload github --repoUrl $repoUrl @tokenArgs --publish --releaseName "FileMorph $version" --tag "v$version"
  Check "Uploading the release to GitHub"
}
Write-Host "Done: Releases\FileMorph-win-Setup.exe" -ForegroundColor Green
