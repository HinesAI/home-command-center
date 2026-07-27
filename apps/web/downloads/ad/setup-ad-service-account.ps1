<#
.SYNOPSIS
  Creates the HCC gMSA on one DC and adds it to HCC-Agent-ServiceAccounts.
  Run AFTER tier groups have replicated (setup-ad-on-dc.ps1 -Phase WaitGroups).
  Host ACLs can be applied before or after gMSA creation; agent install comes last.

.EXAMPLE
  .\setup-ad-service-account.ps1 -AllowedComputerNames HINESDC1,HINESDC2,HINESDC3
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "config.web-flip.psd1"),
    [string]$ServiceAccountName = "svc-hcc-agent",
    [string[]]$AllowedComputerNames = @("HINESDC1", "HINESDC2", "HINESDC3"),
    [string]$ServiceAccountGroupSam = "HCC-Agent-ServiceAccounts"
)

$ErrorActionPreference = "Stop"
Import-Module ActiveDirectory -ErrorAction Stop

if (-not (Test-Path $ConfigPath)) {
    throw "Config not found: $ConfigPath"
}

$config = Import-PowerShellDataFile -Path $ConfigPath
$dnsHostName = "$ServiceAccountName.$($config.DomainDnsName)"
$gmsaSamAccountName = if ($ServiceAccountName.EndsWith('$')) { $ServiceAccountName } else { "$ServiceAccountName$" }
$allowedPrincipals = @($AllowedComputerNames | ForEach-Object { "$($_.ToUpper())$" })

$existing = Get-ADServiceAccount -Filter "SamAccountName -eq '$gmsaSamAccountName'" -ErrorAction SilentlyContinue
if (-not $existing) {
    if ($PSCmdlet.ShouldProcess($ServiceAccountName, "Create gMSA")) {
        New-ADServiceAccount `
            -Name $ServiceAccountName `
            -SamAccountName $ServiceAccountName `
            -DNSHostName $dnsHostName `
            -Path $config.ServiceAccountsOu `
            -Description "HCC fleet agent service account" `
            -PrincipalsAllowedToRetrieveManagedPassword $allowedPrincipals
        Write-Host "Created gMSA: $($config.DomainNetBios)\$ServiceAccountName$"
    }
} else {
    Write-Host "gMSA exists: $($config.DomainNetBios)\$ServiceAccountName$"
    if ($PSCmdlet.ShouldProcess($ServiceAccountName, "Update allowed principals")) {
        Set-ADServiceAccount -Identity $ServiceAccountName -PrincipalsAllowedToRetrieveManagedPassword @{Add=$allowedPrincipals}
    }
}

$group = Get-ADGroup -Identity $ServiceAccountGroupSam
$gmsa = Get-ADServiceAccount -Identity $ServiceAccountName
$existingMembers = @(Get-ADGroupMember -Identity $group.DistinguishedName | Select-Object -ExpandProperty SamAccountName)
if ($gmsaSamAccountName -in $existingMembers) {
    Write-Host "Already a member: $($config.DomainNetBios)\$ServiceAccountName$ -> $ServiceAccountGroupSam"
} elseif ($PSCmdlet.ShouldProcess($ServiceAccountGroupSam, "Add gMSA member")) {
    Add-ADGroupMember -Identity $group.DistinguishedName -Members $gmsa.DistinguishedName
    Write-Host "Added $($config.DomainNetBios)\$ServiceAccountName$ to $ServiceAccountGroupSam"
}

Write-Host "`nService account setup complete on this DC."
Write-Host "Next: setup-ad-on-dc.ps1 -Phase WaitServiceAccount"
Write-Host "Then install agent on each allowed host with:"
Write-Host "  -RunAsAccount `"$($config.DomainNetBios)\$ServiceAccountName$`""
