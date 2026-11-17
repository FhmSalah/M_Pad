param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This build script requires Windows.' }
$projectPath = $PSScriptRoot
$releasePath = Join-Path $projectPath 'release'
$packagePath = Join-Path $releasePath 'Macro Pad'
$configPath = Join-Path $projectPath 'config.json'

# Never replace a prior executable or its edited release config implicitly.
if (Test-Path -LiteralPath $packagePath) {
    throw "Release already exists at $packagePath. Move it aside before rebuilding."
}
if (-not (Test-Path -LiteralPath $configPath)) { throw 'config.json is missing.' }
Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json | Out-Null

& $Python -m PyInstaller --distpath $releasePath --workpath (Join-Path $projectPath 'build\pyinstaller') (Join-Path $projectPath 'MacroPad.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }
if (-not (Test-Path -LiteralPath (Join-Path $packagePath 'Macro Pad.exe'))) {
    throw 'PyInstaller did not produce Macro Pad.exe.'
}
Copy-Item -LiteralPath $configPath -Destination (Join-Path $packagePath 'config.json')
Write-Output "Release ready: $packagePath"
