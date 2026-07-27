function New-HccAgentTaskAction {
    param(
        [string]$AgentScript,
        [string]$WorkingDirectory,
        [switch]$Once
    )
    $arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$AgentScript`""
    if ($Once) {
        $arguments += " -Once"
    }
    return New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument $arguments `
        -WorkingDirectory $WorkingDirectory
}

function New-HccDaemonTaskSettings {
    return New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
        -MultipleInstances IgnoreNew
}

function New-HccWatchdogTaskSettings {
    return New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
        -MultipleInstances IgnoreNew
}

function New-HccRepeatingOnceTrigger {
    param(
        [TimeSpan]$Interval,
        [datetime]$StartAt = (Get-Date).AddMinutes(-5)
    )
    # Copy the Repetition object from a fully constructed trigger. Setting
    # Repetition.Interval directly fails on several Server 2019/2022/2025 builds.
    $seed = New-ScheduledTaskTrigger -Once -At $StartAt `
        -RepetitionInterval $Interval `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $trigger = New-ScheduledTaskTrigger -Once -At $StartAt
    $trigger.Repetition = $seed.Repetition
    return $trigger
}

function Get-HccTaskPrincipal {
    param(
        [string]$TaskName,
        [string]$RunAsAccount = ""
    )

    if ($RunAsAccount) {
        return New-ScheduledTaskPrincipal -UserId $RunAsAccount -LogonType ServiceAccount -RunLevel Limited
    }

    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing -and $existing.Principal -and $existing.Principal.UserId) {
        return $existing.Principal
    }

    return New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
}

function Register-HccAgentScheduledTask {
    param(
        [string]$TaskName = "HCC-Agent",
        [string]$AgentScript = (Join-Path $env:ProgramFiles "HCC-Agent\heartbeat_sender.ps1"),
        [int]$IntervalSeconds = 120,
        [string]$RunAsAccount = "",
        [switch]$StartNow,
        [switch]$LegacyOnceMode
    )

    if (-not (Test-Path $AgentScript)) {
        throw "Agent script not found: $AgentScript"
    }

    $installDir = Split-Path $AgentScript -Parent
    $principal = Get-HccTaskPrincipal -TaskName $TaskName -RunAsAccount $RunAsAccount

    if ($LegacyOnceMode) {
        $action = New-HccAgentTaskAction -AgentScript $AgentScript -WorkingDirectory $installDir -Once
        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -RestartCount 5 `
            -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
            -MultipleInstances Parallel
        $startupTrigger = New-ScheduledTaskTrigger -AtStartup
        $repeatTrigger = New-HccRepeatingOnceTrigger -Interval (New-TimeSpan -Seconds ([Math]::Max(60, $IntervalSeconds)))
        $triggers = @($startupTrigger, $repeatTrigger)
    } else {
        # Daemon mode: one long-running agent loop (matches Linux systemd agent).
        $action = New-HccAgentTaskAction -AgentScript $AgentScript -WorkingDirectory $installDir
        $settings = New-HccDaemonTaskSettings
        $triggers = @(
            (New-ScheduledTaskTrigger -AtStartup),
            (New-ScheduledTaskTrigger -At (Get-Date).AddMinutes(1) -Once)
        )
    }

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null

    if ($StartNow) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($LegacyOnceMode) {
            powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $AgentScript -Once
        } else {
            # Kick an immediate heartbeat while the daemon task starts under the service account.
            Start-Process -FilePath "powershell.exe" `
                -ArgumentList "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$AgentScript`" -Once" `
                -WindowStyle Hidden `
                -ErrorAction SilentlyContinue | Out-Null
        }
    }
}

function Register-HccAgentWatchdogTask {
    param(
        [string]$WatchdogScript = (Join-Path $env:ProgramFiles "HCC-Agent\watchdog-hcc-agent.ps1"),
        [string]$RunAsAccount = "",
        [int]$IntervalMinutes = 5
    )

    if (-not (Test-Path $WatchdogScript)) {
        Write-Host "Watchdog script not found, skipping: $WatchdogScript"
        return
    }

    $taskName = "HCC-Agent-Watchdog"
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$WatchdogScript`"" `
        -WorkingDirectory (Split-Path $WatchdogScript -Parent)
    $settings = New-HccWatchdogTaskSettings
    $startupTrigger = New-ScheduledTaskTrigger -AtStartup
    $repeatTrigger = New-HccRepeatingOnceTrigger -Interval (New-TimeSpan -Minutes ([Math]::Max(5, $IntervalMinutes)))
    $principal = Get-HccTaskPrincipal -TaskName $taskName -RunAsAccount $RunAsAccount

    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger @($startupTrigger, $repeatTrigger) `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
}
