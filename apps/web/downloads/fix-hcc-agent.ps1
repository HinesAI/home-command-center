<#
.SYNOPSIS
  Repairs the HCC-Agent Windows service and syncs agent scripts from the core web server.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\fix-hcc-agent.ps1
#>
[CmdletBinding()]
param(
    [string]$ServiceName = "HCC-Agent",
    [string]$InstallDir = (Join-Path $env:ProgramFiles "HCC-Agent"),
    [string]$AgentScript = "",
    [string]$DownloadsBaseUrl = "http://192.168.1.10:3000/downloads",
    [switch]$SkipScriptSync
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not $AgentScript) {
    $AgentScript = Join-Path $InstallDir "heartbeat_sender.ps1"
}

function Sync-HccAgentScripts {
    param(
        [string]$TargetDir,
        [string]$BaseUrl
    )
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
    $files = @{
        "heartbeat_sender.ps1" = "$BaseUrl/heartbeat_sender.ps1"
        "register-hcc-agent-service.ps1" = "$BaseUrl/register-hcc-agent-service.ps1"
    }
    foreach ($entry in $files.GetEnumerator()) {
        $dest = Join-Path $TargetDir $entry.Key
        Write-Host "Syncing $($entry.Key) from $($entry.Value)"
        Invoke-WebRequest -Uri $entry.Value -OutFile $dest -UseBasicParsing
    }
}

if (-not $SkipScriptSync) {
    Sync-HccAgentScripts -TargetDir $InstallDir -BaseUrl $DownloadsBaseUrl
}

$registerScript = Join-Path $InstallDir "register-hcc-agent-service.ps1"
if (-not (Test-Path $registerScript)) {
    throw "Missing register-hcc-agent-service.ps1 in $InstallDir"
}
. $registerScript

if (-not (Test-Path $AgentScript)) {
    throw "Agent script not found: $AgentScript"
}

$runAs = ""
$envPath = Join-Path $env:ProgramData "HCC-Agent\hcc-agent.env"
if (Test-Path $envPath) {
    foreach ($line in Get-Content $envPath) {
        if ($line -match "^HCC_SERVICE_ACCOUNT=(.+)$") {
            $runAs = $Matches[1].Trim().Trim('"')
        }
    }
}

Register-HccAgentService `
    -ServiceName $ServiceName `
    -AgentScript $AgentScript `
    -RunAsAccount $runAs `
    -RemoveLegacyTasks `
    -StartNow

if (Test-Path $envPath) {
    $content = Get-Content $envPath -Raw
    if ($content -match 'HCC_AGENT_VERSION=') {
        $content = $content -replace 'HCC_AGENT_VERSION=.*', 'HCC_AGENT_VERSION=1.0.5'
        Set-Content -Path $envPath -Value $content.TrimEnd() -Encoding ASCII
    } else {
        Add-Content -Path $envPath -Value "HCC_AGENT_VERSION=1.0.5" -Encoding ASCII
    }
}

Write-Host "Repaired Windows service '$ServiceName' (auto-start, failure restart)."
Get-Service -Name $ServiceName | Format-List Name, Status, StartType

Write-Host "`nRunning verification heartbeat..."
$verify = powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $AgentScript -Once 2>&1
Write-Host $verify

if (Test-Path (Join-Path $env:ProgramData "HCC-Agent\agent.log")) {
    Write-Host "`nRecent agent log:"
    Get-Content (Join-Path $env:ProgramData "HCC-Agent\agent.log") -Tail 12
}
