[CmdletBinding()]
param(
    [string]$AppRoot = "C:\brbots\apps\smart-crm",
    [string]$EnvFile = "C:\ProgramData\SmartCRM\server.env",
    [string]$LogDirectory = "C:\ProgramData\SmartCRM\logs",
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "deployment-policy.ps1")

$allowedKeys = @(
    "SMART_CRM_DB_NAME", "SMART_CRM_DB_USER", "SMART_CRM_DB_PASSWORD",
    "SMART_CRM_DB_HOST", "SMART_CRM_DB_PORT", "SMART_CRM_BIND_IP", "SMART_CRM_PORT",
    "SMART_CRM_CONTROL_DATABASE_URL", "SMART_CRM_TENANT_SECRET_STORE",
    "SMART_CRM_EXPECTED_ORIGIN", "SMART_CRM_TENANT_MAX_CACHED_ENGINES",
    "SMART_CRM_TENANT_POOL_SIZE", "SMART_CRM_TENANT_MAX_OVERFLOW",
    "SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS", "SMART_CRM_TENANT_CONNECT_TIMEOUT_SECONDS",
    "SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK"
)

$runtimeKeys = @(
    "SMART_CRM_CONTROL_DATABASE_URL", "SMART_CRM_TENANT_SECRET_STORE",
    "SMART_CRM_EXPECTED_ORIGIN", "SMART_CRM_TENANT_MAX_CACHED_ENGINES",
    "SMART_CRM_TENANT_POOL_SIZE", "SMART_CRM_TENANT_MAX_OVERFLOW",
    "SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS", "SMART_CRM_TENANT_CONNECT_TIMEOUT_SECONDS",
    "SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK"
)

function Read-SmartCrmEnvironment {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Arquivo de ambiente nao encontrado: $Path"
    }
    $values = @{}
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) { continue }
        if ($line -notmatch "^(?<Key>[A-Z0-9_]+)=(?<Value>.*)$") {
            throw "Linha invalida no arquivo de ambiente."
        }
        $key = $Matches.Key
        if ($key -notin $allowedKeys) { throw "Variavel nao permitida: $key" }
        if ($values.ContainsKey($key)) { throw "Variavel duplicada: $key" }
        $values[$key] = $Matches.Value.Trim()
    }
    return $values
}

$settings = Read-SmartCrmEnvironment -Path $EnvFile
foreach ($requiredKey in $allowedKeys) {
    if (-not $settings.ContainsKey($requiredKey) -or -not $settings[$requiredKey]) {
        throw "Variavel obrigatoria ausente: $requiredKey"
    }
}

if ($settings.SMART_CRM_DB_NAME -ne "smartcrm") { throw "SMART_CRM_DB_NAME deve ser smartcrm." }
if ($settings.SMART_CRM_DB_USER -ne "smartcrm") { throw "SMART_CRM_DB_USER deve ser smartcrm." }
if ($settings.SMART_CRM_DB_PASSWORD -notmatch "^[0-9a-fA-F]{64}$") { throw "Senha deve ter 64 caracteres hexadecimais." }
if ($settings.SMART_CRM_DB_HOST -ne "127.0.0.1") { throw "Banco deve usar 127.0.0.1." }
if ($settings.SMART_CRM_DB_PORT -ne "5432") { throw "Banco deve usar a porta 5432." }
if ($settings.SMART_CRM_BIND_IP -ne "127.0.0.1") { throw "Uvicorn deve usar 127.0.0.1." }
if ($settings.SMART_CRM_PORT -ne "8080") { throw "Uvicorn deve usar a porta 8080." }
if ($settings.SMART_CRM_CONTROL_DATABASE_URL -eq "REPLACE_WITH_CONTROL_DATABASE_URL" -or
    $settings.SMART_CRM_CONTROL_DATABASE_URL -notmatch "^postgresql\+psycopg://[^\s]+$") {
    throw "SMART_CRM_CONTROL_DATABASE_URL invalida."
}
if ($settings.SMART_CRM_TENANT_SECRET_STORE -ne "C:\ProgramData\SmartCRM\tenant-secrets") {
    throw "SMART_CRM_TENANT_SECRET_STORE deve ficar em C:\ProgramData\SmartCRM\tenant-secrets."
}
if ($settings.SMART_CRM_EXPECTED_ORIGIN -ne "https://sc2030.brbots.com") {
    throw "SMART_CRM_EXPECTED_ORIGIN deve usar a origem HTTPS de producao."
}
if ($settings.SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK -ne "1") {
    throw "SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK deve ser 1 para o tenant local aprovado."
}

foreach ($key in @(
    "SMART_CRM_TENANT_MAX_CACHED_ENGINES", "SMART_CRM_TENANT_POOL_SIZE",
    "SMART_CRM_TENANT_CONNECT_TIMEOUT_SECONDS"
)) {
    $parsed = 0
    if (-not [int]::TryParse($settings[$key], [ref]$parsed) -or $parsed -le 0) {
        throw "$key deve ser um inteiro positivo."
    }
}
$maxOverflow = 0
if (-not [int]::TryParse($settings.SMART_CRM_TENANT_MAX_OVERFLOW, [ref]$maxOverflow) -or
    $maxOverflow -le 0) {
    throw "SMART_CRM_TENANT_MAX_OVERFLOW deve ser um inteiro positivo."
}
$poolTimeout = 0.0
if (-not [double]::TryParse(
    $settings.SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS,
    [Globalization.NumberStyles]::Float,
    [Globalization.CultureInfo]::InvariantCulture,
    [ref]$poolTimeout
) -or $poolTimeout -le 0) {
    throw "SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS deve ser positivo."
}

$python = Join-Path $AppRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Virtualenv ausente: $python" }
if ($ValidateOnly) {
    Write-Output "smart crm environment: VALID"
    exit 0
}

foreach ($key in $runtimeKeys) {
    [Environment]::SetEnvironmentVariable($key, $settings[$key], "Process")
}
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$logPath = Join-Path $LogDirectory "smart-crm.log"

Push-Location $AppRoot
try {
    $uvicornArguments = Get-SmartCrmUvicornArguments
    $exitCode = Invoke-SmartCrmLoggedProcess `
        -FilePath $python `
        -ArgumentList $uvicornArguments `
        -LogPath $logPath
    exit $exitCode
}
finally {
    foreach ($key in $runtimeKeys) {
        [Environment]::SetEnvironmentVariable($key, $null, "Process")
    }
    Pop-Location
}
