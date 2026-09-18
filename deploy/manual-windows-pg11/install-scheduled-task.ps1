[CmdletBinding()]
param(
    [string]$AppRoot = "C:\brbots\apps\smart-crm",
    [string]$TaskName = "SmartCRM",
    [Parameter(Mandatory = $true)]
    [PSCredential]$ServiceCredential
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$requiredServiceAccount = "SmartCRMService"
$serviceUser = $ServiceCredential.UserName.Trim()
$accountParts = @($serviceUser -split "\\")
if ($accountParts.Count -ne 2 -or $accountParts[-1] -ne $requiredServiceAccount) {
    throw "Informe a conta dedicada SmartCRMService com nome qualificado."
}
$servicePassword = $ServiceCredential.GetNetworkCredential().Password
if (-not $servicePassword) {
    throw "A credencial da conta dedicada nao pode ter senha vazia."
}

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
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $taskSettings -User $serviceUser -Password $servicePassword -RunLevel Highest -Description "Smart CRM Uvicorn loopback runtime" -Force | Out-Null
}
finally {
    $servicePassword = $null
}
Start-ScheduledTask -TaskName $TaskName
Write-Output "scheduled task registered: $TaskName"
