[CmdletBinding()]
param(
    [string]$AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),
    [string]$PythonPath = "C:\brbots\python\python.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal -ArgumentList $identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Execute este script em PowerShell como Administrador."
}

& (Join-Path $PSScriptRoot "test-package-integrity.ps1") -AppRoot $AppRoot

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python nao encontrado: $PythonPath"
}
& $PythonPath -c "import struct,sys; raise SystemExit(0 if sys.version_info[:2] == (3,11) and struct.calcsize('P') * 8 == 64 else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "O runtime deve ser CPython 3.11 x64. A virtualenv nao foi alterada."
}

$postgresService = Get-Service -Name "postgresql-x64-11" -ErrorAction SilentlyContinue
if ($null -eq $postgresService -or $postgresService.Status -ne "Running") {
    throw "O servico postgresql-x64-11 precisa estar em execucao. Nenhuma alteracao foi feita nele."
}

$listeners = @(Get-NetTCPConnection -State Listen -LocalPort 5432 -ErrorAction SilentlyContinue)
if ($listeners.Count -eq 0) {
    throw "PostgreSQL 11 nao esta ouvindo na porta 5432. Pare antes da migracao."
}
foreach ($listener in $listeners) {
    if ($listener.LocalAddress -notin @("127.0.0.1", "::1")) {
        throw "A porta 5432 esta exposta em $($listener.LocalAddress). Corrija a seguranca fora deste instalador."
    }
}

$psql = "C:\Program Files\PostgreSQL\11\bin\psql.exe"
if (-not (Test-Path -LiteralPath $psql -PathType Leaf)) {
    throw "psql do PostgreSQL 11 nao encontrado: $psql"
}

$wheelhouse = Join-Path $AppRoot "wheelhouse"
$requirements = Join-Path $AppRoot "requirements-runtime.txt"
if (-not (Test-Path -LiteralPath $wheelhouse -PathType Container)) {
    throw "Wheelhouse ausente: $wheelhouse"
}
if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
    throw "Dependencias fixadas ausentes: $requirements"
}

$venvPython = Join-Path $AppRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    & $PythonPath -m venv (Join-Path $AppRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Falha ao criar a virtualenv." }
}

& $venvPython -m pip install --disable-pip-version-check --no-index --find-links $wheelhouse -r $requirements
if ($LASTEXITCODE -ne 0) { throw "Falha na instalacao offline das dependencias." }
& $venvPython -m compileall -q (Join-Path $AppRoot "app")
if ($LASTEXITCODE -ne 0) { throw "Falha ao compilar a aplicacao." }

$programData = "C:\ProgramData\SmartCRM"
$envPath = Join-Path $programData "server.env"
New-Item -ItemType Directory -Path $programData -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $programData "logs") -Force | Out-Null

if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $dbPassword = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    $envLines = @(
        "SMART_CRM_DB_NAME=smartcrm",
        "SMART_CRM_DB_USER=smartcrm",
        "SMART_CRM_DB_PASSWORD=$dbPassword",
        "SMART_CRM_DB_HOST=127.0.0.1",
        "SMART_CRM_DB_PORT=5432",
        "SMART_CRM_BIND_IP=127.0.0.1",
        "SMART_CRM_PORT=8080"
    )
    [IO.File]::WriteAllLines($envPath, $envLines, (New-Object Text.UTF8Encoding($false)))
    Remove-Variable dbPassword
    icacls $envPath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
}

& (Join-Path $PSScriptRoot "start-smart-crm.ps1") -AppRoot $AppRoot -ValidateOnly
Write-Output "offline install: PASS"
Write-Output "Proximo passo: siga a secao 'Criar banco e role' do LEIA-ME.md."
