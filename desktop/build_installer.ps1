param(
    [string]$Python = '.\.venv-win\Scripts\python.exe',
    [string]$Iscc = ''
)

# Builds the app (PyInstaller) and then the Windows setup file (Inno Setup 6).
# Output: desktop\dist\MacroPad-Setup-<version>.exe

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not $Iscc) {
    $Iscc = @(
        (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $Iscc) { throw 'Inno Setup 6 not found. Install it: winget install JRSoftware.InnoSetup' }

$version = (& $Python -c "from version import VERSION; print(VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) { throw 'Could not read VERSION from version.py.' }

& .\build_windows.ps1 -Python $Python -Clean
& $Iscc "/DAppVersion=$version" '.\installer\windows\MacroPad.iss'
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE." }
Write-Output "Installer ready: $(Join-Path $PSScriptRoot "dist\MacroPad-Setup-$version.exe")"
