# Smart CRM em Windows, Apache e sc2030.brbots.com

Este é o procedimento canônico para substituir o aplicativo descontinuado no
servidor Windows atual. O CRM roda em Python/Uvicorn e PostgreSQL no próprio
servidor. O Apache continua como única entrada pública em 80/443.

Estado observado em 2026-09-01:

- `sc2030.brbots.com` aponta para `200.98.200.206`;
- HTTP responde por Apache 2.4.62 Win64;
- HTTPS apresenta certificado expirado e retorna 503.

Não anuncie o acesso ao cliente e não use dados reais antes de concluir todo o
UAT deste documento.

## 1. Pré-requisitos

Abra PowerShell como Administrador e confirme:

```powershell
git --version
$python311 = "C:\brbots\python\python.exe"
& $python311 --version
& $python311 -c "import sys; assert sys.version_info[:2] == (3, 11), sys.version"
& "C:\Apache24\bin\httpd.exe" -v
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" --version
```

Instale, se estiverem ausentes:

- Git for Windows;
- Python 3.11 x64 já existente em `C:\brbots\python\python.exe`;
- PostgreSQL 17 x64, instalado lado a lado na porta 5433;

No instalador do PostgreSQL 17, use `C:\Program Files\PostgreSQL\17`
como diretório do programa, um diretório de dados exclusivo da versão 17 e a porta
5433. Não selecione o diretório de dados da versão 11. O novo serviço esperado é
`postgresql-x64-17`.
- Apache 2.4 com OpenSSL, já existente no servidor.

Não altere, reinicie ou remova o PostgreSQL 11. Ele continua com serviço,
configuração, diretório de dados e porta 5432 próprios. Antes de instalar o
PostgreSQL 17, confirme que a porta escolhida está livre:

```powershell
if (Get-NetTCPConnection -State Listen -LocalPort 5433 -ErrorAction SilentlyContinue) {
    throw 'Porta 5433 já está em uso. Pare e escolha outra porta exclusiva para o PostgreSQL 17.'
}
```

Descubra o serviço e o caminho real do Apache antes de continuar:

```powershell
Get-Service | Where-Object Name -Match 'Apache|httpd|postgresql'
Get-CimInstance Win32_Service |
    Where-Object Name -Match 'Apache|httpd' |
    Select-Object Name, StartName, PathName
```

Substitua `C:\Apache24` nos comandos se o `PathName` mostrar outro diretório.
Registre também `StartName`; essa conta precisará ler a chave TLS.

## 2. Backup do aplicativo antigo

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = "C:\Backups\SmartCRM\$stamp"
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item "C:\Apache24\conf\httpd.conf" $backup
Copy-Item "C:\Apache24\conf\extra" "$backup\extra" -Recurse
& "C:\Apache24\bin\httpd.exe" -S 2>&1 | Set-Content "$backup\apache-vhosts.txt"
& "C:\Apache24\bin\httpd.exe" -M 2>&1 | Set-Content "$backup\apache-modules.txt"
Write-Output $backup
```

Não remova ainda o virtual host antigo. Ele permanece como rollback até o UAT
final.

## 3. Clonar e fixar a versão pelo Git

Use este procedimento somente depois de o commit desejado estar no GitHub.

```powershell
New-Item -ItemType Directory -Path "C:\Apps" -Force | Out-Null
Set-Location "C:\Apps"
git clone https://github.com/lamarcon/smart_crm.git smart-crm
Set-Location "C:\Apps\smart-crm"
git switch main
git pull --ff-only origin main
git status --short
git rev-parse HEAD
```

Pare se `git status --short` exibir qualquer arquivo. Registre o SHA implantado.
Nunca use `git add .` no servidor.

## 4. Preparar o Python

```powershell
Set-Location "C:\Apps\smart-crm"
$python311 = "C:\brbots\python\python.exe"
& $python311 -c "import sys; assert sys.version_info[:2] == (3, 11), sys.version"
& $python311 -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install .
& ".\.venv\Scripts\python.exe" -m compileall -q app
```

O projeto exige Python `>=3.11,<3.13`. Use o Python 3.11 existente; não use Python 3.13.

## 5. Criar o segredo fora do Git

Crie o diretório externo e gere uma senha hexadecimal de 64 caracteres:

```powershell
New-Item -ItemType Directory -Path "C:\ProgramData\SmartCRM" -Force | Out-Null
Copy-Item "deploy\windows-apache\server.env.example" `
    "C:\ProgramData\SmartCRM\server.env"
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$rng.Dispose()
$dbPassword = -join ($bytes | ForEach-Object { $_.ToString('x2') })
$envPath = "C:\ProgramData\SmartCRM\server.env"
$envText = Get-Content -LiteralPath $envPath -Raw
$envText = $envText.Replace('REPLACE_WITH_64_HEX_CHARACTERS', $dbPassword)
[System.IO.File]::WriteAllText($envPath, $envText, [System.Text.UTF8Encoding]::new($false))
icacls $envPath /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F'
```

Não imprima `$dbPassword`, não coloque `server.env` no clone e não envie o
arquivo por Git, e-mail ou chat.

## 6. Criar o banco PostgreSQL

Edite `postgresql.conf` e mantenha somente conexões locais:

```text
listen_addresses = 'localhost'
port = 5433
password_encryption = 'scram-sha-256'
```

Em `pg_hba.conf`, coloque esta regra antes de regras mais amplas:

```text
host    smartcrm    smartcrm    127.0.0.1/32    scram-sha-256
```

Reinicie somente o serviço novo do PostgreSQL 17. Não reinicie o serviço do PostgreSQL 11:

```powershell
Restart-Service postgresql-x64-17
```

Abra o cliente da instalação PostgreSQL 17 explicitamente na porta 5433:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h 127.0.0.1 -p 5433 -U postgres -d postgres
```

No prompt do `psql`, execute:

```sql
CREATE ROLE smartcrm LOGIN;
\password smartcrm
CREATE DATABASE smartcrm OWNER smartcrm ENCODING 'UTF8';
REVOKE CONNECT ON DATABASE smartcrm FROM PUBLIC;
GRANT CONNECT ON DATABASE smartcrm TO smartcrm;
```

Quando `\password` solicitar a senha, use exatamente o valor armazenado em
`C:\ProgramData\SmartCRM\server.env`. Ao terminar:

```powershell
Remove-Variable dbPassword -ErrorAction SilentlyContinue
```

O PostgreSQL cria banco e usuário. O Alembic cria as tabelas; não execute
`CREATE TABLE` manualmente.

## 7. Validar o ambiente e criar as tabelas

```powershell
Set-Location "C:\Apps\smart-crm"
& ".\deploy\windows-apache\start-smart-crm.ps1" -ValidateOnly
$settings = Get-Content "C:\ProgramData\SmartCRM\server.env" |
    Where-Object { $_ -and -not $_.StartsWith('#') } |
    Out-String |
    ConvertFrom-StringData
$env:SMART_CRM_DATABASE_URL = "postgresql+psycopg://$($settings.SMART_CRM_DB_USER):$($settings.SMART_CRM_DB_PASSWORD)@127.0.0.1:$($settings.SMART_CRM_DB_PORT)/$($settings.SMART_CRM_DB_NAME)?connect_timeout=5"
& ".\.venv\Scripts\python.exe" -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Migração Alembic falhou.' }
& ".\.venv\Scripts\python.exe" -m alembic current
Remove-Item Env:SMART_CRM_DATABASE_URL
```

Pare aqui se a migração falhar. Não altere o Apache.

## 8. Registrar e testar o runtime local

```powershell
Set-Location "C:\Apps\smart-crm"
& ".\deploy\windows-apache\install-scheduled-task.ps1"
Start-Sleep -Seconds 5
Get-ScheduledTask -TaskName SmartCRM
Get-ScheduledTaskInfo -TaskName SmartCRM
$health = Invoke-RestMethod "http://127.0.0.1:8080/health"
$health | ConvertTo-Json -Compress
```

Resultado obrigatório:

```json
{"status":"ok","database":"ok"}
```

Confirme que PostgreSQL e Uvicorn não escutam em endereços públicos:

```powershell
Get-NetTCPConnection -State Listen |
    Where-Object LocalPort -In 5432,5433,8080 |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

As três portas devem mostrar somente `127.0.0.1` ou `::1`: 5432 para o
PostgreSQL 11 existente, 5433 para o PostgreSQL 17 do CRM e 8080 para o CRM.
No Firewall do Windows, mantenha regras públicas apenas para 80 e 443.

## 9. Renovar o certificado no PunchSalad

O certificado atual está expirado. No PunchSalad, gere um novo certificado para
`sc2030.brbots.com` e prefira validação DNS. Crie o TXT solicitado em
`_acme-challenge.sc2030.brbots.com`, aguarde a validação e baixe:

- certificado do domínio;
- cadeia intermediária/CA bundle;
- chave privada correspondente.

Crie o diretório TLS fora do Git:

```powershell
New-Item -ItemType Directory -Path "C:\ProgramData\SmartCRM\tls" -Force | Out-Null
```

Monte o arquivo PEM com o certificado do domínio primeiro e a cadeia depois:

```powershell
Get-Content "C:\Downloads\sc2030-certificate.pem", `
    "C:\Downloads\sc2030-ca-bundle.pem" |
    Set-Content "C:\ProgramData\SmartCRM\tls\sc2030.brbots.com-fullchain.pem" -Encoding ascii
Copy-Item "C:\Downloads\sc2030-private-key.pem" `
    "C:\ProgramData\SmartCRM\tls\sc2030.brbots.com-privkey.pem"
```

Valide hostname, validade e correspondência entre certificado e chave:

```powershell
$openssl = "C:\Apache24\bin\openssl.exe"
$tls = "C:\ProgramData\SmartCRM\tls"
& $openssl x509 -in "$tls\sc2030.brbots.com-fullchain.pem" -noout -subject -issuer -dates -ext subjectAltName
& $openssl x509 -checkend 604800 -noout -in "$tls\sc2030.brbots.com-fullchain.pem"
if ($LASTEXITCODE -ne 0) { throw 'Certificado expira em menos de sete dias.' }
& $openssl x509 -pubkey -noout -in "$tls\sc2030.brbots.com-fullchain.pem" -out "$tls\certificate-public.pem"
& $openssl pkey -pubin -in "$tls\certificate-public.pem" -outform DER -out "$tls\certificate-public.der"
& $openssl pkey -in "$tls\sc2030.brbots.com-privkey.pem" -pubout -outform DER -out "$tls\key-public.der"
Get-FileHash "$tls\certificate-public.der", "$tls\key-public.der" -Algorithm SHA256
Remove-Item "$tls\certificate-public.pem", "$tls\certificate-public.der", "$tls\key-public.der"
```

Os dois hashes devem ser idênticos. Se forem diferentes, pare. A chave não
corresponde ao certificado.

Restrinja a chave à conta do serviço Apache, SYSTEM e Administradores. Substitua
`APACHE_SERVICE_ACCOUNT` pelo `StartName` obtido na etapa 1:

```powershell
$key = "C:\ProgramData\SmartCRM\tls\sc2030.brbots.com-privkey.pem"
icacls $key /inheritance:r /grant:r `
    '*S-1-5-18:F' `
    '*S-1-5-32-544:F' `
    'APACHE_SERVICE_ACCOUNT:R'
```

## 10. Preparar o Apache

No `httpd.conf`, habilite uma única ocorrência destes módulos:

```apache
LoadModule alias_module modules/mod_alias.so
LoadModule auth_basic_module modules/mod_auth_basic.so
LoadModule authn_core_module modules/mod_authn_core.so
LoadModule authn_file_module modules/mod_authn_file.so
LoadModule authz_core_module modules/mod_authz_core.so
LoadModule headers_module modules/mod_headers.so
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_http_module modules/mod_proxy_http.so
LoadModule rewrite_module modules/mod_rewrite.so
LoadModule socache_shmcb_module modules/mod_socache_shmcb.so
LoadModule ssl_module modules/mod_ssl.so
```

Crie a senha HTTP, diferente da senha PostgreSQL:

```powershell
New-Item -ItemType Directory -Path "C:\ProgramData\SmartCRM\apache" -Force | Out-Null
& "C:\Apache24\bin\htpasswd.exe" -c `
    "C:\ProgramData\SmartCRM\apache\.htpasswd-smart-crm" `
    crm-homologacao
```

Copie o virtual host e inclua-o no final de `httpd.conf`:

```powershell
Copy-Item "C:\Apps\smart-crm\deploy\windows-apache\httpd-sc2030.conf.example" `
    "C:\Apache24\conf\extra\httpd-smart-crm.conf"
Add-Content "C:\Apache24\conf\httpd.conf" `
    'Include conf/extra/httpd-smart-crm.conf'
& "C:\Apache24\bin\httpd.exe" -t
& "C:\Apache24\bin\httpd.exe" -S
```

Não deixe dois virtual hosts ativos para `sc2030.brbots.com`. Desabilite a
inclusão do host antigo somente depois de preservar o backup da etapa 2.

Execute `httpd.exe -t` novamente. Somente com `Syntax OK`:

```powershell
& "C:\Apache24\bin\httpd.exe" -k restart
```

## 11. UAT de corte

Sem credenciais, HTTPS deve responder 401:

```powershell
curl.exe -I https://sc2030.brbots.com/
```

Com o usuário criado, `/health` deve responder o JSON exato:

```powershell
curl.exe --user crm-homologacao https://sc2030.brbots.com/health
```

Resultado obrigatório:

```json
{"status":"ok","database":"ok"}
```

Teste também a página inicial, `/api/workspace`, logs do Apache e
`C:\ProgramData\SmartCRM\logs\smart-crm.log`. Não use `-k`/`--insecure`; isso
mascara falhas de certificado.

## 12. Backup e atualização por Git

Antes de atualizar:

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = "C:\Backups\SmartCRM\$stamp"
New-Item -ItemType Directory -Path $backup -Force | Out-Null
$settings = Get-Content "C:\ProgramData\SmartCRM\server.env" |
    Where-Object { $_ -and -not $_.StartsWith('#') } |
    Out-String |
    ConvertFrom-StringData
$env:PGPASSWORD = $settings.SMART_CRM_DB_PASSWORD
& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" `
    -h 127.0.0.1 -p $settings.SMART_CRM_DB_PORT -U smartcrm -d smartcrm -Fc `
    -f "$backup\smartcrm.dump"
if ($LASTEXITCODE -ne 0) { throw 'Backup PostgreSQL falhou.' }
Remove-Item Env:PGPASSWORD
git rev-parse HEAD | Set-Content "$backup\application.sha"
Get-FileHash "$backup\smartcrm.dump" -Algorithm SHA256 |
    Format-List | Set-Content "$backup\smartcrm.dump.sha256.txt"
```

Depois do backup:

```powershell
Stop-ScheduledTask -TaskName SmartCRM
Set-Location "C:\Apps\smart-crm"
git status --short
git fetch --prune origin
git merge --ff-only origin/main
& ".\.venv\Scripts\python.exe" -m pip install .
```

Repita a etapa 7 para aplicar migrações. Depois:

```powershell
Start-ScheduledTask -TaskName SmartCRM
Start-Sleep -Seconds 5
Invoke-RestMethod "http://127.0.0.1:8080/health"
curl.exe --user crm-homologacao https://sc2030.brbots.com/health
```

## 13. Rollback

Se o CRM ou o proxy falhar antes da liberação:

```powershell
Stop-ScheduledTask -TaskName SmartCRM
Copy-Item "$backup\httpd.conf" "C:\Apache24\conf\httpd.conf" -Force
Copy-Item "$backup\extra\*" "C:\Apache24\conf\extra" -Recurse -Force
& "C:\Apache24\bin\httpd.exe" -t
if ($LASTEXITCODE -ne 0) { throw 'Configuração Apache de rollback inválida.' }
& "C:\Apache24\bin\httpd.exe" -k restart
```

Não apague o banco. Se uma migração for incompatível com o código anterior,
restaure `smartcrm.dump` somente em janela de manutenção e após confirmar o SHA
e o hash do backup.

## Checklist final

- [ ] Commit/SHA implantado registrado.
- [ ] `server.env` fora do Git e ACL restrita.
- [ ] PostgreSQL escutando somente em localhost.
- [ ] Alembic no `head`.
- [ ] Tarefa `SmartCRM` como SYSTEM e reinício configurado.
- [ ] Uvicorn somente em `127.0.0.1:8080`.
- [ ] Certificado renovado, hostname correto e mais de sete dias de validade.
- [ ] Certificado e chave com hashes públicos idênticos.
- [ ] Apache retorna `Syntax OK`.
- [ ] HTTP redireciona para HTTPS e ACME permanece público.
- [ ] HTTPS sem credenciais retorna 401.
- [ ] HTTPS autenticado `/health` retorna o JSON exato.
- [ ] Backup externo e rollback testados.
- [ ] Ambiente apenas com dados fictícios.

## Referências técnicas

- Apache reverse proxy: https://httpd.apache.org/docs/2.4/howto/reverse_proxy.html
- Apache mod_ssl: https://httpd.apache.org/docs/2.4/mod/mod_ssl.html
- Tarefas agendadas: https://learn.microsoft.com/powershell/module/scheduledtasks/register-scheduledtask
- PostgreSQL 17: https://www.postgresql.org/docs/17/
