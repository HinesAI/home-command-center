<#
.SYNOPSIS
  Same as setup-hcc-agent.ps1 (kept for old bookmarks).
#>
param(
    [string]$CoreBaseUrl = "http://192.168.1.10:18080",
    [string]$WebBaseUrl = "http://192.168.1.10:3000",
    [string]$RunAsAccount = "EXAMPLE\svc-hcc-agent$"
)

$setupUrl = "$WebBaseUrl/downloads/setup-hcc-agent.ps1"
$setupPath = Join-Path $env:TEMP "setup-hcc-agent.ps1"
Invoke-WebRequest -Uri $setupUrl -OutFile $setupPath -UseBasicParsing
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setupPath `
    -CoreBaseUrl $CoreBaseUrl `
    -WebBaseUrl $WebBaseUrl `
    -RunAsAccount $RunAsAccount
