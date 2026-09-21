# Cutover multiempresa manual - BRBots

Este pacote prepara o Smart CRM no Windows Server 2016 com Python 3.11 x64, PostgreSQL 11 compartilhado na porta `5432`, conexoes do Smart CRM em `127.0.0.1`, Apache como proxy reverso e aplicacao interna em `127.0.0.1:8080`.

Este documento nao autoriza uma mudanca no servidor. A execucao exige autorizacao de producao separada, janela de manutencao, backup verificado e responsavel pelo rollback. Nao faca deploy, migracao, parada de tarefa ou alteracao do Apache apenas porque o pacote foi gerado.

## Decisoes fixas deste primeiro tenant

- URL publica: `https://sc2030.brbots.com/brbots`.
- Identificador e nome da empresa: `brbots`.
- Primeiro administrador: `Luiz Felipe`, e-mail `lfmarcon@brbots.com`.
- Conta Windows dedicada: `NOME-DO-SERVIDOR\SmartCRMService`.
- O database `smartcrm` permanece no lugar e passa a ser o tenant da BRBots. Ele nao e recriado, movido ou clonado.
- O novo database `smartcrm_control` contem somente diretorio de tenants, sessoes, bloqueios de login e auditoria; nao copie dados comerciais para ele.
- Os databases preexistentes `DW_CMS` e `DW_PRODUTOS` continuam atendendo seus clientes remotos, nao recebem migracao do Smart CRM e nao podem ter listener, role, schema, regra HBA ou dado alterado por este corte.
- Nao existe cadastro publico de empresa ou primeiro administrador.

## 1. Autorizar e registrar a mudanca

Antes de qualquer comando em producao, registre:

- autorizacao nominal, ticket e janela de manutencao;
- SHA da release e hash SHA-256 do ZIP;
- release ativa atual e caminho para rollback;
- backup consistente do `smartcrm`, hash e ensaio de restauracao;
- backup do `smartcrm_control`, se ja existir;
- exportacao da tarefa `SmartCRM`, `server.env` e configuracao Apache;
- responsavel por executar e responsavel por validar o UAT.

Sem todos esses itens, pare. A autorizacao local para desenvolver o pacote nao vale como autorizacao de producao.

## 2. Preparar a conta dedicada

Crie a conta local `SmartCRMService` antes da instalacao, sem coloca-la no grupo Administradores. Conceda o direito **Log on as a batch job** pela politica local. Use uma senha forte e guarde-a no cofre operacional; quando ela for rotacionada, registre novamente a tarefa.

O instalador resolve o SID dessa conta, concede leitura do `server.env` e modificacao somente em `logs` e `tenant-secrets`. A aplicacao nao roda como `SYSTEM`. O provisionamento DPAPI e a tarefa usam a mesma identidade `SmartCRMService`.

## 3. Copiar a release lado a lado

Cada pacote deve ser extraido em uma pasta imutavel no formato `C:\brbots\apps\smart-crm-<SHA>`. Exemplo:

```powershell
$releaseSha = "<SHA>"
$releaseRoot = "C:\brbots\apps\smart-crm-$releaseSha"
$serviceAccount = "$env:COMPUTERNAME\SmartCRMService"
```

Confira o ZIP antes de extrair:

```powershell
Get-FileHash .\smart-crm-manual-pg11-$releaseSha.zip -Algorithm SHA256
Get-Content .\smart-crm-manual-pg11-$releaseSha.zip.sha256
```

Os hashes devem ser identicos. Crie uma pasta nova e extraia nela. Nao sobrescreva a release ativa, nao apague a release anterior e nao extraia por cima de `C:\brbots\apps\smart-crm`. `git pull` e proibido nesse servidor para este pacote offline.

A pasta nova deve conter `app`, `migrations`, `migrations_control`, `wheelhouse`, `alembic.ini`, `alembic-control.ini`, `requirements-runtime.txt`, `MANIFEST.sha256` e `deploy`.

## 3.1. Proteger somente os databases do Smart CRM no PostgreSQL compartilhado

O listener global da instancia permanece como esta porque `DW_CMS` e `DW_PRODUTOS` dependem de acesso remoto. Nao altere `listen_addresses`, nao reinicie o servico PostgreSQL e nao mude as regras existentes desses databases.

Descubra o arquivo ativo sem imprimir senha:

```powershell
$settings = Get-Content C:\ProgramData\SmartCRM\server.env |
    Where-Object { $_ -and -not $_.StartsWith('#') } |
    Out-String | ConvertFrom-StringData
$env:PGPASSWORD = $settings.SMART_CRM_DB_PASSWORD
try {
    $pgHbaPath = (& "C:\Program Files\PostgreSQL\11\bin\psql.exe" `
        -h 127.0.0.1 -p 5432 -U smartcrm -d smartcrm -At `
        -c "SHOW hba_file;").Trim()
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    Remove-Variable settings -ErrorAction SilentlyContinue
}
if (-not (Test-Path -LiteralPath $pgHbaPath -PathType Leaf)) {
    throw "pg_hba.conf ativo nao foi localizado."
}
Copy-Item -LiteralPath $pgHbaPath -Destination "$pgHbaPath.pre-smartcrm-multitenant"
```

Crie uma proposta, sem sobrescrever o arquivo ativo:

```powershell
$hbaBlock = @'
# BEGIN SMARTCRM LOCAL ONLY
host smartcrm,smartcrm_control all 127.0.0.1/32 md5
host smartcrm,smartcrm_control all ::1/128 md5
host smartcrm,smartcrm_control all 0.0.0.0/0 reject
host smartcrm,smartcrm_control all ::/0 reject
# END SMARTCRM LOCAL ONLY
'@
$pgHbaNext = "$pgHbaPath.smartcrm.next"
$currentHba = [IO.File]::ReadAllText($pgHbaPath)
if ($currentHba -match "BEGIN SMARTCRM LOCAL ONLY") {
    throw "O bloco Smart CRM ja existe; valide-o em vez de duplicar."
}
[IO.File]::WriteAllText(
    $pgHbaNext,
    $hbaBlock + [Environment]::NewLine + $currentHba,
    (New-Object Text.UTF8Encoding($false))
)
. "$releaseRoot\deploy\manual-windows-pg11\deployment-policy.ps1"
Assert-SmartCrmSharedPostgresHba -PgHbaText ([IO.File]::ReadAllText($pgHbaNext))
```

Revise a proposta e confirme que somente as quatro regras mostradas foram adicionadas antes das regras `host` atuais. Dentro da janela autorizada, substitua o arquivo e recarregue a configuracao sem reiniciar o PostgreSQL:

```powershell
Copy-Item -LiteralPath $pgHbaNext -Destination $pgHbaPath -Force
& "C:\Program Files\PostgreSQL\11\bin\psql.exe" `
    -h 127.0.0.1 -p 5432 -U postgres -d postgres -W `
    -v ON_ERROR_STOP=1 -c "SELECT pg_reload_conf();"
```

`pg_reload_conf()` apenas recarrega a configuracao; ele nao reinicia o PostgreSQL. Se retornar falso ou erro, restaure o backup do HBA e pare. Antes e depois da recarga, valide pelo sistema cliente que `DW_CMS` e `DW_PRODUTOS` continuam acessiveis. De uma maquina remota, tentativas a `smartcrm` e `smartcrm_control` devem ser rejeitadas.

## 4. Instalar a release sem publica-la

Abra PowerShell como Administrador:

```powershell
Set-Location $releaseRoot
Set-ExecutionPolicy -Scope Process Bypass
& .\deploy\manual-windows-pg11\test-package-integrity.ps1 -AppRoot $releaseRoot
& .\deploy\manual-windows-pg11\install-offline.ps1 `
    -AppRoot $releaseRoot `
    -ServiceAccount $serviceAccount `
    -SharedPostgres `
    -PgHbaPath $pgHbaPath
icacls $releaseRoot /grant:r "$($serviceAccount):(OI)(CI)RX"
```

O instalador valida CPython 3.11 x64, o listener compartilhado, as quatro primeiras regras `host` do HBA, wheelhouse e dependencias fixadas. Ele nao para nem reconfigura o PostgreSQL e nao altera o Apache.

Em instalacao nova, ele cria `C:\ProgramData\SmartCRM\server.env` com duas senhas aleatorias diferentes: uma para `smartcrm` e outra para `smartcrm_control`. Nunca copie esse arquivo para a pasta da aplicacao.

### Atualizar um `server.env` legado

Se o arquivo existente ainda nao tiver `SMART_CRM_CONTROL_DATABASE_URL`, preserve os valores atuais e gere um sucessor validavel:

```powershell
$envPath = "C:\ProgramData\SmartCRM\server.env"
$nextEnv = "C:\ProgramData\SmartCRM\server.env.next"
$backupEnv = "C:\ProgramData\SmartCRM\server.env.pre-multitenant"
$legacy = Get-Content -LiteralPath $envPath |
    Where-Object { $_ -and -not $_.StartsWith('#') } |
    Out-String | ConvertFrom-StringData
. "$releaseRoot\deploy\manual-windows-pg11\deployment-policy.ps1"

$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
$controlPassword = -join ($bytes | ForEach-Object { $_.ToString("x2") })
$lines = New-SmartCrmEnvironmentLines `
    -Password $legacy.SMART_CRM_DB_PASSWORD `
    -ControlPassword $controlPassword
[IO.File]::WriteAllLines($nextEnv, $lines, (New-Object Text.UTF8Encoding($false)))

& "$releaseRoot\deploy\manual-windows-pg11\start-smart-crm.ps1" `
    -AppRoot $releaseRoot -EnvFile $nextEnv -ValidateOnly
Copy-Item -LiteralPath $envPath -Destination $backupEnv
Move-Item -LiteralPath $nextEnv -Destination $envPath -Force
Remove-Variable legacy,lines,controlPassword -ErrorAction SilentlyContinue
& "$releaseRoot\deploy\manual-windows-pg11\install-offline.ps1" `
    -AppRoot $releaseRoot -ServiceAccount $serviceAccount
```

O literal `SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK=1` autoriza somente o PostgreSQL local da BRBots em loopback. Ele nao libera bancos remotos: futuros servidores PostgreSQL continuam obrigados a usar `sslmode=verify-full` e CA confiavel.

## 5. Criar somente o plano de controle

Carregue a configuracao sem exibir valores e copie temporariamente a senha de controle:

```powershell
$settings = Get-Content C:\ProgramData\SmartCRM\server.env |
    Where-Object { $_ -and -not $_.StartsWith('#') } |
    Out-String | ConvertFrom-StringData
$controlUri = [Uri]($settings.SMART_CRM_CONTROL_DATABASE_URL -replace '^postgresql\+psycopg', 'postgresql')
$controlUserInfo = $controlUri.UserInfo -split ':', 2
$controlPassword = [Uri]::UnescapeDataString($controlUserInfo[1])
Set-Clipboard -Value $controlPassword
& "C:\Program Files\PostgreSQL\11\bin\psql.exe" -h 127.0.0.1 -p 5432 -U postgres -d postgres
```

No `psql`, verifique antes de criar:

```sql
\du smartcrm_control
\l smartcrm_control
```

Se a role nao existir:

```sql
CREATE ROLE smartcrm_control LOGIN;
\password smartcrm_control
```

Cole a senha do clipboard quando solicitado. Se a role ja existir, nao a recrie nem apague; alinhe a senha de forma controlada.

Se o database nao existir:

```sql
CREATE DATABASE smartcrm_control OWNER smartcrm_control ENCODING 'UTF8';
REVOKE CONNECT ON DATABASE smartcrm_control FROM PUBLIC;
GRANT CONNECT ON DATABASE smartcrm_control TO smartcrm_control;
```

Se ja existir, confirme o proprietario e pare em caso de divergencia. Nao use `DROP DATABASE`, `DROP ROLE` ou `CREATE TABLE` manual.

Confirme tambem o banco comercial existente, sem recria-lo:

```sql
\du smartcrm
\l smartcrm
```

O `smartcrm` deve continuar pertencendo a role operacional aprovada. Nao mova, exporte, restaure ou copie registros comerciais para `smartcrm_control`.

Ao sair do `psql`:

```powershell
Set-Clipboard -Value ""
Remove-Variable controlPassword,controlUserInfo,controlUri -ErrorAction SilentlyContinue
```

## 6. Migrar e trocar a tarefa na janela autorizada

Este passo altera os dois schemas e troca a tarefa que atende a porta 8080. Execute somente dentro da janela aprovada.

```powershell
$serviceCredential = Get-Credential `
    -UserName $serviceAccount `
    -Message "Credencial da conta dedicada do Smart CRM"
Export-ScheduledTask -TaskName SmartCRM |
    Set-Content C:\ProgramData\SmartCRM\SmartCRM-task.pre-multitenant.xml
Stop-ScheduledTask -TaskName SmartCRM -ErrorAction SilentlyContinue

& "$releaseRoot\deploy\manual-windows-pg11\initialize-and-test.ps1" `
    -AppRoot $releaseRoot `
    -EnvFile C:\ProgramData\SmartCRM\server.env `
    -SharedPostgres `
    -PgHbaPath $pgHbaPath `
    -ServiceCredential $serviceCredential
```

O inicializador executa, nesta ordem:

1. `alembic-control.ini` ate `c01a5d8e4f20` e confirma exatamente esse head;
2. `alembic.ini` no database existente `smartcrm` ate `a4c9d2e7f1b6` e confirma exatamente esse head;
3. registra a tarefa `SmartCRM` na nova release usando `SmartCRMService`;
4. valida `http://127.0.0.1:8080/health`.

Qualquer falha para antes da publicacao. O startup web nunca executa Alembic. O Apache permanece inalterado.

O resultado obrigatorio e:

```text
{"status":"ok","database":"ok"}
LOCAL GATE: PASS. O Apache pode ser configurado.
```

## 7. Registrar a BRBots e criar o primeiro administrador

DPAPI e vinculado a conta Windows. Abra PowerShell interativo como `SmartCRMService`, por exemplo com `runas /user:NOME-DO-SERVIDOR\SmartCRMService powershell.exe`, e execute os comandos abaixo nessa janela. Nao cadastre como Administrador ou `SYSTEM`.

```powershell
$releaseRoot = "C:\brbots\apps\smart-crm-<SHA>"
Set-Location $releaseRoot
$settings = Get-Content C:\ProgramData\SmartCRM\server.env |
    Where-Object { $_ -and -not $_.StartsWith('#') } |
    Out-String | ConvertFrom-StringData
$env:SMART_CRM_CONTROL_DATABASE_URL = $settings.SMART_CRM_CONTROL_DATABASE_URL
$env:SMART_CRM_SECRET_STORE = $settings.SMART_CRM_TENANT_SECRET_STORE
$env:SMART_CRM_TENANT_SECRET_STORE = $settings.SMART_CRM_TENANT_SECRET_STORE
$env:SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK = "1"

$tenantDsn = "postgresql+psycopg://smartcrm:$($settings.SMART_CRM_DB_PASSWORD)@127.0.0.1:5432/smartcrm?connect_timeout=5"
Set-Clipboard -Value $tenantDsn
& .\.venv\Scripts\python.exe -m app.admin_cli `
    register-tenant brbots --display-name "brbots" `
    --secret-ref brbots-db --expected-revision a4c9d2e7f1b6
Set-Clipboard -Value ""
Remove-Variable tenantDsn -ErrorAction SilentlyContinue

& .\.venv\Scripts\python.exe -m app.admin_cli `
    activate-default brbots --admin-email lfmarcon@brbots.com `
    --admin-name "Luiz Felipe"
```

No primeiro comando, cole o DSN somente no prompt `Database secret:`. No segundo, escolha a senha inicial forte de Luiz Felipe no prompt `Password:`. Todas as senhas sao solicitadas interativamente ou geradas em memoria; nunca as coloque na linha de comando, Git, ticket ou chat. O sistema persiste a senha do usuario apenas como hash Argon2id.

Ao terminar, limpe as variaveis dessa janela:

```powershell
Set-Clipboard -Value ""
Remove-Item Env:SMART_CRM_CONTROL_DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:SMART_CRM_SECRET_STORE -ErrorAction SilentlyContinue
Remove-Item Env:SMART_CRM_TENANT_SECRET_STORE -ErrorAction SilentlyContinue
Remove-Item Env:SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK -ErrorAction SilentlyContinue
Remove-Variable settings -ErrorAction SilentlyContinue
```

## 8. UAT antes de liberar

Valide primeiro no loopback e depois pelo Apache existente:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
curl.exe -I https://sc2030.brbots.com/
curl.exe --user crm-homologacao https://sc2030.brbots.com/health
```

Sem usar `-k` ou `--insecure`, confirme:

- raiz apresenta o localizador de empresa;
- `brbots` abre `/brbots` e apresenta o login;
- `lfmarcon@brbots.com` autentica com a senha definida no prompt;
- logout revoga a sessao;
- workspace `default` preserva contagens e dados comerciais anteriores;
- leitura, alteracao, exclusao e restauracao ficam limitadas ao tenant BRBots;
- tarefa aponta para `C:\brbots\apps\smart-crm-<SHA>` e roda como `SmartCRMService`.

Somente depois do UAT registre essa release como ativa. Remover Basic Auth ou alterar o Apache e outro corte e exige autorizacao propria.

## 9. Rollback

Se o gate local falhar, mantenha o Apache inalterado e nao publique. Se a troca ja ocorreu:

1. pare a tarefa `SmartCRM`;
2. preserve logs, `server.env`, segredos DPAPI e evidencias;
3. restaure a tarefa anterior ou registre novamente `install-scheduled-task.ps1` com o caminho exato da release anterior e a mesma `SmartCRMService`;
4. se a versao anterior nao for compativel com os schemas migrados, restaure os backups verificados de `smartcrm` e `smartcrm_control` somente com autorizacao explicita de rollback;
5. valide loopback, Apache e contagens antes de reabrir o acesso.

Nao use `git reset --hard`, nao execute downgrade Alembic improvisado e nao apague nenhum database. Rollback de um tenant nunca redireciona para o banco de outro tenant.

## 10. Proximas empresas

Cada nova empresa recebe outro slug e outro PostgreSQL exclusivo. O operador cria database/role no servidor escolhido, migra ate `a4c9d2e7f1b6`, cadastra um `secret_ref` opaco via `register-tenant` e ativa o primeiro administrador via prompt. Bancos remotos usam TLS `verify-full` com CA. Nao existe descoberta automatica de bancos e o navegador nunca escolhe o DSN ou o tenant autenticado.
