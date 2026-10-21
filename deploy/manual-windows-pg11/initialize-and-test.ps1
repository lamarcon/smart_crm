[CmdletBinding()]
param(
    [string]$AppRoot = "C:\brbots\apps\smart-crm",
    [string]$EnvFile = "C:\ProgramData\SmartCRM\server.env",
    [string]$PsqlPath = "C:\Program Files\PostgreSQL\11\bin\psql.exe",
    [switch]$SharedPostgres,
    [string]$PgHbaPath,
    [Parameter(Mandatory = $true)]
    [PSCredential]$ServiceCredential
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "deployment-policy.ps1")

$listeners = @(Get-NetTCPConnection -State Listen -LocalPort 5432 -ErrorAction SilentlyContinue)
$pgHbaText = ""
if ($SharedPostgres) {
    if ([string]::IsNullOrWhiteSpace($PgHbaPath) -or -not (Test-Path -LiteralPath $PgHbaPath -PathType Leaf)) {
        throw "Modo PostgreSQL compartilhado exige -PgHbaPath valido."
    }
    $pgHbaText = [IO.File]::ReadAllText($PgHbaPath)
}
Assert-SmartCrmPostgresListeners -Listeners $listeners -SharedPostgres:$SharedPostgres -PgHbaText $pgHbaText

& (Join-Path $PSScriptRoot "start-smart-crm.ps1") -AppRoot $AppRoot -EnvFile $EnvFile -ValidateOnly
$settings = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -and -not $_.StartsWith("#") } | Out-String | ConvertFrom-StringData
$env:PGPASSWORD = $settings.SMART_CRM_DB_PASSWORD
$env:SMART_CRM_CONTROL_DATABASE_URL = $settings.SMART_CRM_CONTROL_DATABASE_URL
$env:SMART_CRM_DATABASE_URL = "postgresql+psycopg://smartcrm:$($settings.SMART_CRM_DB_PASSWORD)@127.0.0.1:5432/smartcrm?connect_timeout=5"

try {
    & $PsqlPath -h 127.0.0.1 -p 5432 -U smartcrm -d smartcrm -v ON_ERROR_STOP=1 -c "SELECT current_database(), current_user;"
    if ($LASTEXITCODE -ne 0) { throw "Role ou database smartcrm ainda nao esta pronto." }

    Push-Location $AppRoot
    try {
        $controlUpgrade = Get-SmartCrmControlAlembicUpgradeArguments
        & ".\.venv\Scripts\python.exe" @controlUpgrade
        Assert-SmartCrmCommandSucceeded -ExitCode $LASTEXITCODE -FailureMessage "Migracao do banco de controle falhou. Apache permanece inalterado."

        $controlCurrent = Get-SmartCrmControlAlembicCurrentArguments
        $controlRevision = & ".\.venv\Scripts\python.exe" @controlCurrent 2>&1
        Assert-SmartCrmCommandSucceeded -ExitCode $LASTEXITCODE -FailureMessage "Nao foi possivel confirmar a revisao do banco de controle."
        Assert-SmartCrmAlembicRevision -Output $controlRevision -ExpectedRevision "c01a5d8e4f20" -DatabaseLabel "controle"

        $tenantUpgrade = Get-SmartCrmTenantAlembicUpgradeArguments
        & ".\.venv\Scripts\python.exe" @tenantUpgrade
        Assert-SmartCrmCommandSucceeded -ExitCode $LASTEXITCODE -FailureMessage "Migracao do banco tenant smartcrm falhou. Apache permanece inalterado."

        $tenantCurrent = Get-SmartCrmTenantAlembicCurrentArguments
        $tenantRevision = & ".\.venv\Scripts\python.exe" @tenantCurrent 2>&1
        Assert-SmartCrmCommandSucceeded -ExitCode $LASTEXITCODE -FailureMessage "Nao foi possivel confirmar a revisao do banco tenant smartcrm."
        Assert-SmartCrmAlembicRevision -Output $tenantRevision -ExpectedRevision "f6b1d3a8c2e4" -DatabaseLabel "tenant smartcrm"
    }
    finally { Pop-Location }

    & (Join-Path $PSScriptRoot "install-scheduled-task.ps1") -AppRoot $AppRoot -ServiceCredential $ServiceCredential
    Start-Sleep -Seconds 5
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/health"
    if (-not (Test-SmartCrmHealth -Health $health)) {
        throw "Health local invalido. Apache permanece inalterado."
    }
    Write-Output '{"status":"ok","database":"ok"}'
    Write-Output "LOCAL GATE: PASS. O Apache pode ser configurado."
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:SMART_CRM_CONTROL_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:SMART_CRM_DATABASE_URL -ErrorAction SilentlyContinue
}
