<#
.SYNOPSIS
  Waits until HCC AD objects have replicated to every domain controller.

.EXAMPLE
  .\wait-hcc-ad-replication.ps1 -Stage Groups
  .\wait-hcc-ad-replication.ps1 -Stage ServiceAccount -TimeoutMinutes 15
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Groups", "ServiceAccount")]
    [string]$Stage,

    [string]$ConfigPath = (Join-Path $PSScriptRoot "config.web-flip.psd1"),
    [string]$ServiceAccountName = "svc-hcc-agent",
    [int]$TimeoutMinutes = 10,
    [int]$PollSeconds = 15
)

$ErrorActionPreference = "Stop"
Import-Module ActiveDirectory -ErrorAction Stop

if (-not (Test-Path $ConfigPath)) {
    throw "Config not found: $ConfigPath"
}

$config = Import-PowerShellDataFile -Path $ConfigPath
$dcs = @($config.DomainControllers)
if (-not $dcs -or $dcs.Count -eq 0) {
    throw "DomainControllers is empty in config."
}

$groupNames = @($config.TierGroups | ForEach-Object { $_.Name })
$gmsaSamAccountName = if ($ServiceAccountName.EndsWith('$')) { $ServiceAccountName } else { "$ServiceAccountName$" }
$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$attempt = 0

function Test-DcHasGroups {
    param([string]$Server)
    foreach ($name in $groupNames) {
        $group = Get-ADGroup -Filter "SamAccountName -eq '$name'" -Server $Server -ErrorAction SilentlyContinue
        if (-not $group) {
            return $false
        }
    }
    return $true
}

function Test-DcHasServiceAccount {
    param([string]$Server)
    $account = Get-ADServiceAccount -Filter "SamAccountName -eq '$gmsaSamAccountName'" -Server $Server -ErrorAction SilentlyContinue
    if (-not $account) {
        return $false
    }
    $group = Get-ADGroup -Identity "HCC-Agent-ServiceAccounts" -Server $Server -ErrorAction SilentlyContinue
    if (-not $group) {
        return $false
    }
    $members = Get-ADGroupMember -Identity $group.DistinguishedName -Server $Server | Select-Object -ExpandProperty SamAccountName
    return ($gmsaSamAccountName -in $members)
}

Write-Host "Waiting for $Stage replication across: $($dcs -join ', ')"
Write-Host "Timeout: $TimeoutMinutes minutes (poll every $PollSeconds s)"

while ((Get-Date) -lt $deadline) {
    $attempt++
    $pending = @()
    foreach ($dc in $dcs) {
        $ok = if ($Stage -eq "Groups") { Test-DcHasGroups -Server $dc } else { Test-DcHasServiceAccount -Server $dc }
        if ($ok) {
            Write-Host "  [$dc] OK"
        } else {
            Write-Host "  [$dc] pending"
            $pending += $dc
        }
    }
    if ($pending.Count -eq 0) {
        Write-Host "`nReplication complete for $Stage on all $($dcs.Count) DCs (attempt $attempt)."
        return
    }
    Start-Sleep -Seconds $PollSeconds
}

throw "Timed out waiting for $Stage replication. Still pending on: $($pending -join ', ')"
