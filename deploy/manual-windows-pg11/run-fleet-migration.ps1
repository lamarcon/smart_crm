[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AppRoot,
    [Parameter(Mandatory = $true)]
    [string]$EnvFile,
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[a-z0-9][a-z0-9-]{0,62}$")]
    [string]$TenantSlug,
    [Parameter(Mandatory = $true)]
    [string]$EvidencePath,
    [switch]$BackupAcknowledged,
    [scriptblock]$NativeProcessInvoker
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "deployment-policy.ps1")

if (-not $BackupAcknowledged) {
    throw "A confirmacao de backup verificado e obrigatoria."
}
if (-not (Test-Path -LiteralPath $AppRoot -PathType Container)) {
    throw "A release alvo nao foi encontrada."
}
$python = Join-Path $AppRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "O Python da release alvo nao foi encontrado."
}
if ($null -eq $NativeProcessInvoker) {
    $NativeProcessInvoker = {
        param($FilePath, $ArgumentList, $WorkingDirectory)
        Invoke-SmartCrmNativeProcess `
            -FilePath $FilePath `
            -ArgumentList $ArgumentList `
            -WorkingDirectory $WorkingDirectory
    }
}

$runtimeKeys = @(
    "SMART_CRM_CONTROL_DATABASE_URL",
    "SMART_CRM_TENANT_SECRET_STORE",
    "SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK"
)
$allowedKeys = @(Get-SmartCrmEnvironmentAllowedKeys)
$settings = Read-SmartCrmEnvironment -Path $EnvFile -AllowedKeys $allowedKeys
foreach ($requiredKey in $runtimeKeys) {
    if (-not $settings.ContainsKey($requiredKey) -or
        [string]::IsNullOrWhiteSpace($settings[$requiredKey])) {
        throw "Variavel obrigatoria ausente: $requiredKey."
    }
}

$originalEnvironment = @{}
$targetRevision = $null
$tenantCode = "runner_failed"
$exitCode = 22
try {
    foreach ($key in $runtimeKeys) {
        $originalEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, $settings[$key], "Process")
    }

    $headArguments = @("-m", "alembic", "-c", "alembic.ini", "heads")
    $headResult = & $NativeProcessInvoker $python $headArguments $AppRoot
    if ($headResult.ExitCode -ne 0) {
        $tenantCode = "packaged_head_failed"
        $exitCode = [int]$headResult.ExitCode
        if ($exitCode -eq 0) { $exitCode = 20 }
    }
    else {
        $headMatch = [regex]::Match(
            [string]$headResult.StdOut,
            "(?m)^\s*([a-z0-9]{12,64})\s+\(head\)\s*$"
        )
        if (-not $headMatch.Success) {
            $tenantCode = "packaged_head_invalid"
            $exitCode = 20
        }
        else {
            $targetRevision = $headMatch.Groups[1].Value
            $migrationArguments = @(
                "-m", "app.fleet_cli", "migrate",
                "--tenant", $TenantSlug,
                "--backup-acknowledged", "--confirmed"
            )
            $migrationResult = & $NativeProcessInvoker $python $migrationArguments $AppRoot
            $exitCode = [int]$migrationResult.ExitCode
            $resultLines = @(
                ([string]$migrationResult.StdOut -split "`r?`n") |
                    Where-Object { $_ -match "^[a-z0-9][a-z0-9-]{0,62} code=[a-z0-9_]+$" }
            )
            $expectedPrefix = "$TenantSlug code="
            $selectedResults = @($resultLines | Where-Object { $_.StartsWith($expectedPrefix) })
            if ($selectedResults.Count -ne 1) {
                $tenantCode = "fleet_result_invalid"
                if ($exitCode -eq 0) { $exitCode = 21 }
            }
            else {
                $tenantCode = $selectedResults[0].Substring($expectedPrefix.Length)
                if ($exitCode -eq 0 -and
                    $tenantCode -notin @("migrated", "already_current")) {
                    $exitCode = 21
                }
            }
        }
    }
}
catch {
    $tenantCode = "runner_failed"
    $exitCode = 22
}
finally {
    foreach ($key in $runtimeKeys) {
        if ($originalEnvironment.ContainsKey($key)) {
            [Environment]::SetEnvironmentVariable(
                $key,
                $originalEnvironment[$key],
                "Process"
            )
        }
        else {
            [Environment]::SetEnvironmentVariable($key, $null, "Process")
        }
    }
}

$succeeded = $exitCode -eq 0 -and $tenantCode -in @("migrated", "already_current")
$evidence = [ordered]@{
    schemaVersion = 1
    releasePath = $AppRoot
    targetRevision = $targetRevision
    tenants = @(
        [ordered]@{
            slug = $TenantSlug
            succeeded = $succeeded
            code = $tenantCode
        }
    )
    exitCode = $exitCode
}

$evidenceDirectory = Split-Path -Parent $EvidencePath
if (-not $evidenceDirectory) {
    throw "O caminho da evidencia deve possuir um diretorio."
}
New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null
$temporaryEvidence = "$EvidencePath.$PID.$([guid]::NewGuid().ToString('N')).tmp"
try {
    $json = $evidence | ConvertTo-Json -Depth 4
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($temporaryEvidence, $json, $utf8NoBom)
    Move-Item -LiteralPath $temporaryEvidence -Destination $EvidencePath -Force
}
finally {
    if (Test-Path -LiteralPath $temporaryEvidence) {
        Remove-Item -LiteralPath $temporaryEvidence -Force -ErrorAction SilentlyContinue
    }
}

if (-not $succeeded) {
    [Console]::Error.WriteLine(
        "Migracao da frota falhou para $TenantSlug (codigo $tenantCode)."
    )
    exit $exitCode
}
Write-Output "FLEET_MIGRATION=PASS tenant=$TenantSlug code=$tenantCode"
