[CmdletBinding()]
param(
    [string]$SecretFile = "C:\ProgramData\SmartCRM\service-secrets\smtp-password.bin",
    [string]$ServiceAccount = "$env:COMPUTERNAME\SmartCRMService"
)

# Stores the SMTP password with Windows DPAPI for the account that runs this
# script. Run it in a PowerShell opened as SmartCRMService (for example with
# runas); the password is typed at a hidden prompt and never printed, logged or
# written in plaintext.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "deployment-policy.ps1")

$accountName = ($ServiceAccount -split "\\")[-1]
$currentName = ([Security.Principal.WindowsIdentity]::GetCurrent().Name -split "\\")[-1]
if ($accountName -ine "SmartCRMService" -or $currentName -ine "SmartCRMService") {
    throw "Execute este script em uma sessao do PowerShell aberta como SmartCRMService."
}
$directory = Split-Path -Parent $SecretFile
if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
    throw "Diretorio de segredos de servico ausente. Execute install-offline.ps1 antes."
}

$secure = Read-Host -AsSecureString "Senha SMTP (nao sera exibida)"
$confirmation = Read-Host -AsSecureString "Confirme a senha SMTP"
$plainPointer = [IntPtr]::Zero
$confirmPointer = [IntPtr]::Zero
$plainBytes = $null
$protected = $null
try {
    $plainPointer = [Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($secure)
    $confirmPointer = [Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($confirmation)
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringUni($plainPointer)
    $confirmed = [Runtime.InteropServices.Marshal]::PtrToStringUni($confirmPointer)
    if (-not $plain) { throw "A senha SMTP nao pode ser vazia." }
    if ($plain -cne $confirmed) { throw "As senhas SMTP informadas nao conferem." }
    $plainBytes = [Text.Encoding]::UTF8.GetBytes($plain)
    $protected = Protect-SmartCrmServiceSecret -Plaintext $plainBytes
    $temporary = "$SecretFile.next"
    [IO.File]::WriteAllBytes($temporary, $protected)
    Move-Item -LiteralPath $temporary -Destination $SecretFile -Force
}
finally {
    if ($plainPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($plainPointer) }
    if ($confirmPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($confirmPointer) }
    if ($null -ne $plainBytes) { [Array]::Clear($plainBytes, 0, $plainBytes.Length) }
    Remove-Variable plain, confirmed, secure, confirmation -ErrorAction SilentlyContinue
}

Assert-SmartCrmServiceSecretReadable -Path $SecretFile
Write-Output "smtp password secret: STORED"
