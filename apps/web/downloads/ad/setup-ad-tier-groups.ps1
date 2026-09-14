<#
.SYNOPSIS
  Creates HCC tier groups in Active Directory (run on a DC or RSAT admin workstation).

.DESCRIPTION
  Step 1 of agent identity rollout (single-DC write, domain replication):
    1. Run on ONE DC only: setup-ad-on-dc.ps1 -Phase Groups
    2. Wait: setup-ad-on-dc.ps1 -Phase WaitGroups
    3. Host ACLs on each managed server (setup-host-hcc-permissions.ps1)
    4. Run on SAME DC: setup-ad-on-dc.ps1 -Phase ServiceAccount
    5. Wait: setup-ad-on-dc.ps1 -Phase WaitServiceAccount
    6. Install agent with -RunAsAccount on each host

.EXAMPLE
  .\setup-ad-tier-groups.ps1
  .\setup-ad-tier-groups.ps1 -ConfigPath .\config.example.psd1 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "config.example.psd1")
)

$ErrorActionPreference = "Stop"

function Require-Module {
    param([string]$Name)
    if (-not (Get-Module -ListAvailable -Name $Name)) {
        throw "Required module '$Name' is not installed. Install RSAT Active Directory tools."
    }
    Import-Module $Name -ErrorAction Stop | Out-Null
}

function Ensure-AdOrganizationalUnit {
    param(
        [string]$DistinguishedName,
        [string]$Description
    )
    $existing = Get-ADOrganizationalUnit -Filter "DistinguishedName -eq '$DistinguishedName'" -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "OU exists: $DistinguishedName"
        return $existing
    }

    $parts = $DistinguishedName.Split(",")
    $name = ($parts[0] -replace "^OU=", "")
    $parent = ($parts[1..($parts.Length - 1)] -join ",")

    if ($parent -match "^OU=") {
        Ensure-AdOrganizationalUnit -DistinguishedName $parent -Description "HCC parent container"
    }

    if ($PSCmdlet.ShouldProcess($DistinguishedName, "Create OU")) {
        New-ADOrganizationalUnit -Name $name -Path $parent -ProtectedFromAccidentalDeletion $true -Description $Description
        Write-Host "Created OU: $DistinguishedName"
    }
}

function Ensure-AdGroup {
    param(
        [hashtable]$Group,
        [string]$Path,
        [string]$DomainNetBios
    )
    $sam = $Group.Name
    $existing = Get-ADGroup -Filter "SamAccountName -eq '$sam'" -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Group exists: $sam"
        if ($Group.Description -and $existing.Description -ne $Group.Description) {
            if ($PSCmdlet.ShouldProcess($sam, "Update description")) {
                Set-ADGroup -Identity $existing.DistinguishedName -Description $Group.Description
            }
        }
        return $existing
    }
    if ($PSCmdlet.ShouldProcess($sam, "Create group")) {
        New-ADGroup `
            -Name $sam `
            -SamAccountName $sam `
            -GroupScope Global `
            -GroupCategory Security `
            -Path $Path `
            -Description $Group.Description
        Write-Host "Created group: $DomainNetBios\$sam"
    }
}

if (-not (Test-Path $ConfigPath)) {
    throw "Config not found: $ConfigPath"
}

$config = Import-PowerShellDataFile -Path $ConfigPath
Require-Module ActiveDirectory

$domain = Get-ADDomain -Identity $config.DomainDnsName
Write-Host "Domain: $($domain.DNSRoot)"

Ensure-AdOrganizationalUnit -DistinguishedName $config.GroupsOu -Description "HCC role groups for dashboard RBAC and agent execution"
Ensure-AdOrganizationalUnit -DistinguishedName $config.ServiceAccountsOu -Description "HCC managed service accounts"

Write-Host "`nCreating tier groups..."
foreach ($group in $config.TierGroups) {
    Ensure-AdGroup -Group $group -Path $config.GroupsOu -DomainNetBios $config.DomainNetBios
}

Write-Host "`nTier group setup complete."
Write-Host "Human RBAC groups (add dashboard users later):"
Write-Host "  - HCC-Agent-Observers"
Write-Host "  - HCC-Agent-Operators"
Write-Host "  - HCC-Agent-Maintainers"
Write-Host "  - HCC-Agent-Deployers"
Write-Host "Service execution group (leave empty until gMSA is created):"
Write-Host "  - HCC-Agent-ServiceAccounts"
Write-Host "`nNext: setup-ad-on-dc.ps1 -Phase WaitGroups"
Write-Host "Then: setup-host-hcc-permissions.ps1 on each managed Windows host"
Write-Host "Then: setup-ad-on-dc.ps1 -Phase ServiceAccount"
