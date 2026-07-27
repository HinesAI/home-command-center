<#
.SYNOPSIS
  Applies setup-host-hcc-permissions.ps1 to multiple Windows hosts via WinRM.

.EXAMPLE
  $cred = Get-Credential "WEB-FLIP\Administrator"
  .\rollout-host-permissions.ps1 -Credential $cred -InventoryPath .\hosts.web-flip.csv
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [pscredential]$Credential,
    [string]$InventoryPath = (Join-Path $PSScriptRoot "hosts.web-flip.csv"),
    [string]$ScriptRoot = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
$rows = Get-Content $InventoryPath | Where-Object { $_ -and -not $_.StartsWith("#") } | ForEach-Object {
    $parts = $_.Split(",")
    [pscustomobject]@{
        Host = $parts[0].Trim()
        HostRole = $parts[1].Trim()
    }
}

foreach ($row in $rows) {
    Write-Host "---- $($row.Host) ($($row.HostRole)) ----"
    if ($PSCmdlet.ShouldProcess($row.Host, "Apply HCC host permissions")) {
        $session = New-PSSession -ComputerName $row.Host -Credential $Credential -ErrorAction Stop
        try {
            Copy-Item -Path (Join-Path $ScriptRoot "setup-host-hcc-permissions.ps1") -Destination "C:\Windows\Temp\" -ToSession $session -Force
            Copy-Item -Path (Join-Path $ScriptRoot "config.web-flip.psd1") -Destination "C:\Windows\Temp\" -ToSession $session -Force
            Invoke-Command -Session $session -ScriptBlock {
                param($Role)
                & "C:\Windows\Temp\setup-host-hcc-permissions.ps1" -HostRole $Role -ConfigPath "C:\Windows\Temp\config.web-flip.psd1"
            } -ArgumentList $row.HostRole
        } finally {
            Remove-PSSession $session
        }
    }
}

Write-Host "Host permission rollout complete."
