[CmdletBinding()]
param(
    [string]$AppRoot = "C:\brbots\apps\smart-crm",
    [string]$EnvFile = "C:\ProgramData\SmartCRM\server.env",
    [string]$PsqlPath = "C:\Program Files\PostgreSQL\11\bin\psql.exe",
    [switch]$SharedPostgres,
    [string]$PgHbaPath,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[a-z0-9][a-z0-9-]{0,62}$")]
    [string]$TenantSlug,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ExpectedVersion,
    [switch]$BackupAcknowledged,
    [string]$TaskName = "SmartCRM",
    [string]$EvidenceDirectory = "C:\ProgramData\SmartCRM\deploy",
    [string]$RecoveryDirectory = "C:\ProgramData\SmartCRM\recovery",
    [double]$MigrationTimeoutSeconds = 300,
    [double]$CutoverTimeoutSeconds = 30,
    [int]$PollMilliseconds = 500,
    [Parameter(Mandatory = $true)]
    [PSCredential]$ServiceCredential
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "deployment-policy.ps1")

if (-not $BackupAcknowledged) {
    throw "A confirmacao de backup verificado e obrigatoria."
}
if ($MigrationTimeoutSeconds -le 0 -or
    $CutoverTimeoutSeconds -le 0 -or
    $PollMilliseconds -lt 1) {
    throw "Os limites de espera do deploy sao invalidos."
}

$listeners = @(Get-NetTCPConnection -State Listen -LocalPort 5432 -ErrorAction SilentlyContinue)
$pgHbaText = ""
if ($SharedPostgres) {
    if ([string]::IsNullOrWhiteSpace($PgHbaPath) -or
        -not (Test-Path -LiteralPath $PgHbaPath -PathType Leaf)) {
        throw "Modo PostgreSQL compartilhado exige -PgHbaPath valido."
    }
    $pgHbaText = [IO.File]::ReadAllText($PgHbaPath)
}
Assert-SmartCrmPostgresListeners `
    -Listeners $listeners `
    -SharedPostgres:$SharedPostgres `
    -PgHbaText $pgHbaText

& (Join-Path $PSScriptRoot "start-smart-crm.ps1") `
    -AppRoot $AppRoot `
    -EnvFile $EnvFile `
    -ValidateOnly

$settings = Read-SmartCrmEnvironment `
    -Path $EnvFile `
    -AllowedKeys @(Get-SmartCrmEnvironmentAllowedKeys)
$previousPgPassword = [Environment]::GetEnvironmentVariable("PGPASSWORD", "Process")
$previousControlUrl = [Environment]::GetEnvironmentVariable(
    "SMART_CRM_CONTROL_DATABASE_URL",
    "Process"
)
$env:PGPASSWORD = $settings["SMART_CRM_DB_PASSWORD"]
$env:SMART_CRM_CONTROL_DATABASE_URL = `
    $settings["SMART_CRM_CONTROL_DATABASE_URL"]

$previousTaskXml = $null
$recoveryPath = $null

try {
    $databaseCheck = Invoke-SmartCrmNativeProcess `
        -FilePath $PsqlPath `
        -ArgumentList @(
            "-h", $settings["SMART_CRM_DB_HOST"],
            "-p", $settings["SMART_CRM_DB_PORT"],
            "-U", $settings["SMART_CRM_DB_USER"],
            "-d", $settings["SMART_CRM_DB_NAME"],
            "-v", "ON_ERROR_STOP=1",
            "-c", "SELECT current_database(), current_user;"
        )
    Assert-SmartCrmCommandSucceeded `
        -ExitCode $databaseCheck.ExitCode `
        -FailureMessage "Role ou database smartcrm ainda nao esta pronto."

    $python = Join-Path $AppRoot ".venv\Scripts\python.exe"
    $controlUpgrade = Get-SmartCrmControlAlembicUpgradeArguments
    $controlUpgradeResult = Invoke-SmartCrmNativeProcess `
        -FilePath $python `
        -ArgumentList $controlUpgrade `
        -WorkingDirectory $AppRoot
    Assert-SmartCrmCommandSucceeded `
        -ExitCode $controlUpgradeResult.ExitCode `
        -FailureMessage "Migracao do banco de controle falhou. A tarefa web permanece inalterada."

    $controlCurrent = Get-SmartCrmControlAlembicCurrentArguments
    $controlCurrentResult = Invoke-SmartCrmNativeProcess `
        -FilePath $python `
        -ArgumentList $controlCurrent `
        -WorkingDirectory $AppRoot
    Assert-SmartCrmCommandSucceeded `
        -ExitCode $controlCurrentResult.ExitCode `
        -FailureMessage "Nao foi possivel confirmar a revisao do banco de controle."
    Assert-SmartCrmAlembicRevision `
        -Output @($controlCurrentResult.StdOut, $controlCurrentResult.StdErr) `
        -ExpectedRevision "d5f0a8c3e7b2" `
        -DatabaseLabel "controle"

    & (Join-Path $PSScriptRoot "invoke-fleet-migration-task.ps1") `
        -AppRoot $AppRoot `
        -EnvFile $EnvFile `
        -TenantSlug $TenantSlug `
        -EvidenceDirectory $EvidenceDirectory `
        -ServiceCredential $ServiceCredential `
        -BackupAcknowledged `
        -TimeoutSeconds $MigrationTimeoutSeconds `
        -PollMilliseconds $PollMilliseconds

    $previousTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $previousTaskXml = Export-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    New-Item -ItemType Directory -Path $RecoveryDirectory -Force | Out-Null
    $recoveryToken = "{0}-{1}" -f `
        (Get-Date -Format "yyyyMMdd-HHmmss"), `
        ([guid]::NewGuid().ToString("N").Substring(0, 8))
    $recoveryPath = Join-Path `
        $RecoveryDirectory `
        "$TaskName-pre-$recoveryToken.xml"
    [System.IO.File]::WriteAllText(
        $recoveryPath,
        $previousTaskXml,
        (New-Object System.Text.UTF8Encoding($false))
    )

    try {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        Wait-SmartCrmPortReleased `
            -Port 8080 `
            -TimeoutSeconds $CutoverTimeoutSeconds `
            -PollMilliseconds $PollMilliseconds

        & (Join-Path $PSScriptRoot "install-scheduled-task.ps1") `
            -AppRoot $AppRoot `
            -TaskName $TaskName `
            -ServiceCredential $ServiceCredential

        $activeTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        Assert-SmartCrmScheduledTaskTarget `
            -Task $activeTask `
            -ExpectedUser $ServiceCredential.UserName `
            -ExpectedAppRoot $AppRoot
        $readiness = Wait-SmartCrmReleaseReady `
            -ExpectedVersion $ExpectedVersion `
            -TimeoutSeconds $CutoverTimeoutSeconds `
            -PollMilliseconds $PollMilliseconds

        Write-Output ($readiness.Health | ConvertTo-Json -Compress)
        Write-Output "LOCAL GATE: PASS release=$ExpectedVersion tenant=$TenantSlug"
    }
    catch {
        $cutoverFailure = $_.Exception.Message
        $restoreFailure = $null
        $servicePassword = $null
        try {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            Wait-SmartCrmPortReleased `
                -Port 8080 `
                -TimeoutSeconds $CutoverTimeoutSeconds `
                -PollMilliseconds $PollMilliseconds
            $servicePassword = $ServiceCredential.GetNetworkCredential().Password
            Register-ScheduledTask `
                -TaskName $TaskName `
                -Xml $previousTaskXml `
                -User $ServiceCredential.UserName `
                -Password $servicePassword `
                -Force | Out-Null
            Start-ScheduledTask -TaskName $TaskName
        }
        catch {
            $restoreFailure = $_.Exception.Message
        }
        finally {
            $servicePassword = $null
        }

        if ($restoreFailure) {
            throw "O cutover falhou: $cutoverFailure A restauracao automatica tambem falhou: $restoreFailure Use o XML preservado em $recoveryPath."
        }
        throw "O cutover falhou e a tarefa anterior foi restaurada: $cutoverFailure"
    }
}
finally {
    [Environment]::SetEnvironmentVariable(
        "PGPASSWORD",
        $previousPgPassword,
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "SMART_CRM_CONTROL_DATABASE_URL",
        $previousControlUrl,
        "Process"
    )
}
