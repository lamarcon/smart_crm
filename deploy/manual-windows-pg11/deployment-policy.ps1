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

function Get-SmartCrmSharedPostgresHbaRules {
    return @(
        "host smartcrm,smartcrm_control all 127.0.0.1/32 md5",
        "host smartcrm,smartcrm_control all ::1/128 md5",
        "host smartcrm,smartcrm_control all 0.0.0.0/0 reject",
        "host smartcrm,smartcrm_control all ::/0 reject"
    )
}

function Assert-SmartCrmSharedPostgresHba {
    param([string]$PgHbaText)
    if ([string]::IsNullOrWhiteSpace($PgHbaText)) {
        throw "Modo PostgreSQL compartilhado exige o conteudo de pg_hba.conf."
    }

    $hostRules = @()
    foreach ($rawLine in ($PgHbaText -split "`r?`n")) {
        $line = (($rawLine -replace "#.*$", "").Trim() -split "\s+") -join " "
        if ($line -match "^host(?:ssl|nossl)?\s") {
            $hostRules += $line.ToLowerInvariant()
        }
    }
    $requiredRules = @(Get-SmartCrmSharedPostgresHbaRules)
    if ($hostRules.Count -lt $requiredRules.Count) {
        throw "pg_hba.conf nao contem a fronteira local obrigatoria do Smart CRM."
    }
    for ($index = 0; $index -lt $requiredRules.Count; $index += 1) {
        if ($hostRules[$index] -ne $requiredRules[$index].ToLowerInvariant()) {
            throw "As primeiras regras host de pg_hba.conf devem proteger somente os databases do Smart CRM."
        }
    }
}

function Assert-SmartCrmPostgresListeners {
    param(
        [object[]]$Listeners,
        [switch]$SharedPostgres,
        [string]$PgHbaText
    )
    $ipv4Loopback = @($Listeners | Where-Object { $_.LocalAddress -eq "127.0.0.1" })
    $ipv4Wildcard = @($Listeners | Where-Object { $_.LocalAddress -eq "0.0.0.0" })
    if ($SharedPostgres) {
        if ($ipv4Loopback.Count -eq 0 -and $ipv4Wildcard.Count -eq 0) {
            throw "PostgreSQL 11 nao aceita conexao IPv4 local na porta 5432."
        }
        Assert-SmartCrmSharedPostgresHba -PgHbaText $PgHbaText
        return
    }
    if ($ipv4Loopback.Count -eq 0) {
        throw "PostgreSQL 11 nao esta ouvindo em 127.0.0.1:5432. Pare antes da migracao."
    }
    $unsafe = @($Listeners | Where-Object { $_.LocalAddress -notin @("127.0.0.1", "::1") })
    if ($unsafe.Count -gt 0) {
        throw "A porta 5432 esta exposta em $($unsafe[0].LocalAddress). Corrija a seguranca fora deste instalador."
    }
}

function New-SmartCrmEnvironmentLines {
    param(
        [string]$Password,
        [string]$ControlPassword
    )
    if ($Password -notmatch "^[0-9a-fA-F]{64}$") {
        throw "A senha do banco deve conter 64 caracteres hexadecimais."
    }
    if ($ControlPassword -notmatch "^[0-9a-fA-F]{64}$") {
        throw "A senha do banco de controle deve conter 64 caracteres hexadecimais."
    }
    return @(
        "SMART_CRM_DB_NAME=smartcrm",
        "SMART_CRM_DB_USER=smartcrm",
        "SMART_CRM_DB_PASSWORD=$Password",
        "SMART_CRM_DB_HOST=127.0.0.1",
        "SMART_CRM_DB_PORT=5432",
        "SMART_CRM_BIND_IP=127.0.0.1",
        "SMART_CRM_PORT=8080",
        "SMART_CRM_CONTROL_DATABASE_URL=postgresql+psycopg://smartcrm_control:$ControlPassword@127.0.0.1:5432/smartcrm_control?connect_timeout=5",
        "SMART_CRM_TENANT_SECRET_STORE=C:\ProgramData\SmartCRM\tenant-secrets",
        "SMART_CRM_EXPECTED_ORIGIN=https://sc2030.brbots.com",
        "SMART_CRM_TENANT_MAX_CACHED_ENGINES=16",
        "SMART_CRM_TENANT_POOL_SIZE=2",
        "SMART_CRM_TENANT_MAX_OVERFLOW=2",
        "SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS=5",
        "SMART_CRM_TENANT_CONNECT_TIMEOUT_SECONDS=3",
        "SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK=1"
    )
}

function Get-SmartCrmControlAlembicUpgradeArguments {
    return @("-m", "alembic", "-c", "alembic-control.ini", "upgrade", "c01a5d8e4f20")
}

function Get-SmartCrmControlAlembicCurrentArguments {
    return @("-m", "alembic", "-c", "alembic-control.ini", "current")
}

function Get-SmartCrmTenantAlembicUpgradeArguments {
    return @("-m", "alembic", "-c", "alembic.ini", "upgrade", "e1c4a7b9d2f6")
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
