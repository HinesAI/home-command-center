# Install HCC Local CA into LocalMachine\Root (idempotent by thumbprint).
param(
    [string]$CertPath = "",
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $InstallDir) {
    $InstallDir = Join-Path $env:ProgramFiles "HCC-Agent"
}
if (-not $CertPath) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $CertPath = Join-Path $ScriptDir "certs\HCC-Local-CA.crt"
}

if (-not (Test-Path $CertPath)) {
    Write-Host "HCC CA cert not found: $CertPath (skipping trust install)"
    return
}

$destDir = Join-Path $InstallDir "certs"
New-Item -ItemType Directory -Force -Path $destDir | Out-Null
$dest = Join-Path $destDir "HCC-Local-CA.crt"
Copy-Item -Path $CertPath -Destination $dest -Force

$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($dest)
$store = New-Object System.Security.Cryptography.X509Certificates.X509Store(
    [System.Security.Cryptography.X509Certificates.StoreName]::Root,
    [System.Security.Cryptography.X509Certificates.StoreLocation]::LocalMachine
)
$store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
try {
    $exists = $false
    foreach ($c in $store.Certificates) {
        if ($c.Thumbprint -eq $cert.Thumbprint) {
            $exists = $true
            break
        }
    }
    if (-not $exists) {
        $store.Add($cert)
        Write-Host "Installed HCC Local CA into LocalMachine\Root ($($cert.Thumbprint))"
    } else {
        Write-Host "HCC Local CA already trusted ($($cert.Thumbprint))"
    }
} finally {
    $store.Close()
}
