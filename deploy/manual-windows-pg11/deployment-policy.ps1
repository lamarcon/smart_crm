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

function Get-SmartCrmEnvironmentAllowedKeys {
    return @(
        "SMART_CRM_DB_NAME", "SMART_CRM_DB_USER", "SMART_CRM_DB_PASSWORD",
        "SMART_CRM_DB_HOST", "SMART_CRM_DB_PORT", "SMART_CRM_BIND_IP",
        "SMART_CRM_PORT", "SMART_CRM_CONTROL_DATABASE_URL",
        "SMART_CRM_TENANT_SECRET_STORE", "SMART_CRM_EXPECTED_ORIGIN",
        "SMART_CRM_TENANT_MAX_CACHED_ENGINES", "SMART_CRM_TENANT_POOL_SIZE",
        "SMART_CRM_TENANT_MAX_OVERFLOW",
        "SMART_CRM_TENANT_POOL_TIMEOUT_SECONDS",
        "SMART_CRM_TENANT_CONNECT_TIMEOUT_SECONDS",
        "SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK"
    )
}

function Read-SmartCrmEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [string[]]$AllowedKeys = @()
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Arquivo de ambiente nao encontrado."
    }

    $allowed = @{}
    foreach ($allowedKey in $AllowedKeys) {
        $allowed[$allowedKey] = $true
    }

    $settings = @{}
    $lineNumber = 0
    foreach ($rawLine in [System.IO.File]::ReadAllLines($Path)) {
        $lineNumber += 1
        $trimmed = $rawLine.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }

        $separator = $rawLine.IndexOf("=")
        if ($separator -lt 1) {
            throw "Linha de ambiente invalida na linha $lineNumber."
        }
        $key = $rawLine.Substring(0, $separator).Trim()
        if ($key -notmatch "^[A-Z][A-Z0-9_]*$") {
            throw "Chave de ambiente invalida na linha $lineNumber."
        }
        if ($allowed.Count -gt 0 -and -not $allowed.ContainsKey($key)) {
            throw "Chave de ambiente nao permitida: $key."
        }
        if ($settings.ContainsKey($key)) {
            throw "Chave de ambiente duplicada: $key."
        }

        # Split only at the first equals sign and keep the value byte-for-byte.
        $settings[$key] = $rawLine.Substring($separator + 1)
    }
    return $settings
}

function Get-SmartCrmControlAlembicUpgradeArguments {
    return @("-m", "alembic", "-c", "alembic-control.ini", "upgrade", "d5f0a8c3e7b2")
}

function Get-SmartCrmControlAlembicCurrentArguments {
    return @("-m", "alembic", "-c", "alembic-control.ini", "current")
}

function Get-SmartCrmTenantAlembicUpgradeArguments {
    return @("-m", "alembic", "-c", "alembic.ini", "upgrade", "f6b1d3a8c2e4")
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

function ConvertTo-SmartCrmNativeArgument {
    param([AllowEmptyString()][string]$Value)
    if ($null -eq $Value) {
        $Value = ""
    }
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }

    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq [char]92) {
            $backslashes += 1
            continue
        }
        if ($character -eq [char]34) {
            [void]$builder.Append(('\' * (($backslashes * 2) + 1)))
            [void]$builder.Append('"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append(('\' * $backslashes))
            $backslashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append(('\' * ($backslashes * 2)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-SmartCrmNativeProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory
    )
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = (@($ArgumentList | ForEach-Object {
        ConvertTo-SmartCrmNativeArgument -Value $_
    }) -join " ")
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    if ($WorkingDirectory) {
        $startInfo.WorkingDirectory = $WorkingDirectory
    }

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "Nao foi possivel iniciar o processo nativo."
        }
        $standardOutput = $process.StandardOutput.ReadToEndAsync()
        $standardError = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = $standardOutput.Result
        $stderr = $standardError.Result
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            StdOut = $stdout
            StdErr = $stderr
        }
    }
    finally {
        $process.Dispose()
    }
}

function Wait-SmartCrmPortReleased {
    param(
        [int]$Port = 8080,
        [double]$TimeoutSeconds = 30,
        [int]$PollMilliseconds = 250,
        [scriptblock]$Probe
    )
    if ($TimeoutSeconds -lt 0 -or $PollMilliseconds -lt 1) {
        throw "Parametros de espera da porta sao invalidos."
    }
    if ($null -eq $Probe) {
        $Probe = {
            param($CandidatePort)
            return @(
                Get-NetTCPConnection -LocalPort $CandidatePort -State Listen `
                    -ErrorAction SilentlyContinue
            ).Count -gt 0
        }
    }

    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        if (-not [bool](& $Probe $Port)) {
            return
        }
        if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
            throw "A porta $Port nao foi liberada dentro do limite."
        }
        Start-Sleep -Milliseconds $PollMilliseconds
    }
}

function Assert-SmartCrmScheduledTaskTarget {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Task,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedUser,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedAppRoot
    )
    if ($Task.Principal.UserId -ine $ExpectedUser) {
        throw "A tarefa SmartCRM nao usa a conta de servico esperada."
    }
    $actions = @($Task.Actions)
    if ($actions.Count -ne 1) {
        throw "A tarefa SmartCRM deve possuir exatamente uma acao."
    }

    $action = $actions[0]
    if ([System.IO.Path]::GetFileName($action.Execute) -ine "PowerShell.exe") {
        throw "A tarefa SmartCRM nao usa o executavel esperado."
    }
    $root = $ExpectedAppRoot.TrimEnd('\')
    $startScript = Join-Path $root "deploy\manual-windows-pg11\start-smart-crm.ps1"
    $filePattern = '(?i)(?:^|\s)-File\s+"?' + [regex]::Escape($startScript) + '"?(?:\s|$)'
    $rootPattern = '(?i)(?:^|\s)-AppRoot\s+"?' + [regex]::Escape($root) + '"?(?:\s|$)'
    if ($action.Arguments -notmatch $filePattern -or $action.Arguments -notmatch $rootPattern) {
        throw "A tarefa SmartCRM nao referencia a release imutavel esperada."
    }
    if ($action.WorkingDirectory -and $action.WorkingDirectory.TrimEnd('\') -ine $root) {
        throw "O diretorio de trabalho da tarefa SmartCRM diverge da release esperada."
    }
}

function Invoke-SmartCrmLoggedProcess {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$LogPath
    )
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 converts native stderr into ErrorRecord objects.
        # Uvicorn writes normal lifecycle messages to stderr, so Stop would
        # terminate an otherwise healthy scheduled task on its first log line.
        $ErrorActionPreference = "Continue"
        & $FilePath @ArgumentList *>> $LogPath
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return $exitCode
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
    if ($null -eq $Health) {
        return $false
    }
    $status = $Health.PSObject.Properties["status"]
    return $null -ne $status -and $status.Value -eq "ok"
}

function Assert-SmartCrmReleaseReadiness {
    param(
        [object]$Health,
        [object]$Version,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedVersion
    )
    if (-not (Test-SmartCrmHealth -Health $Health)) {
        throw "O health check da nova release nao retornou status ok."
    }
    if ($null -eq $Version) {
        throw "A nova release nao informou a versao ativa."
    }
    $versionProperty = $Version.PSObject.Properties["version"]
    if ($null -eq $versionProperty -or $versionProperty.Value -cne $ExpectedVersion) {
        throw "A versao ativa diverge da release esperada."
    }
}

function Wait-SmartCrmReleaseReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExpectedVersion,
        [double]$TimeoutSeconds = 30,
        [int]$PollMilliseconds = 500,
        [scriptblock]$Request
    )
    if ($TimeoutSeconds -le 0 -or $PollMilliseconds -lt 1) {
        throw "Parametros de espera da release sao invalidos."
    }
    if ($null -eq $Request) {
        $Request = {
            param($Uri)
            Invoke-RestMethod -Uri $Uri -TimeoutSec 3
        }
    }

    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        try {
            $health = & $Request "http://127.0.0.1:8080/health"
            $version = & $Request "http://127.0.0.1:8080/api/version"
            Assert-SmartCrmReleaseReadiness `
                -Health $health `
                -Version $version `
                -ExpectedVersion $ExpectedVersion
            return [pscustomobject]@{
                Health = $health
                Version = $version
            }
        }
        catch {
            if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
                break
            }
            Start-Sleep -Milliseconds $PollMilliseconds
        }
    }
    throw "A release esperada $ExpectedVersion nao ficou pronta dentro do limite."
}
