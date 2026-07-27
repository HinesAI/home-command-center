<#
.SYNOPSIS
  Idempotent HCC agent install for Group Policy computer startup.

.DESCRIPTION
  Intended to run as SYSTEM from:
    Computer Configuration -> Policies -> Windows Settings -> Scripts -> Startup

  Detects host type automatically:
    - domain controller  -> server bucket (hostRole windows-server)
    - member server      -> server bucket
    - workstation/client -> client bucket (hostRole windows-client)

  Prerequisites on the domain (one-time):
    - HCC tier groups + gMSA svc-hcc-agent created
    - gMSA allowed for target computers (recommend group HCC-Agent-Hosts + Domain Computers)
    - Host can reach HCC web/core URLs

.EXAMPLE
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\gp-install-hcc-agent.ps1
#>
[CmdletBinding()]
param(
    [string]$CoreBaseUrl = "http://192.168.4.237:18080",
    [string]$WebBaseUrl = "http://192.168.4.237:3000",
    [string]$RunAsAccount = "WEB-FLIP\svc-hcc-agent$",
    [string]$TaskName = "HCC-Agent",
    [string]$Interval = "120"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$logDir = Join-Path $env:ProgramData "HCC-Agent"
$logPath = Join-Path $logDir "gp-install.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Log {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $logPath -Value $line
    Write-Host $line
}

function Get-HccHostRole {
    $domainRole = (Get-CimInstance Win32_ComputerSystem).DomainRole
    if ($domainRole -in 4, 5) {
        return "dc"
    }
    if ($domainRole -in 2, 3) {
        return "member"
    }
    return "client"
}

function Invoke-Download {
    param(
        [string]$Url,
        [string]$Destination
    )
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
}

try {
    $permissionRole = Get-HccHostRole
    $nodeId = $env:COMPUTERNAME.ToLower()
    $agentId = "agent-$nodeId"
    $downloads = "$WebBaseUrl/downloads/ad"
    $workDir = Join-Path $env:ProgramData "HCC-Agent\gp-staging"
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null

    Write-Log "gp-install start on $nodeId (permissionRole=$permissionRole)"

    $hostScriptPath = Join-Path $workDir "setup-host-hcc-permissions.ps1"
    $configPath = Join-Path $workDir "config.web-flip.psd1"
    Invoke-Download "$downloads/setup-host-hcc-permissions.ps1" $hostScriptPath
    Invoke-Download "$downloads/config.web-flip.psd1" $configPath
    & $hostScriptPath -HostRole $permissionRole -ConfigPath $configPath
    Write-Log "host permissions applied"

    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        Write-Log "scheduled task '$TaskName' already present; skipping agent install"
        exit 0
    }

    $bootstrapPath = Join-Path $workDir "bootstrap-server-core.ps1"
    Invoke-Download "$WebBaseUrl/downloads/bootstrap-server-core.ps1" $bootstrapPath

    $config = Import-PowerShellDataFile -Path $configPath
    $services = switch ($permissionRole) {
        "dc" { $config.DcServices -join "," }
        "member" { $config.MemberServerServices -join "," }
        "client" { ($config.ClientServices -join ",") }
    }

    Write-Log "bootstrapping agent $agentId services='$services' runAs=$RunAsAccount"
    & $bootstrapPath `
        -NodeId $nodeId `
        -AgentId $agentId `
        -CoreBaseUrl $CoreBaseUrl `
        -PackageUrl "$WebBaseUrl/downloads/hcc-agent-windows.zip" `
        -Services $services `
        -Interval $Interval `
        -RunAsAccount $RunAsAccount

    Write-Log "gp-install complete"
    exit 0
} catch {
    Write-Log "gp-install failed: $($_.Exception.Message)"
    exit 1
}
