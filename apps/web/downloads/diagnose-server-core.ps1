param(
    [string]$CoreBaseUrl = "http://192.168.1.10:18080"
)

$ErrorActionPreference = "Continue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Write-Host "=== HCC Agent Diagnostics ==="
Write-Host "Computer: $env:COMPUTERNAME"

Write-Host "`n[1] Core connectivity"
try {
    $resp = Invoke-WebRequest -Uri "$CoreBaseUrl/api/v1/fleet/overview" -UseBasicParsing -TimeoutSec 8
    Write-Host "OK: core responded HTTP $($resp.StatusCode)"
}
catch {
    Write-Host "FAIL: cannot reach core at $CoreBaseUrl"
    Write-Host $_.Exception.Message
}

Write-Host "`n[2] Package download"
try {
    $test = Invoke-WebRequest -Uri "http://192.168.1.10:3000/downloads/bootstrap-server-core.ps1" -UseBasicParsing -TimeoutSec 8
    Write-Host "OK: bootstrap script reachable ($($test.RawContentLength) bytes)"
}
catch {
    Write-Host "FAIL: cannot download bootstrap from HCC web server"
    Write-Host $_.Exception.Message
}

Write-Host "`n[3] Install paths"
$installDir = Join-Path $env:ProgramFiles "HCC-Agent"
$configPath = Join-Path $env:ProgramData "HCC-Agent\hcc-agent.env"
$logPath = Join-Path $env:ProgramData "HCC-Agent\agent.log"
Write-Host "Install dir exists: $(Test-Path $installDir) -> $installDir"
Write-Host "Env file exists: $(Test-Path $configPath) -> $configPath"
Write-Host "Log file exists: $(Test-Path $logPath) -> $logPath"
if (Test-Path $configPath) {
    Write-Host "--- hcc-agent.env ---"
    Get-Content $configPath
}

Write-Host "`n[4] Windows service"
$svc = Get-Service -Name "HCC-Agent" -ErrorAction SilentlyContinue
if ($svc) {
    $svc | Format-List Name, Status, StartType
    $svcCfg = sc.exe qc HCC-Agent 2>&1 | Out-String
    Write-Host $svcCfg
} else {
    Write-Host "FAIL: HCC-Agent Windows service not found"
}

Write-Host "`n[5] Legacy scheduled tasks"
foreach ($taskName in @("HCC-Agent", "HCC-Agent-Watchdog")) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "FOUND legacy task: $taskName state=$($task.State)"
        Get-ScheduledTask -TaskName $taskName | Get-ScheduledTaskInfo | Format-List
    }
}
if (-not (Get-ScheduledTask -TaskName "HCC-Agent" -ErrorAction SilentlyContinue)) {
    Write-Host "No legacy HCC-Agent scheduled task (expected for v1.0.5+)"
}

Write-Host "`n[6] Agent script"
$agentScript = Join-Path $installDir "heartbeat_sender.ps1"
Write-Host "PowerShell agent exists: $(Test-Path $agentScript) -> $agentScript"

Write-Host "`n[6] Recent agent log"
if (Test-Path $logPath) {
    Get-Content $logPath -Tail 20
}
else {
    Write-Host "No agent log yet."
}

Write-Host "`n[7] Manual heartbeat (foreground)"
if (Test-Path $agentScript) {
    Write-Host "Running one heartbeat cycle..."
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $agentScript -Once
}
else {
    Write-Host "Skip: PowerShell agent not installed."
}

Write-Host "`nDone."
