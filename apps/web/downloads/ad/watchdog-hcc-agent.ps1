$ErrorActionPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ConfigDir = Join-Path $env:ProgramData "HCC-Agent"
$LogPath = Join-Path $ConfigDir "agent.log"
$StatePath = Join-Path $ConfigDir "agent-state.json"
$EnvPath = Join-Path $ConfigDir "hcc-agent.env"
$AgentScript = Join-Path $env:ProgramFiles "HCC-Agent\heartbeat_sender.ps1"
$TaskName = "HCC-Agent"
$RegisterScript = Join-Path $env:ProgramFiles "HCC-Agent\register-hcc-agent-task.ps1"

function Write-AgentLog {
    param([string]$Message)
    try {
        New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
        $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        Add-Content -Path $LogPath -Value "$stamp watchdog $Message"
    } catch {}
}

function Read-IntervalSeconds {
    if (-not (Test-Path $EnvPath)) { return 120 }
    foreach ($line in Get-Content $EnvPath) {
        if ($line -match "^HCC_AGENT_INTERVAL_SECONDS=(\d+)") {
            return [Math]::Max(60, [int]$Matches[1])
        }
    }
    return 120
}

function Read-ServiceAccount {
    if (-not (Test-Path $EnvPath)) { return "" }
    foreach ($line in Get-Content $EnvPath) {
        if ($line -match "^HCC_SERVICE_ACCOUNT=(.+)$") {
            return $Matches[1].Trim().Trim('"')
        }
    }
    return ""
}

function Get-AgentState {
    if (-not (Test-Path $StatePath)) { return $null }
    try {
        return Get-Content $StatePath -Raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Parse-UtcTimestamp {
    param([string]$Value)
    if (-not $Value) { return $null }
    try {
        return [datetime]::ParseExact($Value, "yyyy-MM-ddTHH:mm:ssZ", $null).ToUniversalTime()
    } catch {
        return $null
    }
}

function Get-LastSuccessUtc {
    $state = Get-AgentState
    $fromState = Parse-UtcTimestamp ([string]$state.lastSuccessUtc)
    if ($fromState) { return $fromState }

    if (-not (Test-Path $LogPath)) { return $null }
    $lines = Get-Content $LogPath -Tail 40 -ErrorAction SilentlyContinue
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        $line = [string]$lines[$i]
        if ($line -match "^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)" -and $line -match "heartbeat sent|processed \d+ action") {
            return Parse-UtcTimestamp $Matches[1]
        }
    }
    return $null
}

function Restart-HccAgentTask {
    param([string]$Reason)
    Write-AgentLog $Reason
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($info) {
        Write-AgentLog "task restarted lastRun=$($info.LastRunTime) nextRun=$($info.NextRunTime) result=$($info.LastTaskResult)"
    }
}

$interval = Read-IntervalSeconds
$staleAfter = [TimeSpan]::FromSeconds($interval + 90)
$lastSuccess = Get-LastSuccessUtc
$now = (Get-Date).ToUniversalTime()

if ($lastSuccess -and (($now - $lastSuccess) -lt $staleAfter)) {
    exit 0
}

Write-AgentLog "stale heartbeat detected; lastSuccess=$lastSuccess interval=${interval}s"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-AgentLog "scheduled task missing; attempting repair registration"
    if (Test-Path $RegisterScript) {
        . $RegisterScript
        Register-HccAgentScheduledTask `
            -AgentScript $AgentScript `
            -IntervalSeconds $interval `
            -RunAsAccount (Read-ServiceAccount) `
            -StartNow | Out-Null
    }
    exit 0
}

$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-AgentLog "task lastRun=$($info.LastRunTime) nextRun=$($info.NextRunTime) result=$($info.LastTaskResult) state=$($task.State)"

if ($task.State -eq "Disabled") {
    Enable-ScheduledTask -TaskName $TaskName | Out-Null
    Write-AgentLog "re-enabled disabled task"
}

Restart-HccAgentTask -Reason "restarting stale agent task"

if ($lastSuccess -and ((Get-Date).ToUniversalTime() - $lastSuccess) -gt [TimeSpan]::FromMinutes(10)) {
    Write-AgentLog "still stale after task restart; forcing one-shot heartbeat"
    if (Test-Path $AgentScript) {
        powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $AgentScript -Once
    }
}
