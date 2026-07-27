param(
    [Parameter(Mandatory = $true)][string]$InventoryFile,
    [string]$CredentialUsername = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallScript = Join-Path $ScriptDir "install-windows-agent.ps1"

if (-not (Test-Path $InventoryFile)) {
    throw "Inventory file not found: $InventoryFile"
}
if (-not (Test-Path $InstallScript)) {
    throw "Installer not found: $InstallScript"
}

function Get-InventoryRows {
    param([string]$Path)
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $parts = $line.Split(",")
        if ($parts.Count -lt 7) {
            throw "Invalid inventory row (expected 7 columns): $line"
        }
        [pscustomobject]@{
            Host = $parts[0].Trim()
            NodeId = $parts[1].Trim()
            AgentId = $parts[2].Trim()
            CoreBaseUrl = $parts[3].Trim()
            Interval = $parts[4].Trim()
            Services = $parts[5].Trim().Trim('"')
            StorageDrives = $parts[6].Trim()
        }
    }
}

$credential = $null
if ($CredentialUsername) {
    $credential = Get-Credential -UserName $CredentialUsername -Message "Password for remote DC rollout"
}

$rows = @(Get-InventoryRows -Path $InventoryFile)
Write-Host "Loaded $($rows.Count) Windows host(s) from $InventoryFile"

foreach ($row in $rows) {
    Write-Host "---- $($row.Host) ($($row.NodeId)) ----"
    $installArgs = @{
        CoreBaseUrl = $row.CoreBaseUrl
        NodeId = $row.NodeId
        AgentId = $row.AgentId
        Interval = $row.Interval
        Services = $row.Services
        StorageDrives = $row.StorageDrives
        InstallPythonIfMissing = $true
    }

    if ($DryRun) {
        Write-Host "[dry-run] Would deploy to $($row.Host) with node $($row.NodeId)"
        continue
    }

    if ($row.Host -eq "." -or $row.Host -eq "localhost" -or $row.Host -eq $env:COMPUTERNAME) {
        & $InstallScript @installArgs
        continue
    }

    $sessionParams = @{
        ComputerName = $row.Host
        ErrorAction = "Stop"
    }
    if ($credential) {
        $sessionParams.Credential = $credential
    }

    $session = New-PSSession @sessionParams
    try {
        Copy-Item -Path (Join-Path $ScriptDir "heartbeat_sender.py") -Destination "C:\Windows\Temp\hcc-agent\" -ToSession $session -Force
        Copy-Item -Path (Join-Path $ScriptDir "host_intelligence.py") -Destination "C:\Windows\Temp\hcc-agent\" -ToSession $session -Force
        Copy-Item -Path (Join-Path $ScriptDir "action_runner.py") -Destination "C:\Windows\Temp\hcc-agent\" -ToSession $session -Force
        Copy-Item -Path $InstallScript -Destination "C:\Windows\Temp\hcc-agent\" -ToSession $session -Force

        $argList = @(
            "-CoreBaseUrl `"$($row.CoreBaseUrl)`""
            "-NodeId `"$($row.NodeId)`""
            "-AgentId `"$($row.AgentId)`""
            "-Interval `"$($row.Interval)`""
            "-Services `"$($row.Services)`""
            "-StorageDrives `"$($row.StorageDrives)`""
            "-InstallPythonIfMissing"
        )
        Invoke-Command -Session $session -ScriptBlock {
            param($ScriptPath, $ArgList)
            Set-Location (Split-Path $ScriptPath)
            $command = "& `"$ScriptPath`" $ArgList"
            Invoke-Expression $command
        } -ArgumentList "C:\Windows\Temp\hcc-agent\install-windows-agent.ps1", ($argList -join " ")
    }
    finally {
        Remove-PSSession $session
    }
}

Write-Host "Windows rollout complete."
