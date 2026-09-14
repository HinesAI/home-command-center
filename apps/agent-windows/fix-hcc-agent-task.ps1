<#
.SYNOPSIS
  Repairs HCC-Agent scheduling and installs a watchdog for stale heartbeats.

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\fix-hcc-agent-task.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = "HCC-Agent",
    [string]$InstallDir = (Join-Path $env:ProgramFiles "HCC-Agent"),
    [string]$AgentScript = "",
    [string]$DownloadsBaseUrl = "http://192.168.1.10:3000/downloads",
    [int]$IntervalSeconds = 120,
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
        "register-hcc-agent-task.ps1" = "$BaseUrl/ad/register-hcc-agent-task.ps1"
        "watchdog-hcc-agent.ps1" = "$BaseUrl/ad/watchdog-hcc-agent.ps1"
    }
    foreach ($entry in $files.GetEnumerator()) {
        $dest = Join-Path $TargetDir $entry.Key
        Write-Host "Syncing $($entry.Key) from $($entry.Value)"
        Invoke-WebRequest -Uri $entry.Value -OutFile $dest -UseBasicParsing
    }
}

function Stop-HccAgentProcesses {
    param([string]$ScriptPath)
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*heartbeat_sender.ps1*" } |
        ForEach-Object {
            Write-Host "Stopping stale agent process pid=$($_.ProcessId)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

function Reset-HccAgentTask {
    param([string]$Name)
    Disable-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue | Out-Null
    Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    schtasks.exe /End /TN $Name 2>$null | Out-Null
    Start-Sleep -Seconds 2
    Enable-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue | Out-Null
}

if (-not $SkipScriptSync) {
    Sync-HccAgentScripts -TargetDir $InstallDir -BaseUrl $DownloadsBaseUrl
}

. (Join-Path $InstallDir "register-hcc-agent-task.ps1")

if (-not (Test-Path $AgentScript)) {
    throw "Agent script not found: $AgentScript"
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    throw "Scheduled task '$TaskName' not found. Re-run bootstrap install first."
}

$runAs = $existing.Principal.UserId
Reset-HccAgentTask -Name $TaskName
Stop-HccAgentProcesses -ScriptPath $AgentScript

Register-HccAgentScheduledTask `
    -TaskName $TaskName `
    -AgentScript $AgentScript `
    -IntervalSeconds $IntervalSeconds `
    -RunAsAccount $runAs `
    -StartNow

Register-HccAgentWatchdogTask -RunAsAccount $runAs

$envPath = Join-Path $env:ProgramData "HCC-Agent\hcc-agent.env"
if (Test-Path $envPath) {
    $content = Get-Content $envPath -Raw
    if ($content -match 'HCC_AGENT_VERSION=') {
        $content = $content -replace 'HCC_AGENT_VERSION=.*', 'HCC_AGENT_VERSION=1.0.4'
        Set-Content -Path $envPath -Value $content.TrimEnd() -Encoding ASCII
    } else {
        Add-Content -Path $envPath -Value "HCC_AGENT_VERSION=1.0.4" -Encoding ASCII
    }
}

Write-Host "Repaired scheduled task '$TaskName' (daemon loop, startup trigger, ignore-new instances)."
Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo | Format-List

Write-Host "`nRunning verification heartbeat..."
$verify = powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $AgentScript -Once 2>&1
Write-Host $verify

if (Test-Path (Join-Path $env:ProgramData "HCC-Agent\agent.log")) {
    Write-Host "`nRecent agent log:"
    Get-Content (Join-Path $env:ProgramData "HCC-Agent\agent.log") -Tail 12
}
