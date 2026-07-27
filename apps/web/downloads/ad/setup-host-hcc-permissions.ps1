<#
.SYNOPSIS
  Applies local Windows permissions for HCC agent service account group on this host.

.DESCRIPTION
  Run AFTER setup-ad-tier-groups.ps1 and BEFORE creating the gMSA.
  Grants WEB-FLIP\HCC-Agent-ServiceAccounts:
    - NTFS on agent install/config paths
    - SeBatchLogonRight (scheduled task)
    - Start/stop/query on allowlisted services (role-specific)

.EXAMPLE
  .\setup-host-hcc-permissions.ps1 -HostRole dc
  .\setup-host-hcc-permissions.ps1 -HostRole member -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dc", "member", "client")]
    [string]$HostRole,

    [string]$ConfigPath = (Join-Path $PSScriptRoot "config.web-flip.psd1"),
    [string]$ServiceAccountGroupSam = "HCC-Agent-ServiceAccounts"
)

$ErrorActionPreference = "Stop"

function Get-DomainGroupPrincipal {
    param(
        [string]$DomainNetBios,
        [string]$Sam
    )
    return "$DomainNetBios\$Sam"
}

function Grant-PathAcl {
    param(
        [string]$Path,
        [string]$Principal,
        [string]$Rights
    )
    if (-not (Test-Path $Path)) {
        if ($PSCmdlet.ShouldProcess($Path, "Create directory")) {
            New-Item -ItemType Directory -Force -Path $Path | Out-Null
        }
    }
    if ($PSCmdlet.ShouldProcess($Path, "Grant $Rights to $Principal")) {
        icacls $Path /grant "${Principal}:(OI)(CI)$Rights" /Q | Out-Null
        icacls $Path /grant "Administrators:(OI)(CI)F" /Q | Out-Null
        icacls $Path /grant "SYSTEM:(OI)(CI)F" /Q | Out-Null
        Write-Host "ACL $Rights on $Path -> $Principal"
    }
}

function Grant-BatchLogonRight {
    param(
        [string]$DomainNetBios,
        [string]$Sam
    )
    $account = "$DomainNetBios\$Sam"
    $export = Join-Path $env:TEMP "hcc-secedit-export.cfg"
    $db = Join-Path $env:TEMP "hcc-secedit.sdb"
    $inf = Join-Path $env:TEMP "hcc-secedit-batch.inf"

    if (-not $PSCmdlet.ShouldProcess($account, "Grant SeBatchLogonRight")) {
        return
    }

    secedit /export /cfg $export /quiet | Out-Null
    if (-not (Test-Path $export)) {
        throw "Failed to export local security policy from secedit."
    }

    $lines = Get-Content $export
    $updated = @()
    $found = $false
    foreach ($line in $lines) {
        if ($line -match '^SeBatchLogonRight\s*=') {
            $found = $true
            if ($line -match [regex]::Escape($account)) {
                Write-Host "SeBatchLogonRight already includes $account"
                return
            }
            if ($line -match 'SeBatchLogonRight\s*=\s*$') {
                $updated += "SeBatchLogonRight = $account"
            } else {
                $updated += ($line.TrimEnd() + ",$account")
            }
        } else {
            $updated += $line
        }
    }
    if (-not $found) {
        throw "SeBatchLogonRight not found in secedit export."
    }
    Set-Content -Path $inf -Value $updated -Encoding Unicode
    secedit /configure /db $db /cfg $inf /areas USER_RIGHTS /quiet | Out-Null
    Write-Host "Granted SeBatchLogonRight to $account"
}

function Add-ServiceControlAce {
    param(
        [string]$ServiceName,
        [string]$GroupSidString
    )
    $ace = "(A;;RPWPCR;;;$GroupSidString)"
    $raw = (sc.exe sdshow $ServiceName 2>$null)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Skip service (not present): $ServiceName"
        return
    }
    $current = (($raw | ForEach-Object { $_.Trim() }) -join "") -replace "`0", ""
    if ($current -match [regex]::Escape($GroupSidString)) {
        Write-Host "Service ACL already set: $ServiceName"
        return
    }
    $saclMarker = "S:"
    $markerIndex = $current.IndexOf($saclMarker)
    if ($markerIndex -ge 0) {
        $newSddl = $current.Substring(0, $markerIndex) + $ace + $current.Substring($markerIndex)
    } else {
        $newSddl = $current + $ace
    }
    if ($PSCmdlet.ShouldProcess($ServiceName, "Grant service control to $GroupSidString")) {
        sc.exe sdset $ServiceName $newSddl | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Service control granted: $ServiceName"
        } else {
            Write-Warning "Failed to update service ACL: $ServiceName"
        }
    }
}

if (-not (Test-Path $ConfigPath)) {
    throw "Config not found: $ConfigPath"
}

$config = Import-PowerShellDataFile -Path $ConfigPath
$principal = Get-DomainGroupPrincipal -DomainNetBios $config.DomainNetBios -Sam $ServiceAccountGroupSam

try {
    $ntAccount = New-Object System.Security.Principal.NTAccount($principal)
    $groupSid = $ntAccount.Translate([System.Security.Principal.SecurityIdentifier]).Value
} catch {
    throw "Could not resolve SID for $principal. Run setup-ad-tier-groups.ps1 on the domain first."
}

$installDir = Join-Path $env:ProgramFiles "HCC-Agent"
$configDir = Join-Path $env:ProgramData "HCC-Agent"
$stagingDir = Join-Path $configDir "staging"

Write-Host "Applying HCC host permissions for role: $HostRole"
Write-Host "Service account group: $principal"

Grant-PathAcl -Path $installDir -Principal $principal -Rights "RX"
Grant-PathAcl -Path $configDir -Principal $principal -Rights "M"
Grant-PathAcl -Path $stagingDir -Principal $principal -Rights "M"
Grant-BatchLogonRight -DomainNetBios $config.DomainNetBios -Sam $ServiceAccountGroupSam

$services = switch ($HostRole) {
    "dc" { $config.DcServices }
    "member" { $config.MemberServerServices }
    "client" { @() }
}
if ($services.Count -gt 0) {
    Write-Host "`nGranting service control on: $($services -join ', ')"
    foreach ($serviceName in $services) {
        Add-ServiceControlAce -ServiceName $serviceName -GroupSidString $groupSid
    }
} else {
    Write-Host "`nNo service-control ACLs for role '$HostRole' (metrics-only)."
}

Write-Host "`nHost permission setup complete."
Write-Host "Next: create gMSA and add it to $ServiceAccountGroupSam, then install agent with -RunAsAccount."
