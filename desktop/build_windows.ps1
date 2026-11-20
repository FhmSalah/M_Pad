param(
    [string]$Python = 'python',
    [switch]$Clean  # Delete a previous release\Macro Pad build output first.
)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This build script requires Windows.' }
$projectPath = $PSScriptRoot
$releasePath = Join-Path $projectPath 'release'
$packagePath = Join-Path $releasePath 'Macro Pad'

if (Test-Path -LiteralPath $packagePath) {
    if (-not $Clean) { throw "Release already exists at $packagePath. Move it aside or use -Clean." }
    Remove-Item -LiteralPath $packagePath -Recurse -Force
}

# No config.json is bundled: each user's settings live in %APPDATA%\Macro Pad\config.json,
# created from starter_config.py on first run.
& $Python -m PyInstaller --noconfirm --distpath $releasePath --workpath (Join-Path $projectPath 'build\pyinstaller') (Join-Path $projectPath 'MacroPad.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
if (-not (Test-Path -LiteralPath (Join-Path $packagePath 'Macro Pad.exe'))) {
    throw 'PyInstaller did not produce Macro Pad.exe.'
}
Write-Output "Release ready: $packagePath"
