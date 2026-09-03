[CmdletBinding()]
param(
    [string]$AppRoot = "C:\brbots\apps\smart-crm",
    [string]$TaskName = "SmartCRM"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal -ArgumentList $identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Execute este script em PowerShell como Administrador."
}

$startScript = Join-Path $AppRoot "deploy\manual-windows-pg11\start-smart-crm.ps1"
foreach ($requiredFile in @($startScript, (Join-Path $AppRoot ".venv\Scripts\python.exe"), "C:\ProgramData\SmartCRM\server.env")) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) { throw "Arquivo obrigatorio ausente: $requiredFile" }
}

$arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -AppRoot "{1}"' -f $startScript, $AppRoot
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument $arguments -WorkingDirectory $AppRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$taskPrincipal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $taskPrincipal -Settings $taskSettings -Description "Smart CRM Uvicorn loopback runtime" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output "scheduled task registered: $TaskName"
