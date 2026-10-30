[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AppRoot,
    [Parameter(Mandatory = $true)]
    [string]$EnvFile,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[a-z0-9][a-z0-9-]{0,62}$")]
    [string]$TenantSlug,
    [string]$EvidenceDirectory = "C:\ProgramData\SmartCRM\deploy",
    [Parameter(Mandatory = $true)]
    [PSCredential]$ServiceCredential,
    [switch]$BackupAcknowledged,
    [double]$TimeoutSeconds = 300,
    [int]$PollMilliseconds = 500
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $BackupAcknowledged) {
    throw "A confirmacao de backup verificado e obrigatoria."
}
if ($TimeoutSeconds -le 0 -or $PollMilliseconds -lt 1) {
    throw "Parametros de espera da tarefa temporaria sao invalidos."
}

$serviceUser = $ServiceCredential.UserName.Trim()
$accountParts = @($serviceUser -split "\\")
if ($accountParts.Count -ne 2 -or $accountParts[-1] -ine "SmartCRMService") {
    throw "Informe a conta dedicada SmartCRMService com nome qualificado."
}
$servicePassword = $ServiceCredential.GetNetworkCredential().Password
if (-not $servicePassword) {
    throw "A credencial da conta dedicada nao pode estar vazia."
}

$runner = Join-Path $AppRoot "deploy\manual-windows-pg11\run-fleet-migration.ps1"
$python = Join-Path $AppRoot ".venv\Scripts\python.exe"
foreach ($requiredFile in @($runner, $python, $EnvFile)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Arquivo obrigatorio da migracao nao encontrado."
    }
    if ($requiredFile.Contains('"')) {
        throw "Caminho da migracao contem caractere invalido."
    }
}
if ($EvidenceDirectory.Contains('"')) {
    throw "Caminho da evidencia contem caractere invalido."
}

function Assert-SmartCrmFleetTaskEvidence {
    param(
        [object]$Evidence,
        [string]$ExpectedReleasePath,
        [string]$ExpectedTenant
    )
    foreach ($propertyName in @(
        "schemaVersion", "releasePath", "targetRevision", "tenants", "exitCode"
    )) {
        if ($null -eq $Evidence.PSObject.Properties[$propertyName]) {
            throw "Evidencia da migracao esta incompleta."
        }
    }
    if ([int]$Evidence.schemaVersion -ne 1 -or
        [string]$Evidence.releasePath -ine $ExpectedReleasePath -or
        [string]$Evidence.targetRevision -notmatch "^[a-z0-9]{12,64}$" -or
        [int]$Evidence.exitCode -ne 0) {
        throw "Evidencia da migracao nao corresponde a operacao solicitada."
    }
    $tenants = @($Evidence.tenants)
    if ($tenants.Count -ne 1) {
        throw "Evidencia da migracao possui selecao tenant inesperada."
    }
    $tenant = $tenants[0]
    foreach ($propertyName in @("slug", "succeeded", "code")) {
        if ($null -eq $tenant.PSObject.Properties[$propertyName]) {
            throw "Resultado tenant da migracao esta incompleto."
        }
    }
    if ([string]$tenant.slug -cne $ExpectedTenant -or
        $tenant.succeeded -ne $true -or
        [string]$tenant.code -notin @("migrated", "already_current")) {
        throw "Resultado tenant da migracao nao comprova sucesso."
    }
}

New-Item -ItemType Directory -Path $EvidenceDirectory -Force | Out-Null
$releaseToken = [System.IO.Path]::GetFileName($AppRoot.TrimEnd('\'))
$releaseToken = ($releaseToken -replace "[^A-Za-z0-9_.-]", "-")
if ($releaseToken.Length -gt 48) {
    $releaseToken = $releaseToken.Substring(0, 48)
}
$operationId = [guid]::NewGuid().ToString("N").Substring(0, 12)
$taskName = "SmartCRM-Migrate-$releaseToken-$TenantSlug-$operationId"
$operationDirectory = Join-Path `
    $EvidenceDirectory `
    "$releaseToken-$TenantSlug-$operationId"
New-Item -ItemType Directory -Path $operationDirectory -ErrorAction Stop | Out-Null
& icacls `
    $operationDirectory `
    /inheritance:r `
    /grant:r `
    '*S-1-5-18:(OI)(CI)F' `
    '*S-1-5-32-544:(OI)(CI)F' `
    "${serviceUser}:(OI)(CI)M" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Nao foi possivel preparar a pasta de evidencia para a conta de servico."
}
$evidencePath = Join-Path `
    $operationDirectory `
    "fleet-result.json"

$arguments = @(
    '-NoProfile',
    '-ExecutionPolicy Bypass',
    ('-File "{0}"' -f $runner),
    ('-AppRoot "{0}"' -f $AppRoot),
    ('-EnvFile "{0}"' -f $EnvFile),
    ('-TenantSlug "{0}"' -f $TenantSlug),
    ('-EvidencePath "{0}"' -f $evidencePath),
    '-BackupAcknowledged'
) -join ' '
$action = New-ScheduledTaskAction `
    -Execute "PowerShell.exe" `
    -Argument $arguments `
    -WorkingDirectory $AppRoot
$executionLimit = [TimeSpan]::FromSeconds([Math]::Ceiling($TimeoutSeconds + 60))
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit $executionLimit `
    -MultipleInstances IgnoreNew

$taskRegistered = $false
try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Settings $settings `
        -User $serviceUser `
        -Password $servicePassword `
        -RunLevel Highest `
        -Description "Smart CRM one-shot fleet migration" `
        -Force | Out-Null
    $taskRegistered = $true
    $before = Get-ScheduledTaskInfo -TaskName $taskName
    Start-ScheduledTask -TaskName $taskName

    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $completed = $false
    $taskInfo = $null
    while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        $task = Get-ScheduledTask -TaskName $taskName
        $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName
        if ($task.State -ne "Running" -and
            $taskInfo.LastRunTime -gt $before.LastRunTime) {
            $completed = $true
            break
        }
        Start-Sleep -Milliseconds $PollMilliseconds
    }
    if (-not $completed) {
        throw "A tarefa temporaria de migracao excedeu o limite de tempo."
    }
    if ([int]$taskInfo.LastTaskResult -ne 0) {
        throw "A tarefa temporaria de migracao terminou com falha."
    }
    if (-not (Test-Path -LiteralPath $evidencePath -PathType Leaf)) {
        throw "A tarefa temporaria nao produziu evidencia."
    }
    try {
        $evidence = Get-Content -LiteralPath $evidencePath -Raw | ConvertFrom-Json
    }
    catch {
        throw "A evidencia da tarefa temporaria e invalida."
    }
    Assert-SmartCrmFleetTaskEvidence `
        -Evidence $evidence `
        -ExpectedReleasePath $AppRoot `
        -ExpectedTenant $TenantSlug
}
finally {
    $servicePassword = $null
    if ($taskRegistered) {
        $registeredTask = $null
        try {
            $registeredTask = Get-ScheduledTask -TaskName $taskName
        }
        catch {
            $registeredTask = $null
        }
        if ($null -ne $registeredTask -and $registeredTask.State -eq "Running") {
            Stop-ScheduledTask -TaskName $taskName
        }
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
}

Write-Output "FLEET_TASK=PASS tenant=$TenantSlug evidence=$evidencePath"
