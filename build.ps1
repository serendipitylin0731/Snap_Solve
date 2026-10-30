param([switch]$SkipDependencies)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3.10 -m venv .venv
}
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not $SkipDependencies) {
    & $python -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
}
& $python scripts\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }
$distRoot = Join-Path $PSScriptRoot ('build\dist-' + [guid]::NewGuid().ToString('N'))
& $python -m PyInstaller --noconfirm --clean --windowed --onedir --name SnapSolve --distpath $distRoot --icon assets\app.ico --collect-submodules keyring.backends launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Application build failed' }

$compiler = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $compiler) {
    $installation = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*', 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -like 'Inno Setup version 6*' } |
        Select-Object -First 1
    if ($installation) { $compiler = Join-Path $installation.InstallLocation 'ISCC.exe' }
}
if (-not $compiler -or -not (Test-Path -LiteralPath $compiler)) {
    throw 'Inno Setup 6 is required: https://jrsoftware.org/isinfo.php'
}
$staging = Join-Path $PSScriptRoot ('build\installer-output-' + [guid]::NewGuid().ToString('N'))
& $compiler "/O$staging" "/DAppDistDir=$(Join-Path $distRoot 'SnapSolve')" installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
$builtInstaller = Join-Path $staging 'SnapSolve-1.0.4-Windows-x64-Setup.exe'
$releaseDirectory = Join-Path $PSScriptRoot 'release'
New-Item -ItemType Directory -Path $releaseDirectory -Force | Out-Null
Copy-Item -LiteralPath $builtInstaller -Destination (Join-Path $releaseDirectory 'SnapSolve-1.0.4-Windows-x64-Setup.exe') -Force
Get-ChildItem -LiteralPath release -Filter '*.exe' | Select-Object FullName,Length

