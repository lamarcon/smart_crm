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

## Como executar os blocos

- Use Windows PowerShell 5.1 aberto com "Executar como administrador", salvo onde a secao pede uma janela de `SmartCRMService`.
- Antes de colar, aperte `Esc` e confira que a linha do prompt esta vazia; texto que sobrou na linha se junta ao bloco colado.
- Colado direto no console, cada linha roda mesmo depois de um erro. Para parar no primeiro erro, envolva o bloco em `. {` e `}` com `$ErrorActionPreference = "Stop"` na primeira linha; o ponto mantem as variaveis (`$releaseRoot`, `$serviceAccount`, `$pgHbaPath`) na janela para os passos seguintes.
- O Windows Server 2016 nao usa TLS 1.2 por padrao: antes de acessar o GitHub, execute `[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12` (a secao 3 ja faz isso).
- Ao fechar a janela, recrie as variaveis: `$releaseRoot = "C:\brbots\apps\smart-crm-vX.Y.Z"` e `$serviceAccount = "$env:COMPUTERNAME\SmartCRMService"`.

## Roteiro de atualizacao (servidor ja multiempresa)

Quando a tarefa `SmartCRM` ja roda uma release multiempresa como `SmartCRMService` e o `server.env` ja tem `SMART_CRM_CONTROL_DATABASE_URL`, a atualizacao usa somente:

1. secao 1 (autorizacao e backup);
2. secao 3 (baixar a release lado a lado);
3. secao 3.1 apenas para obter `$pgHbaPath` (as regras ja existem);
4. secao 4 (instalar sem publicar);
5. secao 5.1, se o `server.env` ainda nao tem SMTP;
6. secao 6 (migrar e trocar a tarefa);
7. secao 8 (UAT), incluindo um convite e uma recuperacao de senha de teste.

As secoes 2, 5 e 7 ja foram feitas no primeiro corte e nao se repetem. Para conferir o estado antes de comecar, sem alterar nada:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/version
$t = Get-ScheduledTask -TaskName SmartCRM
"$($t.State) | $($t.Principal.UserId) | $($t.Actions[0].WorkingDirectory)"
Get-Content C:\ProgramData\SmartCRM\server.env | Where-Object { $_ -match '^[A-Z]' } | ForEach-Object { ($_ -split '=', 2)[0] }
```

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

## 2.1. Publicar a release aprovada no GitHub

O GitHub e a fonte de versao e distribuicao do codigo. O servidor continua sendo a fonte exclusiva de configuracao e segredos: `server.env`, credenciais de banco, arquivos DPAPI e backups nunca entram no Git ou na release.

Na estacao de desenvolvimento, depois de aprovar e enviar o commit que sera publicado, confirme que a arvore esta limpa e crie uma tag exatamente igual a `v` seguida de `APP_VERSION`:

```powershell
$appVersion = (& .\.venv\Scripts\python.exe -c "from app.version import APP_VERSION; print(APP_VERSION)").Trim()
$tag = "v$appVersion"
if (git status --porcelain) {
    throw "A arvore de trabalho deve estar limpa antes de criar a tag."
}
git tag --annotate $tag --message "Smart CRM $tag"
git push origin $tag
```

O envio da tag inicia `.github/workflows/release-windows-pg11.yml`. A publicacao so ocorre depois de:

1. validar que a tag coincide com a versao da aplicacao;
2. executar a suite backend com PostgreSQL e a suite de interface;
3. executar os testes de implantacao em Windows PowerShell 5.1;
4. montar e validar o pacote offline.

No GitHub Actions, aguarde os jobs `quality` e `release` ficarem verdes. Depois confira que a GitHub Release publicada contem exatamente estes dois assets:

```text
smart-crm-manual-pg11-vX.Y.Z.zip
smart-crm-manual-pg11-vX.Y.Z.zip.sha256
```

Se a Action falhar, se a release estiver como rascunho ou preliminar, ou se houver asset adicional ou ausente, pare. Nao corrija uma release existente por cima: corrija o codigo e publique uma nova versao.

## 3. Copiar a release lado a lado

O caminho recomendado baixa a release publica por uma tag explicita. No servidor, abra PowerShell como Administrador e execute:

```powershell
$tag = "vX.Y.Z"
$bootstrap = Join-Path $env:TEMP "stage-smartcrm-$tag.ps1"
[Net.ServicePointManager]::SecurityProtocol = (
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
)
Invoke-WebRequest `
    -Uri "https://raw.githubusercontent.com/lamarcon/smart_crm/$tag/deploy/manual-windows-pg11/stage-github-release.ps1" `
    -OutFile $bootstrap `
    -UseBasicParsing
& $bootstrap -Tag $tag
$releaseRoot = "C:\brbots\apps\smart-crm-$tag"
$serviceAccount = "$env:COMPUTERNAME\SmartCRMService"
```

O resultado obrigatorio inclui `RELEASE_STAGED=PASS`, o SHA-256 e o caminho `C:\brbots\apps\smart-crm-vX.Y.Z`. O script aceita somente uma release publicada, nao preliminar, com os dois assets exatos; valida o hash do download e o `MANIFEST.sha256` interno antes de promover a pasta. Ele apenas prepara a release lado a lado: nao altera banco, `server.env`, tarefa agendada ou Apache e nao ativa a nova versao.

Esse fluxo nao exige token do GitHub, cliente Git ou checkout no servidor. Nao grave credencial do GitHub no servidor. Continue obrigatoriamente pelas secoes 3.1, 4, 5, 6 e 8; o cutover e o rollback permanecem explicitos.

Como alternativa manual de contingencia, cada pacote pode ser extraido em uma pasta imutavel no formato `C:\brbots\apps\smart-crm-<SHA>`. Exemplo:

```powershell
$releaseSha = "<SHA>"
$releaseRoot = "C:\brbots\apps\smart-crm-$releaseSha"
$serviceAccount = "$env:COMPUTERNAME\SmartCRMService"
```

Nesse caminho manual, confira o ZIP antes de extrair:

```powershell
Get-FileHash .\smart-crm-manual-pg11-$releaseSha.zip -Algorithm SHA256
Get-Content .\smart-crm-manual-pg11-$releaseSha.zip.sha256
```

Os hashes devem ser identicos. Crie uma pasta nova e extraia nela. Nao sobrescreva a release ativa, nao apague a release anterior e nao extraia por cima de `C:\brbots\apps\smart-crm`. `git pull` e proibido nesse servidor para este pacote offline.

A pasta nova deve conter `app`, `migrations`, `migrations_control`, `wheelhouse`, `alembic.ini`, `alembic-control.ini`, `requirements-runtime.txt`, `MANIFEST.sha256` e `deploy`.

## 3.1. Proteger somente os databases do Smart CRM no PostgreSQL compartilhado

O listener global da instancia permanece como esta porque `DW_CMS` e `DW_PRODUTOS` dependem de acesso remoto. Nao altere `listen_addresses`, nao reinicie o servico PostgreSQL e nao mude as regras existentes desses databases.

Descubra o arquivo ativo pela configuracao do servico, sem senha e sem consultar o banco (`SHOW hba_file` exige superusuario ou `pg_read_all_settings`, que a role `smartcrm` corretamente nao tem):

```powershell
$svc = Get-CimInstance Win32_Service -Filter "Name='postgresql-x64-11'"
if ($svc.PathName -notmatch '-D\s+"?([^"]+?)"?(\s+-|$)') {
    throw "Nao foi possivel ler a pasta de dados do PostgreSQL: $($svc.PathName)"
}
$dataDir = $Matches[1].Trim()
$custom = Select-String -LiteralPath (Join-Path $dataDir "postgresql.conf") `
    -Pattern "^\s*hba_file\s*=\s*'([^']+)'" | Select-Object -Last 1
$pgHbaPath = if ($custom) { $custom.Matches[0].Groups[1].Value } else { Join-Path $dataDir "pg_hba.conf" }
if (-not (Test-Path -LiteralPath $pgHbaPath -PathType Leaf)) {
    throw "pg_hba.conf ativo nao foi localizado."
}
$pgHbaPath
```

Em uma atualizacao, se o arquivo ja contem `BEGIN SMARTCRM LOCAL ONLY`, as regras ja existem: pule o restante desta secao e use apenas `$pgHbaPath` na secao 4. Caso contrario, guarde uma copia:

```powershell
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
. "$releaseRoot\deploy\manual-windows-pg11\deployment-policy.ps1"
$legacy = Read-SmartCrmEnvironment `
    -Path $envPath `
    -AllowedKeys @(Get-SmartCrmEnvironmentAllowedKeys)

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
. "$releaseRoot\deploy\manual-windows-pg11\deployment-policy.ps1"
$settings = Read-SmartCrmEnvironment `
    -Path C:\ProgramData\SmartCRM\server.env `
    -AllowedKeys @(Get-SmartCrmEnvironmentAllowedKeys)
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

## 5.1. Configurar o SMTP de convites e recuperacao de senha

Convites e recuperacao de senha enviam e-mail pelo SMTP da empresa. As chaves nao secretas ficam no `server.env`; a senha fica somente em `C:\ProgramData\SmartCRM\service-secrets\smtp-password.bin`, protegida por DPAPI para `SmartCRMService`. O `server.env` rejeita `SMART_CRM_SMTP_PASSWORD`, SMTP sem TLS (`SMART_CRM_SMTP_TLS_MODE` aceita somente `starttls` ou `implicit_tls`) e placeholders `REPLACE_WITH_*`. Nenhum comando abaixo imprime a senha.

### Staging (sem tocar na release ativa)

1. Rode `install-offline.ps1` da nova release como Administrador: ele cria `service-secrets` com ACL restrita a `SYSTEM`, Administradores e `SmartCRMService` e nao altera a tarefa ativa.
2. Gere um sucessor do `server.env` que preserva cada linha existente byte a byte e acrescenta as chaves SMTP (os valores nunca sao reinterpretados, entao caminhos com `\` e URLs ficam intactos):

```powershell
$envPath = "C:\ProgramData\SmartCRM\server.env"
$nextEnv = "C:\ProgramData\SmartCRM\server.env.next"
. "$releaseRoot\deploy\manual-windows-pg11\deployment-policy.ps1"
$lines = Add-SmartCrmSmtpEnvironmentLines `
    -Path $envPath `
    -SmtpHost smtp.exemplo.com.br `
    -Port 587 `
    -Username crm@exemplo.com.br `
    -FromAddress crm@exemplo.com.br `
    -TlsMode starttls `
    -TimeoutSeconds 10
[IO.File]::WriteAllLines($nextEnv, $lines, (New-Object Text.UTF8Encoding($false)))
$serviceSid = (New-Object Security.Principal.NTAccount($serviceAccount)).Translate([Security.Principal.SecurityIdentifier]).Value
icacls $nextEnv /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' "*$($serviceSid):R" | Out-Null
Remove-Variable lines -ErrorAction SilentlyContinue
```

Use `-TlsMode implicit_tls -Port 465` quando o provedor exigir TLS implicito. Em instalacao nova, o `server.env` ja nasce com as chaves SMTP como placeholders: edite somente esses valores.

3. Grave a senha SMTP como `SmartCRMService`. Abra `runas /user:NOME-DO-SERVIDOR\SmartCRMService powershell.exe` e, nessa janela:

```powershell
& "$releaseRoot\deploy\manual-windows-pg11\set-smtp-password.ps1"
```

O prompt oculta a senha, pede confirmacao, grava o arquivo DPAPI de forma atomica e confirma que ele abre para essa conta. O resultado esperado e `smtp password secret: STORED`.

4. Ainda na janela de `SmartCRMService`, valide o sucessor antes do corte. A validacao abre o segredo DPAPI, rejeita ACL ampla e configuracao incompleta:

```powershell
& "$releaseRoot\deploy\manual-windows-pg11\start-smart-crm.ps1" `
    -AppRoot $releaseRoot -EnvFile C:\ProgramData\SmartCRM\server.env.next -ValidateOnly
```

O resultado obrigatorio e `smart crm environment: VALID`.

### Smoke test SMTP

Na mesma janela de `SmartCRMService`, envie uma mensagem de teste para uma caixa controlada pela empresa:

```powershell
& "$releaseRoot\deploy\manual-windows-pg11\start-smart-crm.ps1" `
    -AppRoot $releaseRoot -EnvFile C:\ProgramData\SmartCRM\server.env.next `
    -SmtpSmokeTo responsavel@exemplo.com.br
```

O resultado obrigatorio e `smtp smoke: PASS`. Uma falha mostra somente um codigo (`smtp_auth_failed`, `smtp_tls_failed`, `smtp_timeout`, `smtp_password_unreadable`...), nunca a senha ou a resposta do servidor. O smoke test nao altera banco, tarefa nem release ativa.

### Corte

Com `VALID` e `PASS`, faca backup do arquivo atual e promova o sucessor imediatamente antes do inicializador da secao 6:

```powershell
Copy-Item -LiteralPath C:\ProgramData\SmartCRM\server.env -Destination C:\ProgramData\SmartCRM\server.env.pre-smtp
Move-Item -LiteralPath C:\ProgramData\SmartCRM\server.env.next -Destination C:\ProgramData\SmartCRM\server.env -Force
```

O inicializador valida a configuracao como Administrador sem abrir o segredo (`-SkipSecretDecryption`); a tarefa inicia como `SmartCRMService`, que abre o segredo no startup e falha fechada se ele estiver ilegivel. Nesse caso o health check falha e o inicializador restaura a tarefa anterior.

### Rollback

Releases anteriores nao conhecem as chaves SMTP e recusam o `server.env` novo. Ao voltar para a release anterior, restaure tambem o arquivo salvo:

```powershell
Copy-Item -LiteralPath C:\ProgramData\SmartCRM\server.env.pre-smtp -Destination C:\ProgramData\SmartCRM\server.env -Force
```

Mantenha `smtp-password.bin`; ele e inofensivo para a release anterior e evita redigitar a senha no proximo corte.

### Rotacao da senha SMTP

Troque a senha no provedor, abra a janela `runas` de `SmartCRMService`, execute `set-smtp-password.ps1` de novo, rode o smoke test com o `server.env` ativo e reinicie a tarefa `SmartCRM` para o processo carregar o novo segredo. Nao copie a senha para chat, ticket, commit ou `server.env`.

## 5.2. Balanceador (SLB) na frente do Apache (opcional)

O limite de tentativas de login conta erros por IP (30 em 15 minutos bloqueiam o IP por 15 minutos). Se um balanceador de camada 7 (HTTP) fica na frente do Apache, o CRM enxerga o IP do balanceador para todos os usuarios e alguns erros somados bloqueiam o login de todos. Balanceador de camada 4 (TCP), que entrega o IP real ao Apache, nao precisa deste passo.

1. Confirme o problema: no `logs\smart-crm-access.log` do Apache, se praticamente todas as linhas mostram o mesmo IP (ou poucos IPs do provedor), o balanceador e de camada 7.
2. Obtenha com o provedor o IP ou a faixa CIDR **de onde o balanceador conecta ao servidor** e confirme que ele envia `X-Forwarded-For` com o IP do usuario.
3. Na janela autorizada, acrescente ao `C:\ProgramData\SmartCRM\server.env` (sem `*`, sem `0.0.0.0/0`; faixas IPv4 de `/8` a `/32`):

```text
SMART_CRM_TRUSTED_PROXY_IPS=10.0.0.0/24
```

4. Valide, reinicie a tarefa e confirme no `smart-crm.log`/auditoria que os IPs dos usuarios aparecem variados:

```powershell
& C:\brbots\apps\smart-crm\deploy\manual-windows-pg11\start-smart-crm.ps1 -ValidateOnly -SkipSecretDecryption
Stop-ScheduledTask -TaskName SmartCRM; Start-ScheduledTask -TaskName SmartCRM
```

O Apache (`127.0.0.1`) continua sempre confiavel; so os enderecos listados podem informar o IP do usuario, e um cabecalho forjado pelo proprio usuario e ignorado. Releases anteriores nao conhecem a chave: para voltar a uma delas, remova a linha antes do rollback. Sem a linha, o comportamento e o de hoje.

## 6. Migrar e trocar a tarefa na janela autorizada

Este passo altera os dois schemas e troca a tarefa que atende a porta 8080. Execute somente dentro da janela aprovada.

```powershell
$serviceCredential = Get-Credential `
    -UserName $serviceAccount `
    -Message "Credencial da conta dedicada do Smart CRM"
$expectedVersion = (& "$releaseRoot\.venv\Scripts\python.exe" `
    -c "from app.version import APP_VERSION; print(APP_VERSION)").Trim()

& "$releaseRoot\deploy\manual-windows-pg11\initialize-and-test.ps1" `
    -AppRoot $releaseRoot `
    -EnvFile C:\ProgramData\SmartCRM\server.env `
    -SharedPostgres `
    -PgHbaPath $pgHbaPath `
    -TenantSlug brbots `
    -ExpectedVersion $expectedVersion `
    -BackupAcknowledged `
    -ServiceCredential $serviceCredential
```

O inicializador executa, nesta ordem:

1. `alembic-control.ini` ate `d5f0a8c3e7b2` e confirma exatamente esse head;
2. executa a migracao tenant ate o head empacotado (`b4e2c9a7d6f1`) por uma tarefa temporaria sob `SmartCRMService`, usando `FleetService` e os segredos DPAPI;
3. exige evidencia de que o tenant e o perfil central chegaram ao mesmo head antes de alterar a tarefa web;
4. exporta a tarefa anterior para a pasta de recuperacao, para a tarefa e confirma que a porta 8080 foi liberada;
5. registra a tarefa `SmartCRM` na release imutavel usando `SmartCRMService`;
6. aceita sucesso somente quando a tarefa, `http://127.0.0.1:8080/health` e `/api/version` comprovam a release esperada.

A revisao corretiva `a8d4e6f2b1c9` repara de forma idempotente funil e payloads
incompletos sob FORCE RLS, sem SQL manual. A linhagem tenant desta release termina em
`b4e2c9a7d6f1`, que cria `account_action_tokens` (convites e recuperacao de senha) com RLS. Nao execute
`alembic.ini` diretamente e nao altere `expected_tenant_revision` manualmente.

Qualquer falha antes da troca deixa a tarefa atual intacta. Se uma falha ocorrer
depois da troca, o inicializador restaura e reinicia a tarefa anterior; se a
restauracao automatica falhar, a mensagem informa o XML preservado para recuperacao.
O startup web nunca executa Alembic. O Apache permanece inalterado.

O resultado obrigatorio e:

```text
{"status":"ok"}
LOCAL GATE: PASS release=<VERSAO> tenant=brbots
```

## 7. Registrar a BRBots e criar o primeiro administrador

DPAPI e vinculado a conta Windows. Abra PowerShell interativo como `SmartCRMService`, por exemplo com `runas /user:NOME-DO-SERVIDOR\SmartCRMService powershell.exe`, e execute os comandos abaixo nessa janela. Nao cadastre como Administrador ou `SYSTEM`.

```powershell
$releaseRoot = "C:\brbots\apps\smart-crm-<SHA>"
Set-Location $releaseRoot
. "$releaseRoot\deploy\manual-windows-pg11\deployment-policy.ps1"
$settings = Read-SmartCrmEnvironment `
    -Path C:\ProgramData\SmartCRM\server.env `
    -AllowedKeys @(Get-SmartCrmEnvironmentAllowedKeys)
$env:SMART_CRM_CONTROL_DATABASE_URL = $settings.SMART_CRM_CONTROL_DATABASE_URL
$env:SMART_CRM_SECRET_STORE = $settings.SMART_CRM_TENANT_SECRET_STORE
$env:SMART_CRM_TENANT_SECRET_STORE = $settings.SMART_CRM_TENANT_SECRET_STORE
$env:SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK = "1"

$tenantDsn = "postgresql+psycopg://smartcrm:$($settings.SMART_CRM_DB_PASSWORD)@127.0.0.1:5432/smartcrm?connect_timeout=5"
Set-Clipboard -Value $tenantDsn
& .\.venv\Scripts\python.exe -m app.admin_cli `
    register-tenant brbots --display-name "brbots" `
    --secret-ref brbots-db --expected-revision a8d4e6f2b1c9
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

O Windows Server 2016 nao traz `curl.exe`. Nele, confira o Apache pelo PowerShell (esperado `401` enquanto a autenticacao de homologacao estiver ativa) e valide o restante pelo navegador:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
try { (Invoke-WebRequest https://sc2030.brbots.com/ -UseBasicParsing -TimeoutSec 15).StatusCode }
catch { [int]$_.Exception.Response.StatusCode }
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
2. preserve logs, `server.env`, segredos DPAPI e evidencias; ao voltar para uma release sem SMTP, restaure `server.env.pre-smtp` (secao 5.1);
3. restaure a tarefa anterior ou registre novamente `install-scheduled-task.ps1` com o caminho exato da release anterior e a mesma `SmartCRMService`;
4. se a versao anterior nao for compativel com os schemas migrados, restaure os backups verificados de `smartcrm` e `smartcrm_control` somente com autorizacao explicita de rollback;
5. valide loopback, Apache e contagens antes de reabrir o acesso.

Nao use `git reset --hard`, nao execute downgrade Alembic improvisado e nao apague nenhum database. Rollback de um tenant nunca redireciona para o banco de outro tenant.

## 10. Proximas empresas

Cada nova empresa recebe outro slug e outro PostgreSQL exclusivo. O operador cria database/role no servidor escolhido, migra ate `b4e2c9a7d6f1` pelo fluxo de frota, cadastra um `secret_ref` opaco via `register-tenant` e ativa o primeiro administrador via prompt. Bancos remotos usam TLS `verify-full` com CA. Nao existe descoberta automatica de bancos e o navegador nunca escolhe o DSN ou o tenant autenticado.
