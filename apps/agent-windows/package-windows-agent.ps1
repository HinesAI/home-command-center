param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $OutputPath) {
    $OutputPath = Join-Path $ScriptDir "hcc-agent-windows.zip"
}

$files = @(
    "heartbeat_sender.ps1",
    "install-windows-agent.ps1",
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

if (Test-Path $OutputPath) {
    Remove-Item $OutputPath -Force
}
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $OutputPath
Remove-Item $staging -Recurse -Force

Write-Host "Created package: $OutputPath"
