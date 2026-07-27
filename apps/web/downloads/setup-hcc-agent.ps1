<#
.SYNOPSIS
  Install the HCC Windows agent.

.EXAMPLE
  Invoke-WebRequest http://192.168.4.237:3000/downloads/setup-hcc-agent.ps1 -OutFile $env:TEMP\setup-hcc-agent.ps1 -UseBasicParsing
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\setup-hcc-agent.ps1

.EXAMPLE
  # DC install (gMSA is selected automatically on domain controllers):
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\setup-hcc-agent.ps1

.EXAMPLE
  # Member server / workstation (LocalSystem by default):
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\setup-hcc-agent.ps1

.EXAMPLE
  # Member server with gMSA (host must already be allowed on the gMSA object):
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\setup-hcc-agent.ps1 -RunAsAccount "WEB-FLIP\svc-hcc-agent$"
#>
param(
    [string]$NodeId = "",
    [string]$AgentId = "",
    [string]$CoreBaseUrl = "http://192.168.4.237:18080",
    [string]$WebBaseUrl = "http://192.168.4.237:3000",
    [string]$RunAsAccount = "AUTO",
    [string]$Interval = "120",
    [string]$Services = "",
    [string]$StorageDrives = ""
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run from an elevated PowerShell session."
}

if (-not $NodeId) { $NodeId = $env:COMPUTERNAME.ToLower() }
if (-not $AgentId) { $AgentId = "agent-$NodeId" }

$domainRole = (Get-CimInstance Win32_ComputerSystem).DomainRole
if ($RunAsAccount -eq "AUTO") {
    if ($domainRole -in 4, 5) {
        $RunAsAccount = "WEB-FLIP\svc-hcc-agent$"
    } else {
        $RunAsAccount = ""
    }
}

if (-not $Services) {
    if ($domainRole -in 4, 5) {
        $Services = "NTDS,DNS,DHCP,KDC,Netlogon,W32Time,WinRM,W3SVC,Spooler"
    } elseif ($domainRole -in 2, 3) {
        $Services = "WinRM,W3SVC,Spooler,W32Time"
    } else {
        $Services = "WinRM,Spooler"
    }
}

if (-not $StorageDrives) {
    $letters = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
        ForEach-Object { $_.DeviceID.Replace(":", "").ToUpper() } |
        Where-Object { $_ } |
        Select-Object -Unique
    $StorageDrives = if ($letters) { ($letters -join ",") } else { "C" }
}

Write-Host "HCC agent install (build 2026-07-05d)"
Write-Host "  host:    $env:COMPUTERNAME"
Write-Host "  node:    $NodeId"
Write-Host "  agent:   $AgentId"
Write-Host "  core:    $CoreBaseUrl"
Write-Host "  run as:  $(if ($RunAsAccount) { $RunAsAccount } else { 'LocalSystem' })"

$workDir = Join-Path $env:TEMP "hcc-agent-install"
$zipPath = Join-Path $workDir "hcc-agent-windows.zip"
$packageUrl = "$WebBaseUrl/downloads/hcc-agent-windows.zip"

if (Test-Path $workDir) {
    Remove-Item -Path $workDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

Write-Host "Downloading package..."
Invoke-WebRequest -Uri $packageUrl -OutFile $zipPath -UseBasicParsing
Expand-Archive -Path $zipPath -DestinationPath $workDir -Force

$installer = Join-Path $workDir "install-windows-agent.ps1"
if (-not (Test-Path $installer)) {
    throw "Installer missing from package: $installer"
}

Write-Host "Installing..."
& $installer `
    -CoreBaseUrl $CoreBaseUrl `
    -NodeId $NodeId `
    -AgentId $AgentId `
    -Interval $Interval `
    -Services $Services `
    -StorageDrives $StorageDrives `
    -RunAsAccount $RunAsAccount

Remove-Item -Path $workDir -Recurse -Force -ErrorAction SilentlyContinue

$svc = Get-Service -Name "HCC-Agent" -ErrorAction SilentlyContinue
if (-not $svc) {
    throw "HCC-Agent service was not created."
}

Write-Host ""
Write-Host "Install complete."
$svc | Format-List Name, Status, StartType

if ($svc.Status -eq "Running") {
    $runAsLabel = if ($RunAsAccount) { $RunAsAccount } else { "LocalSystem" }
    Write-Host "SUCCESS: agent is running as $runAsLabel."
    if (-not $RunAsAccount) {
        Write-Host "Member servers use LocalSystem by default. gMSA is only for domain controllers."
    }
} else {
    Write-Host "WARNING: service exists but status is $($svc.Status). Check C:\ProgramData\HCC-Agent\logs\"
}
