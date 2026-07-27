<#
.SYNOPSIS
  Same as setup-hcc-agent.ps1 (kept for old bookmarks).
#>
param(
    [string]$CoreBaseUrl = "http://192.168.4.237:18080",
    [string]$WebBaseUrl = "http://192.168.4.237:3000",
    [string]$RunAsAccount = "WEB-FLIP\svc-hcc-agent$"
)

$setupUrl = "$WebBaseUrl/downloads/setup-hcc-agent.ps1"
$setupPath = Join-Path $env:TEMP "setup-hcc-agent.ps1"
Invoke-WebRequest -Uri $setupUrl -OutFile $setupPath -UseBasicParsing
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setupPath `
    -CoreBaseUrl $CoreBaseUrl `
    -WebBaseUrl $WebBaseUrl `
    -RunAsAccount $RunAsAccount
