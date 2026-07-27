param(
    [string]$ManifestPath = ""
)

$ErrorActionPreference = "Stop"

$StateDir = Join-Path $env:ProgramData "HCC-Agent"
if (-not $ManifestPath) {
    $ManifestPath = Join-Path $StateDir "update-manifest.json"
}
$ResultPath = Join-Path $StateDir "update-result.json"
$LogPath = Join-Path $StateDir "update.log"
$InstallDir = Join-Path $env:ProgramFiles "HCC-Agent"
$EnvPath = Join-Path $StateDir "hcc-agent.env"
$ServiceName = "HCC-Agent"

$AgentFiles = @(
    "heartbeat_sender.ps1",
    "diagnose-server-core.ps1",
    "register-hcc-agent-service.ps1",
    "fix-hcc-agent.ps1",
    "apply-update.ps1"
)

function Write-UpdateLog {
    param([string]$Message)
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    Add-Content -Path $LogPath -Value "$stamp $Message"
}

function Write-UpdateResult {
    param(
        [bool]$Ok,
        [string]$Message
    )
    @{
        ok = $Ok
        message = $Message
        completedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    } | ConvertTo-Json -Compress | Set-Content -Path $ResultPath -Encoding UTF8
}

function Stop-HccAgentForUpdate {
    param([string]$InstallDir, [string]$ServiceName)
    $wrapper = Join-Path $InstallDir "HCC-Agent.exe"
    if (Test-Path $wrapper) {
        & $wrapper stop 2>&1 | Out-Null
        Start-Sleep -Seconds 3
        return
    }
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service -and $service.Status -eq "Running") {
        Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
    }
}

function Start-HccAgentAfterUpdate {
    param([string]$InstallDir, [string]$ServiceName)
    $wrapper = Join-Path $InstallDir "HCC-Agent.exe"
    if (Test-Path $wrapper) {
        & $wrapper start 2>&1 | Out-Null
        return
    }
    Start-Service -Name $ServiceName -ErrorAction SilentlyContinue
}

function Set-EnvFileVersion {
    param(
        [string]$Path,
        [string]$Version
    )
    $lines = @()
    if (Test-Path $Path) {
        $lines = Get-Content $Path
    }
    $updated = $false
    $result = @()
    foreach ($line in $lines) {
        if ($line -match "^HCC_AGENT_VERSION=") {
            $result += "HCC_AGENT_VERSION=$Version"
            $updated = $true
        } else {
            $result += $line
        }
    }
    if (-not $updated) {
        $result += "HCC_AGENT_VERSION=$Version"
    }
    Set-Content -Path $Path -Value $result -Encoding ASCII
}

try {
    if (-not (Test-Path $ManifestPath)) {
        throw "missing manifest: $ManifestPath"
    }

    $manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json
    $version = [string]$manifest.version
    $sourceDir = [string]$manifest.sourceDir
    if ($manifest.installDir) { $InstallDir = [string]$manifest.installDir }
    if ($manifest.envPath) { $EnvPath = [string]$manifest.envPath }

    if (-not $version -or -not (Test-Path $sourceDir)) {
        throw "invalid manifest version=$version sourceDir=$sourceDir"
    }

    Write-UpdateLog "applying version $version from $sourceDir"
    Stop-HccAgentForUpdate -InstallDir $InstallDir -ServiceName $ServiceName

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    foreach ($file in $AgentFiles) {
        $src = Join-Path $sourceDir $file
        if (Test-Path $src) {
            Copy-Item -Path $src -Destination (Join-Path $InstallDir $file) -Force
            Write-UpdateLog "installed $file"
        }
    }

    Set-EnvFileVersion -Path $EnvPath -Version $version
    Write-UpdateLog "set HCC_AGENT_VERSION=$version"

    Start-HccAgentAfterUpdate -InstallDir $InstallDir -ServiceName $ServiceName
    Write-UpdateResult -Ok $true -Message "updated to version $version"
    Write-UpdateLog "update complete -> $version"
} catch {
    Write-UpdateLog "update failed: $($_.Exception.Message)"
    Write-UpdateResult -Ok $false -Message $_.Exception.Message
    Start-HccAgentAfterUpdate -InstallDir $InstallDir -ServiceName $ServiceName
    exit 1
}
