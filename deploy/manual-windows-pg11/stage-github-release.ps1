[CmdletBinding()]
param(
    [string]$Tag,
    [string]$AppsRoot = "C:\brbots\apps",
    [string]$DownloadRoot = "C:\ProgramData\SmartCRM\downloads"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:SmartCrmRepository = "lamarcon/smart_crm"

function Assert-SmartCrmReleaseTag {
    param([string]$Value)

    if ($Value -notmatch '^v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$') {
        throw "A tag deve usar o formato vX.Y.Z sem zeros iniciais."
    }
    return $Value
}

function Get-SmartCrmReleaseAssetNames {
    param([string]$ReleaseTag)

    $safeTag = Assert-SmartCrmReleaseTag -Value $ReleaseTag
    $zipName = "smart-crm-manual-pg11-$safeTag.zip"
    return [PSCustomObject]@{
        Zip = $zipName
        Digest = "$zipName.sha256"
    }
}

function Assert-SmartCrmReleaseMetadata {
    param(
        [object]$Metadata,
        [string]$ExpectedTag
    )

    $safeTag = Assert-SmartCrmReleaseTag -Value $ExpectedTag
    if ($null -eq $Metadata -or $Metadata.draft -or $Metadata.prerelease) {
        throw "A release deve estar publicada e nao pode ser preliminar."
    }
    if ([string]$Metadata.tag_name -cne $safeTag) {
        throw "A tag retornada pelo GitHub diverge da tag solicitada."
    }

    $names = Get-SmartCrmReleaseAssetNames -ReleaseTag $safeTag
    $assets = @($Metadata.assets)
    $zipAssets = @($assets | Where-Object { $_.name -ceq $names.Zip })
    $digestAssets = @($assets | Where-Object { $_.name -ceq $names.Digest })
    if ($assets.Count -ne 2 -or $zipAssets.Count -ne 1 -or $digestAssets.Count -ne 1) {
        throw "A release deve conter exatamente o ZIP e o SHA-256 esperados."
    }

    foreach ($asset in @($zipAssets[0], $digestAssets[0])) {
        $downloadUri = [Uri]$asset.browser_download_url
        if ($downloadUri.Scheme -ne "https" -or $downloadUri.Host -ne "github.com") {
            throw "Asset com URL de download invalida."
        }
    }

    return [PSCustomObject]@{
        Tag = $safeTag
        ZipAsset = $zipAssets[0]
        DigestAsset = $digestAssets[0]
    }
}

function Get-SmartCrmPublicRelease {
    param([string]$ReleaseTag)

    $safeTag = Assert-SmartCrmReleaseTag -Value $ReleaseTag
    [Net.ServicePointManager]::SecurityProtocol = (
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    )
    $encodedTag = [Uri]::EscapeDataString($safeTag)
    $uri = "https://api.github.com/repos/$script:SmartCrmRepository/releases/tags/$encodedTag"
    return Invoke-RestMethod -Uri $uri -UseBasicParsing -Headers @{
        Accept = "application/vnd.github+json"
        "User-Agent" = "SmartCRM-Windows-Release-Stager"
    }
}

function Read-SmartCrmReleaseDigest {
    param(
        [string]$DigestPath,
        [string]$ExpectedFileName
    )

    $content = [IO.File]::ReadAllText($DigestPath)
    $match = [regex]::Match($content, '\A([0-9a-fA-F]{64})  ([^\r\n]+)\r?\n?\z')
    if (-not $match.Success -or $match.Groups[2].Value -cne $ExpectedFileName) {
        throw "Arquivo SHA-256 invalido ou referente a outro ZIP."
    }
    return $match.Groups[1].Value.ToLowerInvariant()
}

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

function Assert-SmartCrmArchiveDigest {
    param(
        [string]$ArchivePath,
        [string]$DigestPath
    )

    $archiveName = [IO.Path]::GetFileName($ArchivePath)
    $expected = Read-SmartCrmReleaseDigest -DigestPath $DigestPath -ExpectedFileName $archiveName
    $actual = Get-SmartCrmFileSha256 -Path $ArchivePath
    if ($actual -cne $expected) {
        throw "O SHA-256 do ZIP baixado nao corresponde ao publicado."
    }
    return $actual
}

function Get-SmartCrmValidatedChildPath {
    param(
        [string]$Parent,
        [string]$ChildName
    )

    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    $childFull = [IO.Path]::GetFullPath((Join-Path $parentFull $ChildName))
    if (-not $childFull.StartsWith("$parentFull\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Caminho temporario fora da raiz permitida."
    }
    return $childFull
}

function Remove-SmartCrmTemporaryDirectory {
    param(
        [string]$Parent,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    $pathFull = [IO.Path]::GetFullPath($Path)
    if (-not $pathFull.StartsWith("$parentFull\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Recusa ao remover caminho temporario fora da raiz permitida."
    }
    if (Test-Path -LiteralPath $pathFull) {
        Remove-Item -LiteralPath $pathFull -Recurse -Force
    }
}

function Install-SmartCrmReleaseArchive {
    param(
        [string]$ArchivePath,
        [string]$ReleaseTag,
        [string]$DestinationRoot
    )

    $safeTag = Assert-SmartCrmReleaseTag -Value $ReleaseTag
    New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null
    $finalRoot = Get-SmartCrmValidatedChildPath -Parent $DestinationRoot -ChildName "smart-crm-$safeTag"
    if (Test-Path -LiteralPath $finalRoot) {
        throw "A pasta da release ja existe e nao sera sobrescrita: $finalRoot"
    }

    $stagingName = "smart-crm-$safeTag.staging-$([Guid]::NewGuid().ToString('N'))"
    $stagingRoot = Get-SmartCrmValidatedChildPath -Parent $DestinationRoot -ChildName $stagingName
    try {
        Expand-Archive -LiteralPath $ArchivePath -DestinationPath $stagingRoot
        $integrityScript = Join-Path $stagingRoot "deploy\manual-windows-pg11\test-package-integrity.ps1"
        if (-not (Test-Path -LiteralPath $integrityScript -PathType Leaf)) {
            throw "O ZIP nao contem o verificador de integridade obrigatorio."
        }
        & $integrityScript -AppRoot $stagingRoot | Out-Null
        [IO.Directory]::Move($stagingRoot, $finalRoot)
        $stagingRoot = $null
        return Get-Item -LiteralPath $finalRoot
    }
    finally {
        Remove-SmartCrmTemporaryDirectory -Parent $DestinationRoot -Path $stagingRoot
    }
}

function Invoke-SmartCrmReleaseStaging {
    param(
        [string]$ReleaseTag,
        [string]$DestinationRoot,
        [string]$TemporaryRoot
    )

    $safeTag = Assert-SmartCrmReleaseTag -Value $ReleaseTag
    $metadata = Get-SmartCrmPublicRelease -ReleaseTag $safeTag
    $release = Assert-SmartCrmReleaseMetadata -Metadata $metadata -ExpectedTag $safeTag
    New-Item -ItemType Directory -Path $TemporaryRoot -Force | Out-Null
    $downloadDirectory = Get-SmartCrmValidatedChildPath `
        -Parent $TemporaryRoot `
        -ChildName "release-$safeTag-$([Guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $downloadDirectory | Out-Null

    try {
        $zipPath = Join-Path $downloadDirectory $release.ZipAsset.name
        $digestPath = Join-Path $downloadDirectory $release.DigestAsset.name
        Invoke-WebRequest -Uri $release.ZipAsset.browser_download_url -OutFile $zipPath -UseBasicParsing
        Invoke-WebRequest -Uri $release.DigestAsset.browser_download_url -OutFile $digestPath -UseBasicParsing
        $digest = Assert-SmartCrmArchiveDigest -ArchivePath $zipPath -DigestPath $digestPath
        $releaseRoot = Install-SmartCrmReleaseArchive `
            -ArchivePath $zipPath `
            -ReleaseTag $safeTag `
            -DestinationRoot $DestinationRoot
        return [PSCustomObject]@{
            Tag = $safeTag
            Sha256 = $digest
            ReleaseRoot = $releaseRoot.FullName
        }
    }
    finally {
        Remove-SmartCrmTemporaryDirectory -Parent $TemporaryRoot -Path $downloadDirectory
    }
}

function Assert-SmartCrmAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal -ArgumentList $identity
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Execute este script em PowerShell como Administrador."
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    Assert-SmartCrmAdministrator
    $result = Invoke-SmartCrmReleaseStaging `
        -ReleaseTag $Tag `
        -DestinationRoot $AppsRoot `
        -TemporaryRoot $DownloadRoot
    $result | Format-List Tag, Sha256, ReleaseRoot
    Write-Output "RELEASE_STAGED=PASS"
    Write-Output "Nenhum banco, tarefa agendada ou arquivo server.env foi alterado."
}
