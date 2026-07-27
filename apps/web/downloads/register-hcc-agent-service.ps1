$Script:HccWinSwUrl = "http://192.168.4.237:3000/downloads/WinSW-x64.exe"

function Get-HccAgentWrapperPath {
    param([string]$InstallDir = (Join-Path $env:ProgramFiles "HCC-Agent"))
    return Join-Path $InstallDir "HCC-Agent.exe"
}

function Get-HccAgentWrapperConfigPath {
    param([string]$InstallDir = (Join-Path $env:ProgramFiles "HCC-Agent"))
    return Join-Path $InstallDir "HCC-Agent.xml"
}

function Ensure-HccAgentWrapper {
    param(
        [string]$InstallDir = (Join-Path $env:ProgramFiles "HCC-Agent"),
        [string]$SourceDir = ""
    )
    $wrapperPath = Get-HccAgentWrapperPath -InstallDir $InstallDir
    if (Test-Path $wrapperPath) {
        return $wrapperPath
    }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $candidates = @()
    if ($SourceDir) {
        $candidates += (Join-Path $SourceDir "WinSW-x64.exe")
        $candidates += (Join-Path $SourceDir "HCC-Agent.exe")
    }
    $candidates += (Join-Path $InstallDir "WinSW-x64.exe")

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            Copy-Item -Path $candidate -Destination $wrapperPath -Force
            return $wrapperPath
        }
    }

    $tempZip = Join-Path $env:TEMP "WinSW-x64.exe"
    Write-Host "Downloading WinSW service wrapper from $Script:HccWinSwUrl"
    Invoke-WebRequest -Uri $Script:HccWinSwUrl -OutFile $tempZip -UseBasicParsing
    Copy-Item -Path $tempZip -Destination $wrapperPath -Force
    return $wrapperPath
}

function Grant-ServiceLogonRight {
    param(
        [Parameter(Mandatory = $true)][string]$Account
    )
    $export = Join-Path $env:TEMP "hcc-secedit-export-svc.cfg"
    $db = Join-Path $env:TEMP "hcc-secedit-svc.sdb"
    $inf = Join-Path $env:TEMP "hcc-secedit-svc.inf"

    secedit /export /cfg $export /quiet | Out-Null
    if (-not (Test-Path $export)) {
        Write-Host "Note: could not export secedit policy for SeServiceLogonRight"
        return
    }

    $lines = Get-Content $export
    $updated = @()
    $found = $false
    foreach ($line in $lines) {
        if ($line -match '^SeServiceLogonRight\s*=') {
            $found = $true
            if ($line -match [regex]::Escape($Account)) {
                Write-Host "SeServiceLogonRight already includes $Account"
                return
            }
            if ($line -match 'SeServiceLogonRight\s*=\s*$') {
                $updated += "SeServiceLogonRight = $Account"
            } else {
                $updated += ($line.TrimEnd() + ",$Account")
            }
        } else {
            $updated += $line
        }
    }
    if (-not $found) {
        Write-Host "Note: SeServiceLogonRight not found in local security policy export"
        return
    }
    Set-Content -Path $inf -Value $updated -Encoding Unicode
    secedit /configure /db $db /cfg $inf /areas USER_RIGHTS /quiet | Out-Null
    Write-Host "Granted SeServiceLogonRight to $Account"
}

function Import-ActiveDirectoryModule {
    if (Get-Module -Name ActiveDirectory -ErrorAction SilentlyContinue) {
        return
    }
    if (Get-Module -ListAvailable -Name ActiveDirectory) {
        Import-Module ActiveDirectory -ErrorAction Stop
        return
    }
    throw @"
ActiveDirectory PowerShell module is not available on this host.
DCs include it by default. Member servers do not - do not install RSAT as part of agent setup.
Either run the agent as LocalSystem (default on member servers), or pre-install the gMSA on this host from a machine with the AD module:
  Install-ADServiceAccount -Identity svc-hcc-agent
"@
}

function Install-HccGmsaOnHost {
    param(
        [Parameter(Mandatory = $true)][string]$RunAsAccount
    )

    Import-ActiveDirectoryModule

    $sam = $RunAsAccount.Split("\")[-1]
    if (-not $sam.EndsWith("$")) {
        throw "Expected gMSA account name to end with `$ (got $RunAsAccount)"
    }
    $sam = $sam.TrimEnd("$")

    try {
        $installed = Test-ADServiceAccount -Identity $sam -IsInstalled -ErrorAction Stop
    } catch {
        $installed = $false
    }

    if (-not $installed) {
        Install-ADServiceAccount -Identity $sam -ErrorAction Stop
        Write-Host "Installed gMSA on this host: $sam"
    } else {
        Write-Host "gMSA already installed on this host: $sam"
    }

    if (-not (Test-ADServiceAccount -Identity $sam -IsInstalled)) {
        throw "gMSA $sam is not installed on $($env:COMPUTERNAME). Add $($env:COMPUTERNAME)`$ to PrincipalsAllowedToRetrieveManagedPassword on the gMSA object (run from a DC)."
    }
}

function Resolve-HccRunAsAccount {
    param([string]$RunAsAccount)

    if (-not $RunAsAccount) {
        return ""
    }

    if ($RunAsAccount -notlike "*`$") {
        Grant-ServiceLogonRight -Account $RunAsAccount
        return $RunAsAccount
    }

    Install-HccGmsaOnHost -RunAsAccount $RunAsAccount
    Grant-ServiceLogonRight -Account $RunAsAccount
    return $RunAsAccount
}

function Install-HccAgentServiceAccount {
    param([string]$RunAsAccount)
    $null = Resolve-HccRunAsAccount -RunAsAccount $RunAsAccount
}

function New-HccAgentWinSwXml {
    param(
        [string]$AgentScript,
        [string]$InstallDir,
        [string]$ConfigDir,
        [string]$RunAsAccount = ""
    )
    $powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$AgentScript`""
    $logDir = Join-Path $ConfigDir "logs"

    $xml = @"
<service>
  <id>HCC-Agent</id>
  <name>HCCv2 Agent</name>
  <description>HCCv2 heartbeat and inventory agent</description>
  <executable>$powershell</executable>
  <arguments>$arguments</arguments>
  <workingdirectory>$InstallDir</workingdirectory>
  <logpath>$logDir</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>5</keepFiles>
  </log>
  <onfailure action="restart" delay="60 sec"/>
  <onfailure action="restart" delay="60 sec"/>
  <onfailure action="restart" delay="120 sec"/>
"@

    if ($RunAsAccount) {
        $domain = "."
        $user = $RunAsAccount
        if ($RunAsAccount -match '^(.+)\\(.+)$') {
            $domain = $Matches[1]
            $user = $Matches[2]
        }
        $xml += @"

  <serviceaccount>
    <domain>$domain</domain>
    <user>$user</user>
    <allowservicelogon>true</allowservicelogon>
  </serviceaccount>
"@
    }

    $xml += "`n</service>`n"
    return $xml
}

function Remove-HccAgentLegacyTasks {
    foreach ($taskName in @("HCC-Agent", "HCC-Agent-Watchdog")) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if (-not $task) { continue }
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed legacy scheduled task: $taskName"
    }
}

function Unregister-HccAgentService {
    param(
        [string]$ServiceName = "HCC-Agent",
        [string]$InstallDir = (Join-Path $env:ProgramFiles "HCC-Agent")
    )

    $wrapper = Get-HccAgentWrapperPath -InstallDir $InstallDir
    if (Test-Path $wrapper) {
        & $wrapper stop 2>&1 | Out-Null
        Start-Sleep -Seconds 2
        & $wrapper uninstall 2>&1 | Out-Null
        Start-Sleep -Seconds 1
        Write-Host "Removed WinSW service: $ServiceName"
    }

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service) {
        if ($service.Status -eq "Running") {
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
        sc.exe delete $ServiceName | Out-Null
        Write-Host "Removed legacy Windows service registration: $ServiceName"
    }
}

function Register-HccAgentService {
    param(
        [string]$ServiceName = "HCC-Agent",
        [string]$AgentScript = (Join-Path $env:ProgramFiles "HCC-Agent\heartbeat_sender.ps1"),
        [string]$InstallDir = (Join-Path $env:ProgramFiles "HCC-Agent"),
        [string]$ConfigDir = (Join-Path $env:ProgramData "HCC-Agent"),
        [string]$SourceDir = "",
        [string]$RunAsAccount = "",
        [switch]$StartNow
    )

    if (-not (Test-Path $AgentScript)) {
        throw "Agent script not found: $AgentScript"
    }

    $wrapper = Get-HccAgentWrapperPath -InstallDir $InstallDir
    $serviceExists = (Test-Path $wrapper) -or (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)
    if ($serviceExists) {
        Write-Host "HCC-Agent service already registered; skipping uninstall/reinstall"
        if ($StartNow) {
            Restart-HccAgentServiceDetached -ServiceName $ServiceName -InstallDir $InstallDir
        }
        return $RunAsAccount
    }

    Unregister-HccAgentService -ServiceName $ServiceName -InstallDir $InstallDir
    New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $ConfigDir "logs") | Out-Null

    $effectiveRunAs = Resolve-HccRunAsAccount -RunAsAccount $RunAsAccount

    $wrapper = Ensure-HccAgentWrapper -InstallDir $InstallDir -SourceDir $SourceDir
    $configPath = Get-HccAgentWrapperConfigPath -InstallDir $InstallDir
    $xml = New-HccAgentWinSwXml -AgentScript $AgentScript -InstallDir $InstallDir -ConfigDir $ConfigDir -RunAsAccount $effectiveRunAs
    Set-Content -Path $configPath -Value $xml -Encoding UTF8

    $installOut = & $wrapper install 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -and $installOut -notmatch "already exists") {
        throw "WinSW install failed: $($installOut.Trim())"
    }

    $accountLabel = if ($effectiveRunAs) { $effectiveRunAs } else { "LocalSystem" }
    Write-Host "Registered Windows service via WinSW: $ServiceName (account: $accountLabel)"

    if ($StartNow) {
        Start-HccAgentService -ServiceName $ServiceName -InstallDir $InstallDir
    }

    return $effectiveRunAs
}

function Start-HccAgentService {
    param(
        [string]$ServiceName = "HCC-Agent",
        [string]$InstallDir = (Join-Path $env:ProgramFiles "HCC-Agent")
    )
    $wrapper = Get-HccAgentWrapperPath -InstallDir $InstallDir
    if (Test-Path $wrapper) {
        Start-Sleep -Seconds 2
        $startOut = & $wrapper start 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -and $startOut -notmatch "already been started|RUNNING") {
            $logDir = Join-Path $env:ProgramData "HCC-Agent\logs"
            $hint = @(
                "Check $logDir and Windows Event Viewer (Application log, source HCC-Agent).",
                "For gMSA on member servers: add $($env:COMPUTERNAME)`$ to PrincipalsAllowedToRetrieveManagedPassword, then run Install-ADServiceAccount from a host with the AD module before setup."
            ) -join " "
            throw "WinSW start failed: $($startOut.Trim()) $hint"
        }
        return
    }

    Start-Service -Name $ServiceName -ErrorAction Stop
}

function Stop-HccAgentService {
    param(
        [string]$ServiceName = "HCC-Agent",
        [string]$InstallDir = (Join-Path $env:ProgramFiles "HCC-Agent")
    )
    $wrapper = Get-HccAgentWrapperPath -InstallDir $InstallDir
    if (Test-Path $wrapper) {
        & $wrapper stop 2>&1 | Out-Null
        Start-Sleep -Seconds 2
        return
    }
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service -and $service.Status -eq "Running") {
        Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}

function Restart-HccAgentServiceDetached {
    param(
        [string]$ServiceName = "HCC-Agent",
        [string]$InstallDir = (Join-Path $env:ProgramFiles "HCC-Agent")
    )
    $wrapper = Get-HccAgentWrapperPath -InstallDir $InstallDir
    if (Test-Path $wrapper) {
        $command = "& { Start-Sleep -Seconds 2; & '$wrapper' stop; Start-Sleep -Seconds 3; & '$wrapper' start }"
    } else {
        $command = "& { Start-Sleep -Seconds 2; Stop-Service -Name '$ServiceName' -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 3; Start-Service -Name '$ServiceName' -ErrorAction SilentlyContinue }"
    }
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", $command `
        -WindowStyle Hidden `
        -ErrorAction SilentlyContinue | Out-Null
}
