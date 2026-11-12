param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
if (-not $OutputPath) {
    $OutputPath = Join-Path $ScriptDir "..\web\downloads\hcc-agent-windows.zip"
}

# Prefer live step-ca export; fall back to bundled copy.
$caSrc = Join-Path $RepoRoot "deploy\plugins\step-ca\certs\HCC-Local-CA.crt"
if (-not (Test-Path $caSrc)) {
    $caSrc = Join-Path $ScriptDir "certs\HCC-Local-CA.crt"
}
if (-not (Test-Path $caSrc)) {
    throw "Missing HCC-Local-CA.crt (run deploy/plugins/step-ca/scripts/export-root.sh)"
}
$bundledCertDir = Join-Path $ScriptDir "certs"
New-Item -ItemType Directory -Force -Path $bundledCertDir | Out-Null
Copy-Item -Path $caSrc -Destination (Join-Path $bundledCertDir "HCC-Local-CA.crt") -Force

$files = @(
    "heartbeat_sender.ps1",
    "install-windows-agent.ps1",
    "install-ca-trust.ps1",
    "uninstall-windows-agent.ps1",
    "register-hcc-agent-service.ps1",
    "setup-hcc-agent.ps1",
    "reinstall-dc.ps1",
    "bootstrap-server-core.ps1",
    "diagnose-server-core.ps1",
    "fix-hcc-agent.ps1",
    "apply-update.ps1",
    "hcc-agent.env.example"
)

$staging = Join-Path $env:TEMP ("hcc-agent-windows-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $staging | Out-Null
foreach ($file in $files) {
    $source = Join-Path $ScriptDir $file
    if (-not (Test-Path $source)) {
        throw "Missing package file: $source"
    }
    Copy-Item -Path $source -Destination (Join-Path $staging $file) -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $staging "certs") | Out-Null
Copy-Item -Path (Join-Path $bundledCertDir "HCC-Local-CA.crt") -Destination (Join-Path $staging "certs\HCC-Local-CA.crt") -Force

if (Test-Path $OutputPath) {
    Remove-Item $OutputPath -Force
}
$outDir = Split-Path -Parent $OutputPath
if ($outDir -and -not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
}
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $OutputPath
# Standalone cert for phones / manual install
$downloadsCert = Join-Path $ScriptDir "..\web\downloads\HCC-Local-CA.crt"
Copy-Item -Path (Join-Path $bundledCertDir "HCC-Local-CA.crt") -Destination $downloadsCert -Force
Remove-Item $staging -Recurse -Force

Write-Host "Created package: $OutputPath"
