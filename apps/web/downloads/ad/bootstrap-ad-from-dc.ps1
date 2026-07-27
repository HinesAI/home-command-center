<#
.SYNOPSIS
  Download HCC AD scripts to a DC and run one rollout phase.

.EXAMPLE
  # On HINESDC1 (elevated):
  Set-ExecutionPolicy Bypass -Scope Process -Force
  iex (iwr -UseBasicParsing http://192.168.4.237:3000/downloads/ad/bootstrap-ad-from-dc.ps1).Content

  .\bootstrap-ad-from-dc.ps1 -Phase Groups
  .\bootstrap-ad-from-dc.ps1 -Phase WaitGroups
  .\bootstrap-ad-from-dc.ps1 -Phase ServiceAccount
  .\bootstrap-ad-from-dc.ps1 -Phase WaitServiceAccount
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Groups", "WaitGroups", "ServiceAccount", "WaitServiceAccount")]
    [string]$Phase,

    [string]$BaseUrl = "http://192.168.4.237:3000/downloads/ad",
    [string]$WorkDir = "C:\Windows\Temp\hcc-ad",
    [string[]]$AllowedComputerNames = @("HINESDC1", "HINESDC2", "HINESDC3")
)

$ErrorActionPreference = "Stop"
$files = @(
    "config.web-flip.psd1",
    "setup-ad-tier-groups.ps1",
    "setup-ad-service-account.ps1",
    "setup-ad-on-dc.ps1",
    "wait-hcc-ad-replication.ps1"
)

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
foreach ($file in $files) {
    $dest = Join-Path $WorkDir $file
    Invoke-WebRequest -Uri "$BaseUrl/$file" -OutFile $dest -UseBasicParsing
}

$configPath = Join-Path $WorkDir "config.web-flip.psd1"
& (Join-Path $WorkDir "setup-ad-on-dc.ps1") -Phase $Phase -ConfigPath $configPath -AllowedComputerNames $AllowedComputerNames
