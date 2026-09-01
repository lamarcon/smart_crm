[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),
    [string]$EnvFile = "C:\ProgramData\SmartCRM\server.env",
    [string]$LogDirectory = "C:\ProgramData\SmartCRM\logs",
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$allowedKeys = @(
    "SMART_CRM_DB_NAME",
    "SMART_CRM_DB_USER",
    "SMART_CRM_DB_PASSWORD",
    "SMART_CRM_DB_HOST",
    "SMART_CRM_DB_PORT",
    "SMART_CRM_BIND_IP",
    "SMART_CRM_PORT"
)

function Read-SmartCrmEnvironment {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Arquivo de ambiente não encontrado: $Path"
    }

    $values = @{}
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        if ($line -notmatch "^(?<Key>[A-Z0-9_]+)=(?<Value>.*)$") {
            throw "Linha inválida no arquivo de ambiente."
        }
        $key = $Matches.Key
        if ($key -notin $allowedKeys) {
            throw "Variável não permitida no arquivo de ambiente: $key"
        }
        if ($values.ContainsKey($key)) {
            throw "Variável duplicada no arquivo de ambiente: $key"
        }
        $values[$key] = $Matches.Value.Trim()
    }
    return $values
}

$settings = Read-SmartCrmEnvironment -Path $EnvFile
foreach ($requiredKey in $allowedKeys) {
    if (-not $settings.ContainsKey($requiredKey) -or -not $settings[$requiredKey]) {
        throw "Variável obrigatória ausente: $requiredKey"
    }
}

if ($settings.SMART_CRM_DB_NAME -notmatch "^[a-z_][a-z0-9_]{0,62}$") {
    throw "SMART_CRM_DB_NAME inválido."
}
if ($settings.SMART_CRM_DB_USER -notmatch "^[a-z_][a-z0-9_]{0,62}$") {
    throw "SMART_CRM_DB_USER inválido."
}
if ($settings.SMART_CRM_DB_PASSWORD -notmatch "^[0-9a-fA-F]{64}$") {
    throw "SMART_CRM_DB_PASSWORD deve conter exatamente 64 caracteres hexadecimais."
}
if ($settings.SMART_CRM_DB_HOST -ne "127.0.0.1") {
    throw "SMART_CRM_DB_HOST deve ser 127.0.0.1."
}
if ($settings.SMART_CRM_BIND_IP -ne "127.0.0.1") {
    throw "SMART_CRM_BIND_IP deve ser 127.0.0.1."
}
if ($settings.SMART_CRM_DB_PORT -notmatch "^[0-9]+$" -or
    [int]$settings.SMART_CRM_DB_PORT -lt 1 -or
    [int]$settings.SMART_CRM_DB_PORT -gt 65535) {
    throw "SMART_CRM_DB_PORT inválido."
}
if ($settings.SMART_CRM_PORT -ne "8080") {
    throw "SMART_CRM_PORT deve ser 8080."
}

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python da virtualenv não encontrado: $python"
}

if ($ValidateOnly) {
    Write-Output "smart crm windows environment: VALID"
    exit 0
}

$databaseUrl = "postgresql+psycopg://$($settings.SMART_CRM_DB_USER):$($settings.SMART_CRM_DB_PASSWORD)@127.0.0.1:$($settings.SMART_CRM_DB_PORT)/$($settings.SMART_CRM_DB_NAME)?connect_timeout=5"
$env:SMART_CRM_DATABASE_URL = $databaseUrl
$env:SMART_CRM_TEST_MODE = "0"

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$logPath = Join-Path $LogDirectory "smart-crm.log"

Push-Location $RepoRoot
try {
    & $python -m uvicorn app.main:create_app --factory `
        --host "127.0.0.1" `
        --port "8080" `
        --proxy-headers `
        --forwarded-allow-ips "127.0.0.1" *>> $logPath
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
