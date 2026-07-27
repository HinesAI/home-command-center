param(
    [switch]$EnableWinRM,
    [switch]$EnableOpenSSH
)

$ErrorActionPreference = "Stop"

function Require-Admin {
    $current = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $current.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script from an elevated PowerShell session."
    }
}

Require-Admin

if ($EnableWinRM) {
    Write-Host "Enabling WinRM ..."
    Enable-PSRemoting -Force -SkipNetworkProfileCheck
    Set-Item WSMan:\localhost\Client\TrustedHosts -Value "*" -Force
    Write-Host "WinRM enabled."
}

if ($EnableOpenSSH) {
    Write-Host "Installing OpenSSH Server capability ..."
    Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction Stop
    Start-Service sshd
    Set-Service -Name sshd -StartupType Automatic
    $firewall = Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue
    if ($firewall) {
        Enable-NetFirewallRule -Name "OpenSSH-Server-In-TCP"
    }
    Write-Host "OpenSSH Server enabled."
}

Write-Host "Server Core access prep complete."
