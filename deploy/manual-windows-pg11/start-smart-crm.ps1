[CmdletBinding()]
param(
    [string]$AppRoot = "C:\Apps\smart-crm",
    [string]$EnvFile = "C:\ProgramData\SmartCRM\server.env",
    [string]$LogDirectory = "C:\ProgramData\SmartCRM\logs",
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "deployment-policy.ps1")

$allowedKeys = @(
    "SMART_CRM_DB_NAME", "SMART_CRM_DB_USER", "SMART_CRM_DB_PASSWORD",
    "SMART_CRM_DB_HOST", "SMART_CRM_DB_PORT", "SMART_CRM_BIND_IP", "SMART_CRM_PORT"
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

$python = Join-Path $AppRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Virtualenv ausente: $python" }
if ($ValidateOnly) {
    Write-Output "smart crm environment: VALID"
    exit 0
}

$env:SMART_CRM_DATABASE_URL = "postgresql+psycopg://$($settings.SMART_CRM_DB_USER):$($settings.SMART_CRM_DB_PASSWORD)@127.0.0.1:5432/smartcrm?connect_timeout=5"
$env:SMART_CRM_TEST_MODE = "0"
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$logPath = Join-Path $LogDirectory "smart-crm.log"

Push-Location $AppRoot
try {
    $uvicornArguments = Get-SmartCrmUvicornArguments
    & $python @uvicornArguments *>> $logPath
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:SMART_CRM_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:SMART_CRM_TEST_MODE -ErrorAction SilentlyContinue
    Pop-Location
}
