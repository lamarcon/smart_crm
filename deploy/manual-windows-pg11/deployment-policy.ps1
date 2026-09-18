Set-StrictMode -Version Latest

function Assert-SmartCrmRuntimeFacts {
    param(
        [string]$Implementation,
        [int]$Major,
        [int]$Minor,
        [int]$Bits
    )
    if ($Implementation -ne "CPython" -or $Major -ne 3 -or $Minor -ne 11 -or $Bits -ne 64) {
        throw "O runtime deve ser CPython 3.11 x64. A virtualenv nao foi alterada."
    }
}

function Assert-SmartCrmPostgresListeners {
    param([object[]]$Listeners)
    $ipv4Loopback = @($Listeners | Where-Object { $_.LocalAddress -eq "127.0.0.1" })
    if ($ipv4Loopback.Count -eq 0) {
        throw "PostgreSQL 11 nao esta ouvindo em 127.0.0.1:5432. Pare antes da migracao."
    }
    $unsafe = @($Listeners | Where-Object { $_.LocalAddress -notin @("127.0.0.1", "::1") })
    if ($unsafe.Count -gt 0) {
        throw "A porta 5432 esta exposta em $($unsafe[0].LocalAddress). Corrija a seguranca fora deste instalador."
    }
}

function New-SmartCrmEnvironmentLines {
    param([string]$Password)
    if ($Password -notmatch "^[0-9a-fA-F]{64}$") {
        throw "A senha do banco deve conter 64 caracteres hexadecimais."
    }
    return @(
        "SMART_CRM_DB_NAME=smartcrm",
        "SMART_CRM_DB_USER=smartcrm",
        "SMART_CRM_DB_PASSWORD=$Password",
        "SMART_CRM_DB_HOST=127.0.0.1",
        "SMART_CRM_DB_PORT=5432",
        "SMART_CRM_BIND_IP=127.0.0.1",
        "SMART_CRM_PORT=8080"
    )
}

function Get-SmartCrmControlAlembicUpgradeArguments {
    return @("-m", "alembic", "-c", "alembic-control.ini", "upgrade", "c01a5d8e4f20")
}

function Get-SmartCrmControlAlembicCurrentArguments {
    return @("-m", "alembic", "-c", "alembic-control.ini", "current")
}

function Get-SmartCrmTenantAlembicUpgradeArguments {
    return @("-m", "alembic", "-c", "alembic.ini", "upgrade", "a4c9d2e7f1b6")
}

function Get-SmartCrmTenantAlembicCurrentArguments {
    return @("-m", "alembic", "-c", "alembic.ini", "current")
}

function Assert-SmartCrmAlembicRevision {
    param(
        [object[]]$Output,
        [string]$ExpectedRevision,
        [string]$DatabaseLabel
    )
    $text = @($Output) -join [Environment]::NewLine
    $pattern = "(?m)^\s*" + [regex]::Escape($ExpectedRevision) + "\s+\(head\)\s*$"
    if (-not [regex]::IsMatch($text, $pattern)) {
        throw "Revisao Alembic inesperada para $DatabaseLabel."
    }
}

function Get-SmartCrmUvicornArguments {
    return @(
        "-m", "uvicorn", "app.server:create_central_app", "--factory",
        "--host", "127.0.0.1", "--port", "8080",
        "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"
    )
}

function Assert-SmartCrmCommandSucceeded {
    param(
        [int]$ExitCode,
        [string]$FailureMessage
    )
    if ($ExitCode -ne 0) {
        throw $FailureMessage
    }
}

function Test-SmartCrmHealth {
    param([object]$Health)
    return $Health.status -eq "ok" -and $Health.database -eq "ok"
}
