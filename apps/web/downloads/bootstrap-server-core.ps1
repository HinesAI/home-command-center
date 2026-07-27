param(
    [Parameter(Mandatory = $true)][string]$NodeId,
    [Parameter(Mandatory = $true)][string]$AgentId,
    [string]$CoreBaseUrl = "http://192.168.4.237:18080",
    [string]$PackageUrl = "http://192.168.4.237:3000/downloads/hcc-agent-windows.zip",
    [string]$Services = "NTDS,DNS,DHCP,KDC,Netlogon,W32Time,WinRM,W3SVC,Spooler",
    [string]$StorageDrives = "C",
    [string]$Interval = "120",
    [string]$RunAsAccount = ""
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this bootstrap from an elevated PowerShell session."
}

$workDir = Join-Path $env:TEMP "hcc-agent-install"
$zipPath = Join-Path $workDir "hcc-agent-windows.zip"

if (Test-Path $workDir) {
    Remove-Item -Path $workDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

Write-Host "Downloading $PackageUrl"
Invoke-WebRequest -Uri $PackageUrl -OutFile $zipPath -UseBasicParsing
Expand-Archive -Path $zipPath -DestinationPath $workDir -Force

$installer = Join-Path $workDir "install-windows-agent.ps1"
if (-not (Test-Path $installer)) {
    throw "Installer not found in package: $installer"
}

& $installer `
    -CoreBaseUrl $CoreBaseUrl `
    -NodeId $NodeId `
    -AgentId $AgentId `
    -Interval $Interval `
    -Services $Services `
    -StorageDrives $StorageDrives `
    -RunAsAccount $RunAsAccount

Remove-Item -Path $workDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Bootstrap complete for $NodeId"
