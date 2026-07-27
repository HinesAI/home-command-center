param(
    [Parameter(Mandatory = $true)][string]$CoreBaseUrl,
    [Parameter(Mandatory = $true)][string]$NodeId,
    [Parameter(Mandatory = $true)][string]$AgentId,
    [string]$Interval = "120",
    [string]$Services = "NTDS,DNS,DHCP,KDC,Netlogon,W32Time,WinRM,W3SVC,Spooler",
    [string]$StorageDrives = "C",
    [string]$RunAsAccount = ""
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this installer from an elevated PowerShell session."
}

function Set-HccDirectoryAcl {
    param(
        [string]$Path,
        [string]$Account
    )
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
    icacls $Path /grant "${Account}:(OI)(CI)M" /Q | Out-Null
    icacls $Path /grant "Administrators:(OI)(CI)F" /Q | Out-Null
    icacls $Path /grant "SYSTEM:(OI)(CI)F" /Q | Out-Null
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Join-Path $env:ProgramFiles "HCC-Agent"
$ConfigDir = Join-Path $env:ProgramData "HCC-Agent"
$EnvPath = Join-Path $ConfigDir "hcc-agent.env"
$ServiceName = "HCC-Agent"
$AgentScript = Join-Path $InstallDir "heartbeat_sender.ps1"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null

Copy-Item -Path (Join-Path $ScriptDir "heartbeat_sender.ps1") -Destination $InstallDir -Force
Copy-Item -Path (Join-Path $ScriptDir "register-hcc-agent-service.ps1") -Destination $InstallDir -Force
if (Test-Path (Join-Path $ScriptDir "diagnose-server-core.ps1")) {
    Copy-Item -Path (Join-Path $ScriptDir "diagnose-server-core.ps1") -Destination $InstallDir -Force
}

$envLines = @(
    "HCC_CORE_BASE_URL=$CoreBaseUrl"
    "HCC_AGENT_NODE_ID=$NodeId"
    "HCC_AGENT_ID=$AgentId"
    "HCC_AGENT_VERSION=1.0.6"
    "HCC_AGENT_INTERVAL_SECONDS=$Interval"
    "HCC_SERVICES=$Services"
    "HCC_STORAGE_DRIVES=$StorageDrives"
)
Set-Content -Path $EnvPath -Value $envLines -Encoding ASCII

if ($RunAsAccount) {
    Set-HccDirectoryAcl -Path $InstallDir -Account $RunAsAccount
    Set-HccDirectoryAcl -Path $ConfigDir -Account $RunAsAccount
}

. (Join-Path $ScriptDir "register-hcc-agent-service.ps1")
$effectiveRunAs = Register-HccAgentService `
    -ServiceName $ServiceName `
    -AgentScript $AgentScript `
    -InstallDir $InstallDir `
    -ConfigDir $ConfigDir `
    -SourceDir $ScriptDir `
    -RunAsAccount $RunAsAccount `
    -StartNow

if ($effectiveRunAs) {
    $envLines += ('HCC_SERVICE_ACCOUNT=' + $effectiveRunAs)
    Set-Content -Path $EnvPath -Value $envLines -Encoding ASCII
}

Write-Host "Agent files: $InstallDir"
Write-Host "Config:      $EnvPath"
Write-Host "Service:     $ServiceName (run as: $(if ($effectiveRunAs) { $effectiveRunAs } else { 'LocalSystem' }))"
