<#
.SYNOPSIS
  Diagnose HCC dashboard AD login for the current or named user.

.EXAMPLE
  $sec = Read-Host "Password" -AsSecureString
  .\test-ad-login.ps1 -Username Jaleel -Password $sec
#>
[CmdletBinding()]
param(
    [string]$Username = $env:USERNAME,
    [Parameter(Mandatory = $true)]
    [Security.SecureString]$Password,
    [string]$CoreUrl = "http://192.168.1.10:18080",
    [string]$DomainDnsName = "example.local",
    [string]$DomainNetBios = "EXAMPLE",
    [string]$LdapServer = "192.168.1.11"
)

$ErrorActionPreference = "Stop"
Import-Module ActiveDirectory -ErrorAction Stop

$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

$user = Get-ADUser -Identity $Username -Properties SamAccountName, UserPrincipalName, Enabled, LockedOut, PasswordExpired, MemberOf
Write-Host ""
Write-Host "=== AD account ===" -ForegroundColor Cyan
Write-Host "SamAccountName : $($user.SamAccountName)"
Write-Host "UserPrincipalName : $($user.UserPrincipalName)"
Write-Host "Enabled : $($user.Enabled)"
Write-Host "LockedOut : $($user.LockedOut)"
Write-Host "PasswordExpired : $($user.PasswordExpired)"

$hccGroups = @()
foreach ($groupDn in $user.MemberOf) {
    $group = Get-ADGroup -Identity $groupDn -ErrorAction SilentlyContinue
    if ($group -and $group.SamAccountName -like "HCC-Agent-*") {
        $hccGroups += $group.SamAccountName
    }
}
Write-Host "HCC groups : $(if ($hccGroups) { $hccGroups -join ', ' } else { '(none)' })"

Write-Host ""
Write-Host "=== Local credential validation ===" -ForegroundColor Cyan
Add-Type -AssemblyName System.DirectoryServices.AccountManagement
$ctx = New-Object System.DirectoryServices.AccountManagement.PrincipalContext("Domain", $DomainDnsName)

$samOk = $ctx.ValidateCredentials($user.SamAccountName, $plain)
Write-Host "ValidateCredentials($($user.SamAccountName)) : $samOk"

$upnOk = $ctx.ValidateCredentials($user.UserPrincipalName, $plain)
Write-Host "ValidateCredentials($($user.UserPrincipalName)) : $upnOk"

Write-Host ""
Write-Host "=== LDAP bind to $LdapServer ===" -ForegroundColor Cyan
foreach ($identity in @($user.UserPrincipalName, "$DomainNetBios\$($user.SamAccountName)", "$($user.SamAccountName)@$DomainDnsName")) {
    try {
        $entry = New-Object System.DirectoryServices.DirectoryEntry("LDAP://${LdapServer}", $identity, $plain)
        $null = $entry.NativeObject
        Write-Host "LDAP bind OK : $identity" -ForegroundColor Green
    } catch {
        Write-Host "LDAP bind FAIL : $identity -> $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== HCC core login API ===" -ForegroundColor Cyan
$attempts = @(
    @{ username = $user.SamAccountName; label = "SamAccountName" },
    @{ username = $user.UserPrincipalName; label = "UserPrincipalName" },
    @{ username = "$DomainNetBios\$($user.SamAccountName)"; label = "NetBIOS\sam" }
)

foreach ($attempt in $attempts) {
    $body = @{
        username = $attempt.username
        password = $plain
    } | ConvertTo-Json
    try {
        $response = Invoke-RestMethod -Uri "$CoreUrl/api/v1/auth/login" -Method POST -Body $body -ContentType "application/json"
        Write-Host "Core login OK via $($attempt.label) ($($attempt.username)) as $($response.user.role)" -ForegroundColor Green
    } catch {
        $detail = $_.ErrorDetails.Message
        if (-not $detail) { $detail = $_.Exception.Message }
        Write-Host "Core login FAIL via $($attempt.label) ($($attempt.username)) -> $detail" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Use the UserPrincipalName shown above on the HCC login page if SamAccountName fails." -ForegroundColor Cyan
