<#
.SYNOPSIS
  Run HCC AD identity phases from a single domain controller. Objects replicate to the whole domain.

.DESCRIPTION
  Recommended sequence on HINESDC1 (or any one DC):

    Phase 1 - Groups only:
      .\setup-ad-on-dc.ps1 -Phase Groups
      .\setup-ad-on-dc.ps1 -Phase WaitGroups

    Phase 2 - Service account (after groups have replicated):
      .\setup-ad-on-dc.ps1 -Phase ServiceAccount
      .\setup-ad-on-dc.ps1 -Phase WaitServiceAccount

    Phase 3 - Host permissions + agent (after gMSA has replicated):
      Run setup-host-hcc-permissions.ps1 on each host, then bootstrap agent with -RunAsAccount.

.EXAMPLE
  .\setup-ad-on-dc.ps1 -Phase Groups
  .\setup-ad-on-dc.ps1 -Phase WaitGroups
  .\setup-ad-on-dc.ps1 -Phase ServiceAccount
  .\setup-ad-on-dc.ps1 -Phase WaitServiceAccount
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Groups", "WaitGroups", "ServiceAccount", "WaitServiceAccount", "All")]
    [string]$Phase,

    [string]$ConfigPath = (Join-Path $PSScriptRoot "config.web-flip.psd1"),
    [string[]]$AllowedComputerNames = @("HINESDC1", "HINESDC2", "HINESDC3"),
    [switch]$SkipReplicationWait
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

function Invoke-LocalScript {
    param(
        [string]$Name,
        [hashtable]$ScriptParams = @{}
    )
    $path = Join-Path $here $Name
    if (-not (Test-Path $path)) {
        throw "Missing script: $path"
    }
    & $path @ScriptParams
}

function Run-GroupsPhase {
    $config = Import-PowerShellDataFile -Path $ConfigPath
    $hostname = $env:COMPUTERNAME
    if ($config.WriteDomainController -and ($hostname -ne $config.WriteDomainController)) {
        Write-Warning "You are on $hostname; config recommends writing AD objects on $($config.WriteDomainController)."
        Write-Warning "Continuing anyway - AD will replicate from whichever DC you use."
    }
    Invoke-LocalScript -Name "setup-ad-tier-groups.ps1" -ScriptParams @{ ConfigPath = $ConfigPath }
    if (-not $SkipReplicationWait) {
        Write-Host "`nTriggering inbound replication on peer DCs (best effort)..."
        foreach ($dc in @($config.DomainControllers)) {
            if ($dc -eq $hostname) { continue }
            repadmin /syncall $dc /A /e /d 2>$null | Out-Null
        }
    }
}

function Run-WaitGroupsPhase {
    if ($SkipReplicationWait) {
        Write-Host "SkipReplicationWait set; not polling DCs."
        return
    }
    Invoke-LocalScript -Name "wait-hcc-ad-replication.ps1" -ScriptParams @{
        Stage      = "Groups"
        ConfigPath = $ConfigPath
    }
}

function Run-ServiceAccountPhase {
    Invoke-LocalScript -Name "setup-ad-service-account.ps1" -ScriptParams @{
        ConfigPath             = $ConfigPath
        AllowedComputerNames   = $AllowedComputerNames
    }
    if (-not $SkipReplicationWait) {
        $config = Import-PowerShellDataFile -Path $ConfigPath
        $hostname = $env:COMPUTERNAME
        foreach ($dc in @($config.DomainControllers)) {
            if ($dc -eq $hostname) { continue }
            repadmin /syncall $dc /A /e /d 2>$null | Out-Null
        }
    }
}

function Run-WaitServiceAccountPhase {
    if ($SkipReplicationWait) {
        Write-Host "SkipReplicationWait set; not polling DCs."
        return
    }
    Invoke-LocalScript -Name "wait-hcc-ad-replication.ps1" -ScriptParams @{
        Stage      = "ServiceAccount"
        ConfigPath = $ConfigPath
    }
}

switch ($Phase) {
    "Groups"               { Run-GroupsPhase; break }
    "WaitGroups"           { Run-WaitGroupsPhase; break }
    "ServiceAccount"       { Run-ServiceAccountPhase; break }
    "WaitServiceAccount"   { Run-WaitServiceAccountPhase; break }
    "All" {
        Run-GroupsPhase
        Run-WaitGroupsPhase
        Run-ServiceAccountPhase
        Run-WaitServiceAccountPhase
        break
    }
}

Write-Host ""
Write-Host ("Phase {0} finished." -f $Phase)
