[CmdletBinding()]
param(
    [string]$AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")),
    [string]$PythonPath = "C:\brbots\python\python.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "deployment-policy.ps1")

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal -ArgumentList $identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Execute este script em PowerShell como Administrador."
}

& (Join-Path $PSScriptRoot "test-package-integrity.ps1") -AppRoot $AppRoot

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python nao encontrado: $PythonPath"
}
$runtimeJson = & $PythonPath -c "import json,platform,struct,sys; print(json.dumps({'implementation': platform.python_implementation(), 'major': sys.version_info.major, 'minor': sys.version_info.minor, 'bits': struct.calcsize('P') * 8}))"
if ($LASTEXITCODE -ne 0) { throw "Nao foi possivel consultar o runtime Python." }
$runtime = $runtimeJson | ConvertFrom-Json
Assert-SmartCrmRuntimeFacts -Implementation $runtime.implementation -Major $runtime.major -Minor $runtime.minor -Bits $runtime.bits

$postgresService = Get-Service -Name "postgresql-x64-11" -ErrorAction SilentlyContinue
if ($null -eq $postgresService -or $postgresService.Status -ne "Running") {
    throw "O servico postgresql-x64-11 precisa estar em execucao. Nenhuma alteracao foi feita nele."
}

$listeners = @(Get-NetTCPConnection -State Listen -LocalPort 5432 -ErrorAction SilentlyContinue)
Assert-SmartCrmPostgresListeners -Listeners $listeners

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
    $envLines = New-SmartCrmEnvironmentLines -Password $dbPassword
    [IO.File]::WriteAllLines($envPath, $envLines, (New-Object Text.UTF8Encoding($false)))
    Remove-Variable dbPassword
    icacls $envPath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
}

& (Join-Path $PSScriptRoot "start-smart-crm.ps1") -AppRoot $AppRoot -ValidateOnly
Write-Output "offline install: PASS"
Write-Output "Proximo passo: siga a secao 'Criar banco e role' do LEIA-ME.md."
