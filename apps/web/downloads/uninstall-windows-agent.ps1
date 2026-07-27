param(
    [switch]$SkipTempCleanup
)

$ErrorActionPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ServiceName = "HCC-Agent"
$TaskName = "HCC-Agent"
$WatchdogTaskName = "HCC-Agent-Watchdog"
$InstallDir = Join-Path $env:ProgramFiles "HCC-Agent"
$ConfigDir = Join-Path $env:ProgramData "HCC-Agent"
$TempPatterns = @(
    (Join-Path $env:TEMP "hcc-agent-install"),
    (Join-Path $env:TEMP "hcc-bootstrap.ps1"),
    (Join-Path $env:TEMP "hcc-diagnose.ps1"),
    "C:\Windows\Temp\hcc-agent"
)

function Require-Admin {
    $current = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $current.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this uninstaller from an elevated PowerShell session."
    }
}

function Remove-HccAgent {
    Write-Host "Removing existing HCC agent, if present..."

    $wrapper = Join-Path $InstallDir "HCC-Agent.exe"
    if (Test-Path $wrapper) {
        Write-Host "Stopping WinSW service wrapper..."
        & $wrapper stop 2>&1 | Out-Null
        Start-Sleep -Seconds 2
        Write-Host "Uninstalling WinSW service wrapper..."
        & $wrapper uninstall 2>&1 | Out-Null
        Write-Host "Removed WinSW service wrapper"
    }

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service) {
        Write-Host "Stopping Windows service: $ServiceName"
        if ($service.Status -eq "Running") {
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
        sc.exe delete $ServiceName | Out-Null
        Write-Host "Removed Windows service: $ServiceName"
    }

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "Removing scheduled task: $TaskName"
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed scheduled task: $TaskName"
    }

    $watchdog = Get-ScheduledTask -TaskName $WatchdogTaskName -ErrorAction SilentlyContinue
    if ($watchdog) {
        Write-Host "Removing scheduled task: $WatchdogTaskName"
        Stop-ScheduledTask -TaskName $WatchdogTaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $WatchdogTaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed scheduled task: $WatchdogTaskName"
    }

    $agentScript = Join-Path $InstallDir "heartbeat_sender.ps1"
    $shouldStopWorkers = (Test-Path $agentScript) -or $service
    if ($shouldStopWorkers) {
        Write-Host "Stopping leftover HCC agent worker processes..."
        foreach ($procName in @("powershell.exe", "python.exe", "pythonw.exe")) {
            $procs = @(Get-CimInstance Win32_Process -Filter "Name='$procName'" -ErrorAction SilentlyContinue)
            foreach ($proc in $procs) {
                $cmd = $proc.CommandLine
                if ($cmd -and ($cmd -like "*heartbeat_sender*" -or $cmd -like "*\HCC-Agent\*")) {
                    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
                }
            }
        }
    } else {
        Write-Host "No agent worker processes to stop"
    }

    if (Test-Path $InstallDir) {
        Remove-Item -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Removed install dir: $InstallDir"
    }

    if (Test-Path $ConfigDir) {
        Remove-Item -Path $ConfigDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Removed config dir: $ConfigDir"
    }

    if (-not $SkipTempCleanup) {
        foreach ($path in $TempPatterns) {
            if (Test-Path $path) {
                Remove-Item -Path $path -Recurse -Force -ErrorAction SilentlyContinue
                Write-Host "Removed temp path: $path"
            }
        }
    }

    Write-Host "HCC agent uninstall complete."
}

Require-Admin
Remove-HccAgent
