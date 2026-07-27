param(
    [switch]$Once
)

$ErrorActionPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ConfigDir = Join-Path $env:ProgramData "HCC-Agent"
$EnvPath = Join-Path $ConfigDir "hcc-agent.env"
$LogPath = Join-Path $ConfigDir "agent.log"
$StatePath = Join-Path $ConfigDir "agent-state.json"

function Get-MaxInt64 {
    param([int64]$Left, [int64]$Right)
    if ($Left -gt $Right) { return $Left }
    return $Right
}

function Get-MaxDouble {
    param([double]$Left, [double]$Right)
    if ($Left -gt $Right) { return $Left }
    return $Right
}

function ConvertTo-JsonArray {
    param(
        [AllowNull()]$Items,
        [int]$Depth = 6
    )
    $parts = @()
    foreach ($item in @($Items)) {
        if ($null -ne $item) {
            $parts += (ConvertTo-Json $item -Compress -Depth $Depth)
        }
    }
    return "[" + ($parts -join ",") + "]"
}

function Write-AgentLog {
    param([string]$Message)
    try {
        New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
        $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        Add-Content -Path $LogPath -Value "$stamp $Message"
    } catch {}
}

function Read-AgentState {
    if (-not (Test-Path $StatePath)) { return $null }
    try {
        return Get-Content $StatePath -Raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Write-AgentState {
    param(
        [bool]$Success,
        [string]$Message = "",
        [int]$ConsecutiveFailures = 0
    )
    $attemptUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $previous = Read-AgentState
    $state = @{
        lastAttemptUtc = $attemptUtc
        consecutiveFailures = $ConsecutiveFailures
        lastMessage = $Message
    }
    if ($Success) {
        $state.lastSuccessUtc = $attemptUtc
    } elseif ($previous -and $previous.lastSuccessUtc) {
        $state.lastSuccessUtc = [string]$previous.lastSuccessUtc
    }
    try {
        $state | ConvertTo-Json -Compress | Set-Content -Path $StatePath -Encoding ASCII
    } catch {}
}

function Get-RetryDelaySeconds {
    param(
        [int]$Failures,
        [int]$NormalInterval
    )
    if ($Failures -le 0) { return $NormalInterval }
    $delay = [int](15 * [Math]::Pow(2, [Math]::Min($Failures - 1, 3)))
    return [Math]::Max(15, [Math]::Min($NormalInterval, $delay))
}

function Test-TransientWebError {
    param([string]$Message)
    if (-not $Message) { return $false }
    return $Message -match "Unable to connect|No such host|Name or service not known|timed out|actively refused|connection|forcibly closed|502|503|504|Bad Gateway|Service Unavailable|Gateway Timeout|The remote server returned an error"
}

function Read-EnvFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return @{} }
    $values = @{}
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or $line -notmatch "=") { return }
        $parts = $line.Split("=", 2)
        $values[$parts[0].Trim()] = $parts[1].Trim().Trim('"')
    }
    return $values
}

function Get-AgentConfig {
    $envValues = Read-EnvFile -Path $EnvPath
    $coreBase = if ($envValues["HCC_CORE_BASE_URL"]) { $envValues["HCC_CORE_BASE_URL"].TrimEnd("/") } else { "" }
    $heartbeat = if ($envValues["HCC_CORE_HEARTBEAT_URL"]) { $envValues["HCC_CORE_HEARTBEAT_URL"] } elseif ($coreBase) { "$coreBase/api/v1/agent/heartbeat" } else { "" }
    $services = if ($envValues["HCC_SERVICES"]) { $envValues["HCC_SERVICES"].Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ } } else { @("NTDS","DNS","DHCP","KDC","Netlogon","W32Time","WinRM","W3SVC","Spooler") }
    $drives = if ($envValues["HCC_STORAGE_DRIVES"]) { $envValues["HCC_STORAGE_DRIVES"].Split(",") | ForEach-Object { $_.Trim().ToUpper() } | Where-Object { $_ } } else { @("C") }
    return [pscustomobject]@{
        CoreUrl = $heartbeat
        NodeId = if ($envValues["HCC_AGENT_NODE_ID"]) { $envValues["HCC_AGENT_NODE_ID"] } else { $env:COMPUTERNAME }
        AgentId = if ($envValues["HCC_AGENT_ID"]) { $envValues["HCC_AGENT_ID"] } else { "agent-$($env:COMPUTERNAME)" }
        AgentVersion = if ($envValues["HCC_AGENT_VERSION"]) { $envValues["HCC_AGENT_VERSION"] } else { "1.0.9" }
        Interval = if ($envValues["HCC_AGENT_INTERVAL_SECONDS"]) { [int]$envValues["HCC_AGENT_INTERVAL_SECONDS"] } else { 120 }
        Services = $services
        StorageDrives = $drives
    }
}

function Get-HardwareProfile {
    $cs = Get-CimInstance Win32_ComputerSystem
    $model = [string]$cs.Model
    $manufacturer = [string]$cs.Manufacturer
    $hypervisor = [bool]$cs.HypervisorPresent
    $vmHints = @("Virtual Machine","VMware","KVM","VirtualBox","QEMU","Hyper-V","Microsoft Virtual")
    $isVM = $hypervisor -or ($vmHints | Where-Object { $model -like "*$_*" -or $manufacturer -like "*$_*" })
    return @{
        virtualizationType = if ($hypervisor) { "hyperv" } elseif ($isVM) { "vm" } else { "none" }
        isVirtualMachine = [bool]$isVM
        isContainer = $false
        isPhysical = -not [bool]$isVM
    }
}

function Get-HostRole {
    param($Hardware)
    $os = Get-CimInstance Win32_OperatingSystem
    $productType = [int]$os.ProductType
    $caption = [string]$os.Caption
    if ($productType -eq 1 -or $caption -match "Windows 10|Windows 11") { return "windows-client" }
    if ($productType -in 2,3 -or $caption -match "Server|Domain Controller") { return "windows-server" }
    if ($Hardware.isVirtualMachine) { return "windows-server" }
    return "windows-client"
}

function Get-CpuInfo {
    $cpus = Get-CimInstance Win32_Processor
    $model = [string]($cpus | Select-Object -First 1 -ExpandProperty Name)
    $logical = [int](($cpus | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum)
    $physical = [int](($cpus | Measure-Object -Property NumberOfCores -Sum).Sum)
    $sockets = [int](($cpus | Select-Object -ExpandProperty SocketDesignation | Sort-Object -Unique | Measure-Object).Count)
    return @{
        model = $model
        logicalCpus = $logical
        physicalCores = $physical
        sockets = $sockets
        cores = $logical
        threads = $logical
        arch = [string]($cpus | Select-Object -First 1 -ExpandProperty AddressWidth) + "-bit"
        physical = $true
    }
}

function Get-ActionCatalog {
    param([string]$HostRole)
    $hostActions = @(
        @{ id = "host.reboot"; label = "Reboot Host"; scope = "host"; dangerous = $true },
        @{ id = "host.shutdown"; label = "Shutdown Host"; scope = "host"; dangerous = $true }
    )
    if ($HostRole -eq "windows-server") {
        return @(
            @{ id = "agent.self_update"; label = "Self Update Agent"; scope = "agent"; dangerous = $true },
            @{ id = "service.restart"; label = "Restart Service"; scope = "service"; targetRequired = $true },
            @{ id = "service.stop"; label = "Stop Service"; scope = "service"; targetRequired = $true; dangerous = $true },
            @{ id = "service.start"; label = "Start Service"; scope = "service"; targetRequired = $true }
        ) + $hostActions
    }
    return $hostActions
}

function Get-PrimaryIps {
    $ips = @()
    $configs = Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -eq $true -and $_.IPAddress }
    foreach ($cfg in $configs) {
        foreach ($ip in @($cfg.IPAddress)) {
            if ($ip -and $ip -notlike "127.*" -and $ip -notlike "*:*") {
                $ips += [string]$ip
            }
        }
    }
    return ($ips | Select-Object -Unique | Select-Object -First 3)
}

function Get-CpuMetrics {
    $perf = Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor | Where-Object { $_.Name -eq "_Total" } | Select-Object -First 1
    $queueObj = Get-CimInstance Win32_PerfFormattedData_PerfOS_System
    $queue = if ($queueObj) { [double]$queueObj.ProcessorQueueLength } else { 0.0 }
    $idle = if ($perf) { [double]$perf.PercentIdleTime } else { 100.0 }
    $used = [math]::Round([math]::Max(0, [math]::Min(100, 100 - $idle)), 1)
    return @{ percent = $used; load1 = [math]::Round($queue, 2); load5 = 0.0; load15 = 0.0; queueLength = [math]::Round($queue, 2) }
}

function Get-MemoryMetrics {
    $os = Get-CimInstance Win32_OperatingSystem
    $total = [int64]$os.TotalVisibleMemorySize * 1024
    $free = [int64]$os.FreePhysicalMemory * 1024
    $used = [int64]($total - $free)
    $swapTotal = [int64](Get-MaxInt64 -Left 0 -Right ([int64]$os.TotalVirtualMemorySize - [int64]$os.TotalVisibleMemorySize)) * 1024
    $swapFree = [int64](Get-MaxInt64 -Left 0 -Right ([int64]$os.FreeVirtualMemory - [int64]$os.FreePhysicalMemory)) * 1024
    $swapUsed = [int64]($swapTotal - $swapFree)
    return @{
        percent = if ($total -gt 0) { [math]::Round(($used * 100.0) / $total, 1) } else { 0 }
        usedBytes = $used
        totalBytes = $total
        availableBytes = $free
        swapUsedBytes = (Get-MaxInt64 -Left 0 -Right $swapUsed)
        swapTotalBytes = (Get-MaxInt64 -Left 0 -Right $swapTotal)
        swapPercent = if ($swapTotal -gt 0) { [math]::Round(($swapUsed * 100.0) / $swapTotal, 1) } else { 0 }
    }
}

function Get-NetworkRates {
    $netStatePath = Join-Path $ConfigDir "net-state.json"
    $state = $null
    if (Test-Path $netStatePath) {
        try { $state = Get-Content $netStatePath -Raw | ConvertFrom-Json } catch {}
    }
    $now = [int][double]::Parse((Get-Date -UFormat %s))
    $rx = [int64]0
    $tx = [int64]0
    $perf = Get-CimInstance Win32_PerfRawData_Tcpip_NetworkInterface | Where-Object { $_.Name -notmatch "Loopback|isatap|Teredo|QoS" }
    if ($perf) {
        $rx = [int64](($perf | Measure-Object -Property BytesReceivedPerSec -Sum).Sum)
        $tx = [int64](($perf | Measure-Object -Property BytesSentPerSec -Sum).Sum)
    }
    $rates = @{ rxBytesPerSec = 0; txBytesPerSec = 0 }
    if ($state -and $state.netRx -ne $null -and $state.netTs -ne $null) {
        $elapsed = Get-MaxDouble -Left 1.0 -Right ([double]$now - [double]$state.netTs)
        $rxRate = ([double]$rx - [double]$state.netRx) / $elapsed
        $txRate = ([double]$tx - [double]$state.netTx) / $elapsed
        if ($rxRate -lt 0) { $rxRate = 0 }
        if ($txRate -lt 0) { $txRate = 0 }
        $rates.rxBytesPerSec = [int64]$rxRate
        $rates.txBytesPerSec = [int64]$txRate
    }
    @{ netRx = $rx; netTx = $tx; netTs = $now } | ConvertTo-Json -Compress | Set-Content -Path $netStatePath -Encoding ASCII
    return $rates
}

function Get-StorageRows {
    param([string[]]$Drives)
    $rows = [System.Collections.ArrayList]@()
    $letters = @(
        $Drives | ForEach-Object {
            $letter = $_.Trim().TrimEnd(":").ToUpper()
            if ($letter -match '^[A-Z]$') { $letter }
        } | Where-Object { $_ } | Select-Object -Unique
    )
    if (-not $letters.Count) {
        $letters = @("C")
    }

    function Add-StorageRow {
        param(
            [string]$DeviceId,
            [string]$FileSystem,
            [int64]$TotalBytes,
            [int64]$FreeBytes
        )
        if ($TotalBytes -le 0) { return }
        foreach ($existing in $rows) {
            if ($existing.path -eq $DeviceId) { return }
        }
        $used = [int64]($TotalBytes - $FreeBytes)
        [void]$rows.Add([ordered]@{
            path = $DeviceId
            source = $DeviceId
            fstype = [string]$FileSystem
            kind = "volume"
            usedBytes = $used
            totalBytes = $TotalBytes
            freeBytes = $FreeBytes
            percent = [math]::Round(($used * 100.0) / $TotalBytes, 1)
        })
    }

    try {
        Get-CimInstance Win32_LogicalDisk -ErrorAction Stop |
            Where-Object { $_.DriveType -eq 3 -and ($letters -contains $_.DeviceID.Replace(":", "").ToUpper()) } |
            ForEach-Object {
                Add-StorageRow -DeviceId ([string]$_.DeviceID) -FileSystem ([string]$_.FileSystem) -TotalBytes ([int64]$_.Size) -FreeBytes ([int64]$_.FreeSpace)
            }
    } catch {
        Write-AgentLog "storage WMI query failed: $($_.Exception.Message)"
    }

    if (-not $rows.Count) {
        try {
            Get-PSDrive -PSProvider FileSystem -ErrorAction Stop |
                Where-Object { $_.Name -match '^[A-Z]$' -and ($letters -contains $_.Name) } |
                ForEach-Object {
                    $root = "$($_.Name):\"
                    Add-StorageRow -DeviceId $root.TrimEnd("\") -FileSystem "NTFS" -TotalBytes ([int64]$_.Used + [int64]$_.Free) -FreeBytes ([int64]$_.Free)
                }
        } catch {
            Write-AgentLog "storage PSDrive query failed: $($_.Exception.Message)"
        }
    }

    if (-not $rows.Count) {
        foreach ($letter in $letters) {
            $root = "${letter}:\"
            try {
                $info = New-Object System.IO.DriveInfo($root)
                if (-not $info.IsReady) {
                    Write-AgentLog "storage skip not ready: $root"
                    continue
                }
                Add-StorageRow -DeviceId $root.TrimEnd("\") -FileSystem ([string]$info.DriveFormat) -TotalBytes ([int64]$info.TotalSize) -FreeBytes ([int64]$info.AvailableFreeSpace)
            } catch {
                Write-AgentLog "storage DriveInfo failed for ${root}: $($_.Exception.Message)"
            }
        }
    }

    if (-not $rows.Count) {
        Write-AgentLog "storage fallback: all fixed disks"
        try {
            Get-CimInstance Win32_LogicalDisk -ErrorAction Stop |
                Where-Object { $_.DriveType -eq 3 -and [int64]$_.Size -gt 0 } |
                ForEach-Object {
                    Add-StorageRow -DeviceId ([string]$_.DeviceID) -FileSystem ([string]$_.FileSystem) -TotalBytes ([int64]$_.Size) -FreeBytes ([int64]$_.FreeSpace)
                }
        } catch {
            Write-AgentLog "storage fallback WMI failed: $($_.Exception.Message)"
        }
    }

    return @($rows.ToArray())
}

function Get-AllServiceRows {
    param([string[]]$ControlledNames)
    $controlled = @{}
    foreach ($name in $ControlledNames) {
        if ($name) { $controlled[$name.ToLower()] = $true }
    }
    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($svc in @(Get-Service -ErrorAction SilentlyContinue)) {
        $status = switch ($svc.Status.ToString()) {
            "Running" { "running" }
            "StartPending" { "starting" }
            "StopPending" { "stop pending" }
            default { "stopped" }
        }
        $name = [string]$svc.Name
        $rows.Add(@{
            name = $name
            status = $status
            managed = $controlled.ContainsKey($name.ToLower())
        })
    }
    return @($rows | Sort-Object { $_.name })
}

function New-AgentSnapshot {
    param($Config)
    $hardware = Get-HardwareProfile
    $hostRole = Get-HostRole -Hardware $hardware
    $cpu = Get-CpuInfo
    $memory = Get-MemoryMetrics
    $cpuMetrics = Get-CpuMetrics
    $network = Get-NetworkRates
    $storageRows = Get-StorageRows -Drives $Config.StorageDrives
    $storageUsed = [int64]0
    $storageTotal = [int64]0
    foreach ($row in $storageRows) {
        $storageUsed += [int64]$row.usedBytes
        $storageTotal += [int64]$row.totalBytes
    }
    $os = Get-CimInstance Win32_OperatingSystem
    $uptimeSec = [int][math]::Max(0, ((Get-Date) - $os.LastBootUpTime).TotalSeconds)
    $deviceCategory = if ($hostRole -eq "windows-client") { "client" } else { "server" }
    return @{
        node = @{
            id = $Config.NodeId
            hostname = $env:COMPUTERNAME
            platform = "windows"
            hostRole = $hostRole
            deviceCategory = $deviceCategory
            agentVersion = $Config.AgentVersion
            uptimeSec = $uptimeSec
            ips = @(Get-PrimaryIps)
            os = @{
                name = [string]$os.Caption
                version = [string]$os.Version
                kernel = [string]$os.BuildNumber
                arch = [string]$os.OSArchitecture
            }
            hardware = $hardware
            cpu = $cpu
        }
        capabilities = @{
            hostRole = $hostRole
            deviceCategory = $deviceCategory
            actions = @(Get-ActionCatalog -HostRole $hostRole)
            sections = @{ services = $true; containers = $false; vms = $false; storage = $true }
        }
        workloads = @{
            kind = $hostRole
            focus = if ($hostRole -eq "windows-server") { @("services","storage") } else { @("storage") }
        }
        system = @{
            cpuPercent = $cpuMetrics.percent
            cpu = @{
                load1 = $cpuMetrics.load1
                load5 = $cpuMetrics.load5
                load15 = $cpuMetrics.load15
                queueLength = $cpuMetrics.queueLength
            }
            memory = $memory
            network = $network
        }
        storage = $storageRows
        storageDetail = @{
            totals = @{
                usedBytes = [int64]$storageUsed
                totalBytes = [int64]$storageTotal
                freeBytes = (Get-MaxInt64 -Left 0 -Right ($storageTotal - $storageUsed))
                percent = if ($storageTotal -gt 0) { [math]::Round(($storageUsed * 100.0) / $storageTotal, 1) } else { 0 }
            }
            configuredPaths = $storageRows
            filesystems = $storageRows
            blockDevices = @()
            zfsPools = @()
            zfsDatasets = @()
        }
        services = @(Get-AllServiceRows -ControlledNames $Config.Services)
        containers = @()
    }
}

function Get-FileSha256Hex {
    param([string]$Path)
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Set-EnvFileValue {
    param(
        [string]$Path,
        [string]$Key,
        [string]$Value
    )
    $lines = @()
    if (Test-Path $Path) {
        $lines = @(Get-Content $Path)
    }
    $updated = $false
    $result = @()
    foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Key))=") {
            $result += "$Key=$Value"
            $updated = $true
        } else {
            $result += $line
        }
    }
    if (-not $updated) {
        $result += "$Key=$Value"
    }
    Set-Content -Path $Path -Value $result -Encoding ASCII
}

function Invoke-AgentSelfUpdate {
    param(
        $Action,
        $Config
    )
    $params = $Action.params
    if ($params -is [pscustomobject]) {
        $params = @{
            version = $params.version
            packageUrl = $params.packageUrl
            sha256 = $params.sha256
        }
    }
    $targetVersion = [string]$params.version
    $packageUrl = [string]$params.packageUrl
    $expectedSha = ([string]$params.sha256).Trim().ToLowerInvariant()
    if (-not $targetVersion -or -not $packageUrl) {
        throw "agent.self_update requires version and packageUrl"
    }
    if ($Config.AgentVersion -eq $targetVersion) {
        return "already on version $targetVersion"
    }

    $installDir = Join-Path $env:ProgramFiles "HCC-Agent"
    $stagingDir = Join-Path $ConfigDir "staging"
    $zipPath = Join-Path $stagingDir "hcc-agent-windows.zip"
    $manifestPath = Join-Path $ConfigDir "update-manifest.json"
    New-Item -ItemType Directory -Force -Path $stagingDir | Out-Null

    try {
        Invoke-WebRequest -Uri $packageUrl -OutFile $zipPath -UseBasicParsing
        if ($expectedSha) {
            $actualSha = Get-FileSha256Hex -Path $zipPath
            if ($actualSha -ne $expectedSha) {
                throw "package sha256 mismatch expected=$expectedSha actual=$actualSha"
            }
        }

        $extractDir = Join-Path $stagingDir "extract"
        if (Test-Path $extractDir) {
            Remove-Item -Path $extractDir -Recurse -Force
        }
        Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

        $sourceDir = $extractDir
        $nested = Join-Path $extractDir "hcc-agent"
        if (Test-Path $nested) {
            $sourceDir = $nested
        }

        @{
            version = $targetVersion
            sourceDir = $sourceDir
            installDir = $installDir
            envPath = $EnvPath
            stateDir = $ConfigDir
            queuedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        } | ConvertTo-Json -Compress | Set-Content -Path $manifestPath -Encoding UTF8

        $installedHelper = Join-Path $installDir "apply-update.ps1"
        $helper = if (Test-Path $installedHelper) { $installedHelper } else { Join-Path $sourceDir "apply-update.ps1" }
        if (-not (Test-Path $helper)) {
            throw "update helper not found in install dir or staged package"
        }

        Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", "`"$helper`"", "-ManifestPath", "`"$manifestPath`"" `
            -WindowStyle Hidden `
            -ErrorAction Stop | Out-Null

        Write-AgentLog "update helper started for version $targetVersion"
        return "update scheduled for version $targetVersion (helper will stop/install/start)"
    } catch {
        Write-AgentLog "self-update staging failed: $($_.Exception.Message)"
        throw
    }
}

function Invoke-ScServiceControl {
    param(
        [string]$Name,
        [string]$Verb
    )
    if ($Verb -eq "start") {
        $output = sc.exe start $Name 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -and $output -notmatch "1056|already been started") {
            throw $output.Trim()
        }
        return "started $Name"
    }
    if ($Verb -eq "stop") {
        $output = sc.exe stop $Name 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -and $output -notmatch "1062|has not been started") {
            throw $output.Trim()
        }
        return "stopped $Name"
    }
    if ($Verb -eq "restart") {
        $stopOutput = sc.exe stop $Name 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -and $stopOutput -notmatch "1062|has not been started") {
            throw $stopOutput.Trim()
        }
        Start-Sleep -Seconds 2
        $startOutput = sc.exe start $Name 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -and $startOutput -notmatch "1056|already been started") {
            throw $startOutput.Trim()
        }
        return "restarted $Name"
    }
    throw "unsupported service verb: $Verb"
}

function Invoke-AgentAction {
    param(
        $Action,
        $Config
    )
    $allowed = @($Config.Services | ForEach-Object { $_.ToLower() })
    $actionId = [string]$Action.actionId
    $target = [string]$Action.target
    try {
        if ($actionId -eq "host.reboot") { shutdown /r /t 0 /f | Out-Null; return @{ ok = $true; message = "reboot requested" } }
        if ($actionId -eq "host.shutdown") { shutdown /s /t 0 /f | Out-Null; return @{ ok = $true; message = "shutdown requested" } }
        if ($actionId -like "service.*") {
            if (-not $target) { return @{ ok = $false; message = "service target required" } }
            if ($allowed -notcontains $target.ToLower()) { return @{ ok = $false; message = "service not allowlisted: $target" } }
            $verb = $actionId.Split(".")[1]
            if ($verb -notin @("start", "stop", "restart")) {
                return @{ ok = $false; message = "unsupported service action: $verb" }
            }
            $message = Invoke-ScServiceControl -Name $target -Verb $verb
            return @{ ok = $true; message = $message }
        }
        if ($actionId -eq "agent.self_update") {
            $config = Get-AgentConfig
            $message = Invoke-AgentSelfUpdate -Action $Action -Config $config
            return @{ ok = $true; message = $message }
        }
        return @{ ok = $false; message = "unsupported action: $actionId" }
    } catch {
        Write-AgentLog "action failed ${actionId} ${target}: $($_.Exception.Message)"
        return @{ ok = $false; message = $_.Exception.Message }
    }
}

function Send-AgentHeartbeat {
    param($Config, $ActionResults)
    if (-not $Config.CoreUrl) { throw "Missing HCC core heartbeat URL in $EnvPath" }
    $snapshot = New-AgentSnapshot -Config $Config
    $node = $snapshot.node
    $node.ips = @($node.ips)
    $nodeJson = ConvertTo-Json $node -Compress -Depth 8
    if ($node.ips.Count -le 1) {
        $nodeJson = $nodeJson -replace '"ips"\s*:\s*"[^"]*"', ('"ips":' + (ConvertTo-JsonArray $node.ips))
        if ($node.ips.Count -eq 0 -and $nodeJson -notmatch '"ips"\s*:\s*\[') {
            $nodeJson = $nodeJson -replace '"ips"\s*:\s*[^,}]+', '"ips":[]'
        }
    }
    $payloadJson = "{"
    $payloadJson += '"node":' + $nodeJson + ","
    $caps = $snapshot.capabilities
    $payloadJson += '"capabilities":{"hostRole":"' + $caps.hostRole + '","deviceCategory":"' + $caps.deviceCategory + '","actions":' + (ConvertTo-JsonArray $caps.actions) + ',"sections":' + (ConvertTo-Json $caps.sections -Compress -Depth 4) + "},"
    $payloadJson += '"workloads":' + (ConvertTo-Json $snapshot.workloads -Compress -Depth 4) + ","
    $payloadJson += '"system":' + (ConvertTo-Json $snapshot.system -Compress -Depth 8) + ","
    $payloadJson += '"storage":' + (ConvertTo-JsonArray $snapshot.storage) + ","
    $payloadJson += '"storageDetail":' + (ConvertTo-Json $snapshot.storageDetail -Compress -Depth 8) + ","
    $payloadJson += '"services":' + (ConvertTo-JsonArray $snapshot.services) + ","
    $payloadJson += '"containers":' + (ConvertTo-JsonArray $snapshot.containers)
    $payloadJson += "}"
    $sentAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $messageId = "msg-$([int][double]::Parse((Get-Date -UFormat %s)))000"
    $bodyJson = "{"
    $bodyJson += '"schemaVersion":"v1",'
    $bodyJson += '"messageType":"heartbeat",'
    $bodyJson += """messageId"":""$messageId"","
    $bodyJson += """sentAt"":""$sentAt"","
    $bodyJson += """agentId"":""$($Config.AgentId)"","
    $bodyJson += """agentVersion"":""$($Config.AgentVersion)"","
    $bodyJson += """nodeId"":""$($Config.NodeId)"","
    $bodyJson += '"payload":' + $payloadJson
    if ($ActionResults) {
        $bodyJson += ',"actionResults":' + (ConvertTo-JsonArray $ActionResults)
    }
    $bodyJson += "}"
    $attempt = 0
    $maxAttempts = 3
    while ($attempt -lt $maxAttempts) {
        $attempt++
        try {
            return Invoke-RestMethod -Uri $Config.CoreUrl -Method Post -Body $bodyJson -ContentType "application/json" -TimeoutSec 20
        } catch {
            $message = $_.Exception.Message
            if ($attempt -lt $maxAttempts -and (Test-TransientWebError -Message $message)) {
                Start-Sleep -Seconds 5
                continue
            }
            throw
        }
    }
}

function Invoke-HeartbeatCycle {
    param($Config)
    $response = Send-AgentHeartbeat -Config $Config
    $pending = @($response.pendingActions)
    if ($pending.Count -gt 0) {
        $results = @()
        foreach ($action in $pending) {
            $result = Invoke-AgentAction -Action $action -Config $Config
            $results += @{
                requestId = [string]$action.requestId
                actionId = [string]$action.actionId
                target = $action.target
                ok = [bool]$result.ok
                message = [string]$result.message
            }
        }
        Send-AgentHeartbeat -Config $Config -ActionResults $results | Out-Null
        return "processed $($results.Count) action(s)"
    }
    return "heartbeat sent"
}

$config = Get-AgentConfig
if (-not $config.CoreUrl) {
    Write-AgentLog "Missing core URL in $EnvPath"
    throw "Missing HCC core URL. Configure $EnvPath first."
}

$existingState = Read-AgentState
$consecutiveFailures = 0
if ($existingState -and $existingState.consecutiveFailures) {
    $consecutiveFailures = [int]$existingState.consecutiveFailures
}

Write-AgentLog "hcc-agent starting for $($config.NodeId) -> $($config.CoreUrl) once=$($Once.IsPresent)"

do {
    try {
        $message = Invoke-HeartbeatCycle -Config $config
        $consecutiveFailures = 0
        Write-AgentState -Success $true -Message $message -ConsecutiveFailures 0
        Write-AgentLog $message
        Write-Host $message
    } catch {
        $consecutiveFailures++
        $errorMessage = $_.Exception.Message
        Write-AgentState -Success $false -Message $errorMessage -ConsecutiveFailures $consecutiveFailures
        Write-AgentLog "heartbeat failed ($consecutiveFailures): $errorMessage"
        Write-Host "heartbeat failed: $errorMessage"
    }

    if ($Once) { break }

    $sleepSeconds = if ($consecutiveFailures -le 0) {
        $config.Interval
    } else {
        Get-RetryDelaySeconds -Failures $consecutiveFailures -NormalInterval $config.Interval
    }
    Start-Sleep -Seconds $sleepSeconds
} while ($true)
