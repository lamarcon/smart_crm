[CmdletBinding()]
param(
    [string]$AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-SmartCrmFileSha256 {
    param([string]$Path)

    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

$manifestPath = Join-Path $AppRoot "MANIFEST.sha256"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Manifesto ausente: $manifestPath"
}

$expected = @{}
foreach ($line in Get-Content -LiteralPath $manifestPath) {
    if ($line -notmatch "^(?<Hash>[0-9a-f]{64})  (?<Path>.+)$") {
        throw "Linha invalida no manifesto."
    }
    $relativePath = $Matches.Path.Replace("/", "\")
    if ($expected.ContainsKey($relativePath)) {
        throw "Arquivo duplicado no manifesto: $relativePath"
    }
    $expected[$relativePath] = $Matches.Hash
}

$actualPaths = @(
    Get-ChildItem -LiteralPath $AppRoot -Recurse -File |
        ForEach-Object {
            $_.FullName.Substring($AppRoot.TrimEnd("\").Length + 1)
        } |
        Where-Object {
            $_ -ne "MANIFEST.sha256" -and
            $_ -notlike ".venv\*" -and
            $_ -notmatch "(^|\\)__pycache__\\" -and
            $_ -notlike "*.pyc"
        } |
        Sort-Object
)

if ($actualPaths.Count -ne $expected.Count) {
    throw "Quantidade de arquivos diferente do manifesto."
}

foreach ($relativePath in $actualPaths) {
    if (-not $expected.ContainsKey($relativePath)) {
        throw "Arquivo nao previsto no manifesto: $relativePath"
    }
    $fullPath = Join-Path $AppRoot $relativePath
    $actualHash = Get-SmartCrmFileSha256 -Path $fullPath
    if ($actualHash -ne $expected[$relativePath]) {
        throw "Hash invalido: $relativePath"
    }
}

Write-Output "package integrity: PASS"
