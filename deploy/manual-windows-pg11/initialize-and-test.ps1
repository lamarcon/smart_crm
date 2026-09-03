[CmdletBinding()]
param(
    [string]$AppRoot = "C:\Apps\smart-crm",
    [string]$EnvFile = "C:\ProgramData\SmartCRM\server.env",
    [string]$PsqlPath = "C:\Program Files\PostgreSQL\11\bin\psql.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

& (Join-Path $PSScriptRoot "start-smart-crm.ps1") -AppRoot $AppRoot -EnvFile $EnvFile -ValidateOnly
$settings = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -and -not $_.StartsWith("#") } | Out-String | ConvertFrom-StringData
$env:PGPASSWORD = $settings.SMART_CRM_DB_PASSWORD
$env:SMART_CRM_DATABASE_URL = "postgresql+psycopg://smartcrm:$($settings.SMART_CRM_DB_PASSWORD)@127.0.0.1:5432/smartcrm?connect_timeout=5"

try {
    & $PsqlPath -h 127.0.0.1 -p 5432 -U smartcrm -d smartcrm -v ON_ERROR_STOP=1 -c "SELECT current_database(), current_user;"
    if ($LASTEXITCODE -ne 0) { throw "Role ou database smartcrm ainda nao esta pronto." }

    Push-Location $AppRoot
    try {
        & ".\.venv\Scripts\python.exe" -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "Migracao Alembic falhou. Apache permanece inalterado." }
        & ".\.venv\Scripts\python.exe" -m alembic current
        if ($LASTEXITCODE -ne 0) { throw "Nao foi possivel confirmar o head do Alembic." }
    }
    finally { Pop-Location }

    & (Join-Path $PSScriptRoot "install-scheduled-task.ps1") -AppRoot $AppRoot
    Start-Sleep -Seconds 5
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/health"
    if ($health.status -ne "ok" -or $health.database -ne "ok") {
        throw "Health local invalido. Apache permanece inalterado."
    }
    Write-Output '{"status":"ok","database":"ok"}'
    Write-Output "LOCAL GATE: PASS. O Apache pode ser configurado."
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:SMART_CRM_DATABASE_URL -ErrorAction SilentlyContinue
}
