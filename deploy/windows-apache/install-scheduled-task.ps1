[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Apps\smart-crm",
    [string]$TaskName = "SmartCRM"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Execute este script em PowerShell como Administrador."
}

$startScript = Join-Path $RepoRoot "deploy\windows-apache\start-smart-crm.ps1"
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$envFile = "C:\ProgramData\SmartCRM\server.env"

foreach ($requiredFile in @($startScript, $python, $envFile)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Arquivo obrigatório não encontrado: $requiredFile"
    }
}

$arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -RepoRoot "{1}"' -f $startScript, $RepoRoot
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument $arguments -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$taskPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 10 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $taskPrincipal `
    -Settings $settings `
    -Description "Smart CRM Uvicorn loopback runtime" `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Output "scheduled task registered: $TaskName"
