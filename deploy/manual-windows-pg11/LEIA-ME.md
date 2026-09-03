# Instalação manual do Smart CRM

Este pacote é para o servidor Windows Server 2016 informado. Ele usa o Python 3.11 em `C:\brbots\python\python.exe` e o PostgreSQL 11 existente em `127.0.0.1:5432`. Não instala Git, não acessa a internet e não altera o serviço `postgresql-x64-11`.

PostgreSQL 11 não recebe correções oficiais. Esta implantação reduz mudanças no servidor para cumprir o prazo, mas a atualização do banco continua obrigatória depois da estabilização.

## 1. Copiar e conferir

Copie o ZIP e o arquivo `.sha256` para o servidor. Confira o hash antes de extrair:

```powershell
Get-FileHash .\smart-crm-manual-pg11-*.zip -Algorithm SHA256
Get-Content .\smart-crm-manual-pg11-*.zip.sha256
```

Os hashes devem ser idênticos. Extraia o conteúdo interno diretamente em `C:\brbots\apps\smart-crm`. A pasta deve conter `app`, `migrations`, `wheelhouse`, `alembic.ini`, `requirements-runtime.txt`, `MANIFEST.sha256` e `deploy`.

## 2. Instalar offline

Abra PowerShell como Administrador:

```powershell
Set-Location C:\brbots\apps\smart-crm
Set-ExecutionPolicy -Scope Process Bypass
& .\deploy\manual-windows-pg11\test-package-integrity.ps1
& .\deploy\manual-windows-pg11\install-offline.ps1
```

O segundo comando valida Python 3.11 x64, serviço PostgreSQL 11, porta local 5432 e wheelhouse antes de criar a virtualenv. Ele gera `C:\ProgramData\SmartCRM\server.env` uma única vez e nunca sobrescreve esse segredo.

## 3. Criar banco e role

Este é o único passo que altera o PostgreSQL. Ele não para, reinicia ou reconfigura o serviço. Carregue a senha gerada e abra o `psql`:

```powershell
$settings = Get-Content C:\ProgramData\SmartCRM\server.env |
    Where-Object { $_ -and -not $_.StartsWith('#') } |
    Out-String | ConvertFrom-StringData
$settings.SMART_CRM_DB_PASSWORD | Set-Clipboard
& "C:\Program Files\PostgreSQL\11\bin\psql.exe" -h 127.0.0.1 -p 5432 -U postgres -d postgres
```

No `psql`, verifique primeiro se os objetos já existem:

```sql
\du smartcrm
\l smartcrm
```

Se a role não existir:

```sql
CREATE ROLE smartcrm LOGIN;
\password smartcrm
```

Cole a senha do clipboard quando solicitado. Se a role já existir, não a recrie nem apague; apenas execute `\password smartcrm` para alinhar a senha.

Se o database não existir:

```sql
CREATE DATABASE smartcrm OWNER smartcrm ENCODING 'UTF8';
REVOKE CONNECT ON DATABASE smartcrm FROM PUBLIC;
GRANT CONNECT ON DATABASE smartcrm TO smartcrm;
```

Se o database já existir, confirme o proprietário com `\l smartcrm`. Pare e investigue se não pertencer a `smartcrm`. Não execute `DROP DATABASE`, `DROP ROLE` ou `CREATE TABLE`.

Ao terminar:

```powershell
Set-Clipboard -Value ""
Remove-Variable settings -ErrorAction SilentlyContinue
```

## 4. Criar tabelas e testar localmente

```powershell
Set-Location C:\brbots\apps\smart-crm
& .\deploy\manual-windows-pg11\initialize-and-test.ps1
```

O resultado obrigatório no final é:

```text
{"status":"ok","database":"ok"}
LOCAL GATE: PASS. O Apache pode ser configurado.
```

Se houver falha, pare. O script não altera o Apache. Consulte `C:\ProgramData\SmartCRM\logs\smart-crm.log`.

## 5. Preparar o Apache somente após o gate local

Descubra primeiro o processo e o caminho reais:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 80,443 |
    Select-Object LocalAddress,LocalPort,OwningProcess
Get-CimInstance Win32_Process |
    Where-Object { $_.ProcessId -in (Get-NetTCPConnection -State Listen -LocalPort 80,443).OwningProcess } |
    Select-Object ProcessId,ExecutablePath,CommandLine
```

Faça backup de `httpd.conf` e da pasta `conf\extra`. Renove o certificado do PunchSalad para `sc2030.brbots.com` e salve certificado/cadeia e chave fora da aplicação em `C:\ProgramData\SmartCRM\tls`.

Copie `deploy\manual-windows-pg11\httpd-sc2030.conf.example` para a pasta `conf\extra` real do Apache. Inclua o arquivo no `httpd.conf`, mas mantenha o virtual host antigo disponível para rollback. Antes de reiniciar:

```powershell
& "CAMINHO_REAL_DO_APACHE\bin\httpd.exe" -t
& "CAMINHO_REAL_DO_APACHE\bin\httpd.exe" -S
```

Só reinicie com `Syntax OK`, sem dois virtual hosts ativos para `sc2030.brbots.com` e depois de criar o arquivo de autenticação indicado no virtual host.

## 6. UAT de lançamento

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
curl.exe -I https://sc2030.brbots.com/
curl.exe --user crm-homologacao https://sc2030.brbots.com/health
```

O teste HTTPS autenticado deve retornar exatamente `{"status":"ok","database":"ok"}` sem usar `-k` ou `--insecure`. O CRM só está pronto para o cliente depois desse UAT, do teste da página e da confirmação de backup/rollback.

## Rollback antes da liberação

Se o proxy falhar, pare a tarefa `SmartCRM`, restaure apenas os arquivos do Apache salvos no backup, valide `httpd.exe -t` e reinicie o Apache. Não apague o database `smartcrm`; preserve-o para diagnóstico ou restauração controlada.
