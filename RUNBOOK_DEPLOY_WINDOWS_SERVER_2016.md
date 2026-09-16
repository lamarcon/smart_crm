# Runbook de deploy nativo do Smart CRM no Windows Server 2016

> Documento operacional para instalação, configuração, publicação, validação, operação e reversão.
>
> Escopo analisado: repositório `D:\Develop_CRM_Project`, commit `d0e1b94` observado em 09/09/2026.
>
> Ambiente-alvo informado: Windows Server 2016 Standard 1607 build 14393, Apache HTTP Server, CPython 3.11.5 e PostgreSQL 11.22 existente.

## 0. Regras de ouro

1. **O banco existente nunca deve ser apagado, recriado, limpo, sobrescrito ou restaurado por cima.**
2. Nenhum comando deste documento foi executado no servidor de produção. Todos os blocos são instruções para uma janela de mudança controlada.
3. Não executar `alembic downgrade` neste ambiente: o primeiro downgrade do projeto remove todas as tabelas do Smart CRM.
4. Não executar `DROP DATABASE`, `DROP SCHEMA`, `DROP TABLE`, `TRUNCATE`, `docker compose down -v`, `git reset --hard` ou `pg_restore --clean`.
5. Toda mudança de schema exige, nesta ordem: inventário, backup validado, restauração ensaiada fora de produção, revisão do SQL Alembic, aprovação e janela de manutenção.
6. Segredos não entram no Git, no ZIP da aplicação, em tickets, e-mail, chat, histórico de shell ou capturas de tela.
7. A aplicação deve escutar somente em `127.0.0.1:8080`; apenas o Apache recebe tráfego em 80/443.
8. Se qualquer variável ainda contiver `<...>` ou `PENDENTE_DE_CONFIRMACAO`, pare.
9. O repositório declara esta entrega como protótipo/homologação: não há autenticação nem autorização reais no backend. **Dados pessoais ou comerciais reais só podem ser liberados após correção desse risco ou aceite formal do responsável de segurança e do dono do negócio, com controle de perímetro compensatório.**

## 1. Informações pendentes

Preencher e aprovar esta tabela antes da mudança. As pendências não impedem a preparação do servidor, mas bloqueiam migração, publicação ou liberação de usuários conforme indicado.

| Informação | Valor | Bloqueia |
| --- | --- | --- |
| FQDN de produção, por exemplo `crm.exemplo.com.br` | **PENDENTE DE CONFIRMAÇÃO** | Apache/TLS |
| IP(s) do servidor e registro DNS A/AAAA | **PENDENTE DE CONFIRMAÇÃO** | Publicação |
| Caminho real do Apache e nome do serviço Windows | **PENDENTE DE CONFIRMAÇÃO** | Configuração/restart |
| Versão/build/OpenSSL do Apache instalado | **PENDENTE DE CONFIRMAÇÃO** | Compatibilidade TLS |
| Conta que executa o serviço Apache | **PENDENTE DE CONFIRMAÇÃO** | ACL da chave TLS |
| Host do PostgreSQL 11.22 | **PENDENTE DE CONFIRMAÇÃO** | Banco |
| Porta do PostgreSQL | **PENDENTE DE CONFIRMAÇÃO** (evidência histórica do repositório: `5432`) | Banco |
| Nome do serviço PostgreSQL | **PENDENTE DE CONFIRMAÇÃO** (evidência histórica: `postgresql-x64-11`) | Dependência do serviço |
| Nome do banco existente | **PENDENTE DE CONFIRMAÇÃO** | Banco |
| Owner do banco existente | **PENDENTE DE CONFIRMAÇÃO** | Banco |
| O banco é exclusivo do CRM ou compartilhado com outras aplicações? | **PENDENTE DE CONFIRMAÇÃO** | Migração |
| O banco já contém tabelas do Smart CRM? | **PENDENTE DE CONFIRMAÇÃO** | Migração |
| Revisão presente em `alembic_version`, se existir | **PENDENTE DE CONFIRMAÇÃO** | Migração |
| Role de migração/owner e role restrita de runtime | **PENDENTE DE CONFIRMAÇÃO** | Banco/serviço |
| Encoding, collation e ctype do banco | **PENDENTE DE CONFIRMAÇÃO** | Migração |
| Extensões instaladas e permitidas | **PENDENTE DE CONFIRMAÇÃO**; o código não exige extensão | Migração |
| Diretório de backup e retenção aprovados | **PENDENTE DE CONFIRMAÇÃO** | Deploy |
| RPO, RTO, janela de manutenção e aprovadores | **PENDENTE DE CONFIRMAÇÃO** | Deploy |
| Fonte/distribuição aprovada do Apache para Windows | **PENDENTE DE CONFIRMAÇÃO** | Instalação do Apache |
| SHA-256 aprovado do WinSW 2.12.0 e dos instaladores | **PENDENTE DE CONFIRMAÇÃO** | Instalação |
| Emissor, cadeia e processo de renovação do certificado | **PENDENTE DE CONFIRMAÇÃO** | HTTPS |
| Política de acesso: VPN, allowlist e/ou Basic Auth temporária | **PENDENTE DE CONFIRMAÇÃO** | Liberação |
| Aceite do risco de ausência de autenticação/autorização no backend | **PENDENTE DE CONFIRMAÇÃO** | Dados reais |
| Capacidade: CPU/RAM, volume e concorrência esperada | **PENDENTE DE CONFIRMAÇÃO** | Dimensionamento |

## 2. Resumo da arquitetura de produção identificada

Fluxo recomendado:

```text
Cliente HTTPS
    |
    v
Apache 2.4 :443 (TLS, autenticação/allowlist, logs, limite de 25 MB)
    |
    v
127.0.0.1:8080
WinSW -> PowerShell -> CPython 3.11.5 -> Uvicorn 0.35.0
    |
    v
FastAPI 0.116.1 / SQLAlchemy 2.0.43 / Psycopg 3.2.9
    |
    v
PostgreSQL 11.22 existente (host/porta/banco pendentes)
```

Fatos confirmados no código:

| Item | Resultado | Evidência |
| --- | --- | --- |
| Framework | FastAPI `0.116.1` | `pyproject.toml`, `app/main.py` |
| Interface | ASGI | objeto/factory FastAPI; comando Uvicorn |
| Servidor Windows | Uvicorn `0.35.0` | `requirements-runtime.txt`; scripts de deploy |
| Comando | `python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8080 --proxy-headers --forwarded-allow-ips 127.0.0.1` | `deploy/manual-windows-pg11/deployment-policy.ps1` |
| Health check | `GET /health`; 200 `{"status":"ok","database":"ok"}` ou 503 degradado | `app/main.py` |
| Frontend | SPA monolítica, já pronta, sem etapa de build | `app/static/index.html`; `package.json` só contém Playwright de teste |
| Publicação dos estáticos | FastAPI monta `app/static` em `/` | `app/main.py` |
| Uploads | Não há armazenamento binário; o formulário de PDF persiste somente o nome | `app/static/index.html`, `app/models.py` |
| Porta interna | `8080` nos scripts Windows | `server.env.example`, políticas de deploy |
| Banco | URL SQLAlchemy em `SMART_CRM_DATABASE_URL` | `app/database.py`, `migrations/env.py` |
| Migração | Alembic: base `be40ea4d21ad`, head `9f7a2c31d5e8` | `migrations/versions` |
| Extensões PostgreSQL | Nenhuma criada/requerida nas migrações | migrações |
| Tarefas em segundo plano | Nenhuma encontrada | código e dependências |
| Serviços externos | Nenhum encontrado; chamadas do browser são same-origin | `app/static/index.html` |

Não se usa Gunicorn no Windows. O Uvicorn usa ASGI nativamente e sua documentação confirma que o gerenciador multiprocesso usa `spawn`, compatível com Windows. Este runbook mantém **um worker**, igual ao contrato já validado pelo repositório. Aumentar workers fica pendente de teste de carga e memória.

O Apache fará proxy de `/` inteiro. Servir `app/static` diretamente pelo Apache criaria duas fontes de publicação e risco de frontend/API fora de sincronia; portanto, não é adotado.

## 3. Matriz de compatibilidade e suporte em 09/09/2026

| Componente | Versão | Compatibilidade técnica | Suporte/risco | Decisão |
| --- | --- | --- | --- | --- |
| Windows Server | 2016 Standard 1607/14393 | Compatível com Python/Apache/WinSW em x64, sujeito ao patch level | Suporte estendido termina em **12/01/2027**; janela residual muito curta | Manter por exigência, totalmente atualizado; planejar migração do SO imediatamente |
| CPython | 3.11.5 x64 | Projeto exige `>=3.11,<3.13`; wheels `cp311-win_amd64` existem no bundle | Série 3.11 está em fase de correções de segurança até 10/2027, mas **3.11.5 foi substituído por patches 3.11 mais novos** | Usar 3.11.5 por exigência; registrar aceite e plano para patch 3.11.x após testes |
| PostgreSQL | 11.22 | Psycopg 3 suporta PG 10+ em best effort quando EOL; schema usa recursos comuns do PG11, inclusive JSONB | **EOL desde 09/11/2023**, sem correções de segurança/bugs | Não alterar nesta mudança; isolar, restringir e abrir plano prioritário de upgrade |
| Apache HTTP Server | 2.4.x; versão real pendente | Reverse proxy via `mod_proxy`/`mod_proxy_http`; TLS via `mod_ssl` | ASF recomenda a GA atual **2.4.68**; ASF não fornece binário oficial Windows | Reaproveitar instalação existente se suportada e corrigida; distribuição/build deve ser aprovada |
| WinSW | 2.12.0 NET4 | Roda com .NET Framework 4.6.1+; Windows Server 2016 já inclui versão compatível | 2.12.0 é a release 2.x estável; 3.x aparece como pré-release | Fixar 2.12.0, validar hash do artefato aprovado, monitorar CVEs/releases |
| FastAPI | 0.116.1 | Requer Python >=3.8; projeto usa 3.11 | Pin antigo; há release mais nova | Não atualizar durante deploy; abrir ciclo de dependências separado |
| Uvicorn | 0.35.0 | Requer Python >=3.9; execução Windows suportada; `uvloop` não é Windows e não está instalado | Pin antigo; há release mais nova | Usar implementação padrão e manter pin |
| SQLAlchemy | 2.0.43 | Requer Python >=3.7; wheel CPython 3.11 Windows x64 no bundle | Pin antigo; há release 2.0.x mais nova | Manter pin e testar atualização separadamente |
| Alembic | 1.16.5 | Requer Python >=3.9; DDL transacional em PostgreSQL | Pin antigo; há release mais nova | Manter pin; revisar toda migração antes de aplicar |
| Psycopg binary | 3.2.9 | Wheel CPython 3.11 Windows x64; inclui bibliotecas cliente; PG11 em best effort | Pin antigo; PG11 fora do conjunto ativamente testado | Gate de conexão, migração e UAT obrigatório |

Dependências transitivas observadas na wheelhouse do artefato existente: `annotated-types 0.8.0`, `anyio 4.15.0`, `click 8.5.0`, `greenlet 3.5.5`, `h11 0.16.0`, `idna 3.19`, `Mako 1.4.1`, `MarkupSafe 3.0.3`, `pydantic 2.13.5`, `pydantic-core 2.46.5`, `starlette 0.47.3`, `typing-extensions 4.16.0`, `typing-inspection 0.4.4` e `tzdata 2026.3`. O manifesto SHA-256 do bundle é o lock efetivo desses artefatos.

Fontes primárias:

- Windows Server 2016: <https://learn.microsoft.com/en-us/lifecycle/products/windows-server-2016>
- Estado das versões Python: <https://devguide.python.org/versions/>
- Release Python 3.11.5: <https://www.python.org/downloads/release/python-3115/>
- Política de versões PostgreSQL: <https://www.postgresql.org/support/versioning/>
- EOL do PostgreSQL 11.22: <https://www.postgresql.org/about/news/postgresql-161-155-1410-1313-1217-and-1122-released-2749/>
- Apache atual e verificação: <https://httpd.apache.org/download.cgi>
- Apache no Windows: <https://httpd.apache.org/docs/2.4/platform/windows.html>
- Uvicorn em produção: <https://www.uvicorn.org/deployment/>
- Psycopg: <https://www.psycopg.org/psycopg3/docs/basic/install.html>
- WinSW: <https://github.com/winsw/winsw>
- Visual C++ Runtime: <https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist>

## 4. Pré-requisitos

### 4.1 Pessoas, acessos e janela

- Administrador local para instalar Python, Apache/WinSW, serviço e firewall.
- DBA com permissão de leitura/inventário, backup e DDL somente durante a migração aprovada.
- Acesso ao cofre de segredos, DNS e emissor ACME/certificado.
- Janela com congelamento de escrita, plano de comunicação e aprovador de go/no-go.
- Máquina de build confiável com Git e internet, caso o servidor seja offline.
- Destino externo para ao menos duas cópias do backup; nunca somente no mesmo disco do PostgreSQL.

### 4.2 Sistema e recursos

Recomendação inicial de reserva, a confirmar por capacidade: 4 GB livres de RAM, 2 vCPU e pelo menos `2 x tamanho_do_banco + 5 GB` livres para backup, pacote, logs e restauração temporária. Estes valores não vêm do código e exigem validação operacional.

**PowerShell — inventário somente leitura:**

```powershell
Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber, OsArchitecture
Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 20
$PSVersionTable
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" |
    Select-Object DeviceID,Size,FreeSpace
Get-NetTCPConnection -State Listen |
    Where-Object LocalPort -In 80,443,5432,8080 |
    Select-Object LocalAddress,LocalPort,OwningProcess
```

Aplicar todas as atualizações cumulativas e de segurança aprovadas para Windows Server 2016 antes da janela, com reboot e nova validação. Não misturar atualização do SO com o corte do CRM se a política de mudança exigir janelas separadas.

### 4.3 Visual C++, PowerShell e .NET

Instalar o **Microsoft Visual C++ v14 Redistributable x64 mais recente compatível com Server 2016**, somente pelo link Microsoft. Verificar assinatura antes de executar.

**PowerShell — verificação do instalador baixado:**

```powershell
$installer = 'C:\Transfer\vc_redist.x64.exe'
Get-FileHash -LiteralPath $installer -Algorithm SHA256
Get-AuthenticodeSignature -LiteralPath $installer | Format-List Status,SignerCertificate
if ((Get-AuthenticodeSignature -LiteralPath $installer).Status -ne 'Valid') {
    throw 'Assinatura Authenticode inválida. Não instalar.'
}
```

**CMD — instalação silenciosa somente após aprovação do hash/assinatura:**

```cmd
C:\Transfer\vc_redist.x64.exe /install /quiet /norestart
```

Confirmar .NET Framework para o WinSW:

**PowerShell:**

```powershell
Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' |
    Select-Object Release,Version
```

WinSW NET4 requer .NET Framework 4.6.1 ou superior. Se ausente, usar apenas instalador Microsoft aprovado, validar assinatura e reiniciar antes de continuar.

### 4.4 Portas, DNS e certificados

- Entrada pública: TCP 80 apenas para redirecionamento/ACME; TCP 443 para HTTPS.
- `127.0.0.1:8080`: backend; nenhuma regra inbound pública.
- PostgreSQL: manter conforme arquitetura existente. Se local, preferir loopback. Se remoto, liberar 5432 apenas entre IPs necessários e exigir TLS conforme política do DBA.
- DNS A/AAAA deve apontar para o host correto antes da emissão/validação TLS.
- Certificado deve conter o FQDN em SAN, cadeia completa, chave correspondente e validade monitorada.

### 4.5 Pacotes e instalação offline

O caminho mais reproduzível já existente é o builder `scripts/build_manual_windows_pg11_bundle.py`, que cria ZIP, wheelhouse Windows CPython 3.11 x64, manifesto interno e SHA-256 externo. O bundle existente `357113f7` é anterior ao commit analisado `d0e1b94`; **não presumir que ele representa a versão que será implantada**.

Na máquina de build confiável:

**PowerShell:**

```powershell
$repo = 'D:\Develop_CRM_Project'
Set-Location -LiteralPath $repo
& 'C:\Program Files\Git\cmd\git.exe' status --short
& 'C:\Program Files\Git\cmd\git.exe' rev-parse HEAD
& 'C:\caminho\python311\python.exe' scripts\build_manual_windows_pg11_bundle.py
Get-ChildItem -LiteralPath (Join-Path $repo 'dist') -Filter 'smart-crm-manual-pg11-*.zip' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1 |
    Get-FileHash -Algorithm SHA256
```

Pare se `git status --short` mostrar mudanças não aprovadas. Arquive o SHA Git, ZIP, `.sha256`, SBOM/lista de wheels e aprovações. O servidor offline recebe somente artefatos aprovados.

## 5. Instalação nativa passo a passo

### 5.1 Variáveis da sessão do administrador

Substituir todos os placeholders. Este bloco é **PowerShell**:

```powershell
$AppRoot = 'C:\brbots\apps\smart-crm'
$ProgramDataRoot = 'C:\ProgramData\SmartCRM'
$BackupRoot = 'D:\Backups\SmartCRM'
$PythonInstaller = 'C:\Transfer\python-3.11.5-amd64.exe'
$Bundle = 'C:\Transfer\smart-crm-manual-pg11-<COMMIT>.zip'
$BundleHashFile = "$Bundle.sha256"
$ApacheRoot = '<CAMINHO_REAL_APACHE>'
$ApacheService = '<NOME_SERVICO_APACHE>'
$ApacheServiceAccount = '<CONTA_SERVICO_APACHE>'
$DbHost = '<DB_HOST>'
$DbPortText = '<DB_PORT>'
$DbName = '<DB_NAME>'
$DbOwner = '<DB_OWNER>'
$DbMigrationUser = '<DB_MIGRATOR_ROLE>'
$DbRuntimeUser = '<DB_RUNTIME_ROLE>'
$PostgresService = '<NOME_SERVICO_POSTGRESQL>'
$Domain = '<DOMINIO_FQDN>'

$allValues = @(
    $ApacheRoot,$ApacheService,$ApacheServiceAccount,$DbHost,$DbName,$DbOwner,
    $DbMigrationUser,$DbRuntimeUser,$PostgresService,$Domain,$Bundle,$DbPortText
)
if ($allValues | Where-Object { $_ -match '<|PENDENTE' }) {
    throw 'Há placeholders pendentes. Pare antes de alterar o servidor.'
}
[int]$DbPort = $DbPortText
```

### 5.2 Descobrir o Apache/PostgreSQL existente

**PowerShell — somente leitura:**

```powershell
Get-CimInstance Win32_Service |
    Where-Object Name -Match 'Apache|httpd|postgresql' |
    Select-Object Name,State,StartName,PathName,StartMode
Get-Process -Id (Get-NetTCPConnection -State Listen -LocalPort 80,443 -ErrorAction SilentlyContinue).OwningProcess |
    Select-Object Id,Path
& (Join-Path $ApacheRoot 'bin\httpd.exe') -v
& (Join-Path $ApacheRoot 'bin\httpd.exe') -V
& (Join-Path $ApacheRoot 'bin\httpd.exe') -M
& (Join-Path $ApacheRoot 'bin\openssl.exe') version -a
Get-Service -Name $PostgresService
```

Registrar a saída no ticket de mudança. Não parar nem reiniciar o PostgreSQL para este deploy.

### 5.3 Instalar ou validar o Apache

Se o Apache existente estiver atualizado, íntegro e sob manutenção, reutilizá-lo. A ASF publica fonte e assinaturas, mas não binário oficial Windows. Para uma instalação nova, a distribuição Windows e seu toolchain/OpenSSL devem ser aprovados pela organização. Em 09/09/2026, a GA ASF é 2.4.68; não trocar automaticamente a versão existente sem análise de compatibilidade.

**PowerShell — verificar artefato aprovado:**

```powershell
$apacheZip = 'C:\Transfer\httpd-2.4.68-win64-<DISTRIBUIDOR_APROVADO>.zip'
$expectedApacheSha256 = '<SHA256_APROVADO>'
$actualApacheSha256 = (Get-FileHash -LiteralPath $apacheZip -Algorithm SHA256).Hash
if ($actualApacheSha256 -ne $expectedApacheSha256) {
    throw 'Hash do Apache divergente. Não extrair.'
}
```

Extrair para o caminho aprovado e revisar `ServerRoot`, `Listen`, `ServerName`, módulos e conta do serviço. Não sobrescrever uma instalação existente. Em instalação nova, o comando de registro deve ser executado em **CMD elevado**:

```cmd
"C:\Apache24\bin\httpd.exe" -k install -n "Apache2.4"
"C:\Apache24\bin\httpd.exe" -t
sc.exe query "Apache2.4"
```

Se o Apache já existe, não execute `-k install`.

### 5.4 Instalar exatamente CPython 3.11.5 x64

Baixar somente da release oficial Python 3.11.5. Validar a assinatura Authenticode e comparar o hash com o valor aprovado na estação de transferência.

**PowerShell:**

```powershell
$expectedPythonSha256 = '<SHA256_APROVADO_PYTHON_3_11_5_AMD64>'
$actualPythonSha256 = (Get-FileHash -LiteralPath $PythonInstaller -Algorithm SHA256).Hash
$pythonSignature = Get-AuthenticodeSignature -LiteralPath $PythonInstaller
if ($actualPythonSha256 -ne $expectedPythonSha256 -or $pythonSignature.Status -ne 'Valid') {
    throw 'Python 3.11.5 não passou em hash/assinatura.'
}
```

**CMD elevado — instalação all-users em caminho fixo:**

```cmd
C:\Transfer\python-3.11.5-amd64.exe /quiet InstallAllUsers=1 TargetDir=C:\brbots\python Include_launcher=0 PrependPath=0 Include_test=0 Include_pip=1 Include_tcltk=0
```

**PowerShell — gate obrigatório:**

```powershell
$Python311 = 'C:\brbots\python\python.exe'
& $Python311 --version
& $Python311 -c "import json,platform,struct,sys; print(json.dumps({'implementation':platform.python_implementation(),'version':sys.version,'bits':struct.calcsize('P')*8})); assert platform.python_implementation() == 'CPython'; assert sys.version_info[:3] == (3,11,5); assert struct.calcsize('P')*8 == 64"
if ($LASTEXITCODE -ne 0) { throw 'Runtime diferente de CPython 3.11.5 x64.' }
```

### 5.5 Instalar a aplicação e virtualenv

Validar ZIP antes de extrair. A extração só pode ocorrer em diretório novo; uma atualização usa diretório versionado, descrito adiante.

**PowerShell:**

```powershell
$expectedLine = (Get-Content -LiteralPath $BundleHashFile -Raw).Trim()
$expectedBundleSha256 = ($expectedLine -split '\s+')[0]
$actualBundleSha256 = (Get-FileHash -LiteralPath $Bundle -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualBundleSha256 -ne $expectedBundleSha256.ToLowerInvariant()) {
    throw 'Hash do bundle inválido.'
}
if (Test-Path -LiteralPath $AppRoot) {
    throw 'AppRoot já existe. Não sobrescrever; usar o procedimento de atualização versionada.'
}
New-Item -ItemType Directory -Path $AppRoot -Force | Out-Null
Expand-Archive -LiteralPath $Bundle -DestinationPath $AppRoot
Set-Location -LiteralPath $AppRoot
& '.\deploy\manual-windows-pg11\test-package-integrity.ps1' -AppRoot $AppRoot
& $Python311 -m venv (Join-Path $AppRoot '.venv')
$VenvPython = Join-Path $AppRoot '.venv\Scripts\python.exe'
& $VenvPython -m pip install --disable-pip-version-check --no-index `
    --find-links (Join-Path $AppRoot 'wheelhouse') `
    -r (Join-Path $AppRoot 'requirements-runtime.txt')
if ($LASTEXITCODE -ne 0) { throw 'Instalação das dependências falhou.' }
& $VenvPython -m pip check
& $VenvPython -m compileall -q (Join-Path $AppRoot 'app')
& $VenvPython -c "import fastapi,psycopg,sqlalchemy,uvicorn; print(fastapi.__version__, psycopg.__version__, sqlalchemy.__version__, uvicorn.__version__)"
```

Não executar `pnpm install` nem build Node no servidor. O `package.json` serve aos testes Playwright; o frontend implantável é `app\static\index.html`.

### 5.6 Estrutura e ACLs NTFS

Conta escolhida: `NT AUTHORITY\LocalService` (SID `S-1-5-19`) para privilégio mínimo. Ela precisa de leitura/execução na aplicação, leitura do ambiente e modificação somente nos logs. O Apache recebe leitura da chave TLS. Administradores e SYSTEM mantêm controle total.

**PowerShell elevado:**

```powershell
$ServiceRoot = Join-Path $ProgramDataRoot 'service'
$LogRoot = Join-Path $ProgramDataRoot 'logs'
$TlsRoot = Join-Path $ProgramDataRoot 'tls'
$ApacheConfigRoot = Join-Path $ProgramDataRoot 'apache'
$AcmeRoot = Join-Path $ProgramDataRoot 'acme-challenge'
New-Item -ItemType Directory -Path $ServiceRoot,$LogRoot,$TlsRoot,$ApacheConfigRoot,$AcmeRoot -Force | Out-Null

icacls $AppRoot /inheritance:r /grant:r `
    '*S-1-5-18:(OI)(CI)F' `
    '*S-1-5-32-544:(OI)(CI)F' `
    '*S-1-5-19:(OI)(CI)RX'
icacls $ProgramDataRoot /inheritance:r /grant:r `
    '*S-1-5-18:(OI)(CI)F' `
    '*S-1-5-32-544:(OI)(CI)F'
icacls $LogRoot /grant:r '*S-1-5-19:(OI)(CI)M'
icacls $ServiceRoot /grant:r '*S-1-5-19:(OI)(CI)RX'
icacls $AcmeRoot /grant:r "$ApacheServiceAccount`:(OI)(CI)M"
```

Revisar o resultado de cada `icacls`. Não conceder `Everyone`, `Users` ou escrita do serviço no código.

## 6. Configuração segura

### 6.1 Variáveis

A aplicação lê diretamente apenas:

| Variável | Obrigatória em produção | Uso |
| --- | --- | --- |
| `SMART_CRM_DATABASE_URL` | Sim | URL `postgresql+psycopg://...`; criada em memória pelo script wrapper |
| `SMART_CRM_TEST_MODE` | Sim no wrapper | Deve ser `0`; evita qualquer semântica de teste |

O wrapper operacional usa:

| Variável | Exemplo sem segredo | Observação |
| --- | --- | --- |
| `SMART_CRM_DB_NAME` | `<DB_NAME>` | Nome existente; não criar/recriar |
| `SMART_CRM_DB_USER` | `<DB_RUNTIME_ROLE>` | Role restrita, não owner |
| `SMART_CRM_DB_PASSWORD` | `<SEGREDO_DO_COFRE>` | Nunca registrar ou exibir |
| `SMART_CRM_DB_HOST` | `<DB_HOST>` | `127.0.0.1` se local |
| `SMART_CRM_DB_PORT` | `<DB_PORT>` | Confirmar no servidor |
| `SMART_CRM_BIND_IP` | `127.0.0.1` | Valor fixo de segurança |
| `SMART_CRM_PORT` | `8080` | Valor do contrato existente |

Criar `C:\ProgramData\SmartCRM\server.env` em editor elevado, em UTF-8 sem BOM, com os placeholders substituídos. Não reutilizar automaticamente `deploy\manual-windows-pg11\server.env.example`, pois ele fixa banco/role `smartcrm` e porta 5432 sem evidência do banco atual.

```dotenv
SMART_CRM_DB_NAME=<DB_NAME>
SMART_CRM_DB_USER=<DB_RUNTIME_ROLE>
SMART_CRM_DB_PASSWORD=<SEGREDO_DO_COFRE>
SMART_CRM_DB_HOST=<DB_HOST>
SMART_CRM_DB_PORT=<DB_PORT>
SMART_CRM_BIND_IP=127.0.0.1
SMART_CRM_PORT=8080
```

**PowerShell — restringir e auditar sem imprimir conteúdo:**

```powershell
$EnvFile = Join-Path $ProgramDataRoot 'server.env'
icacls $EnvFile /inheritance:r /grant:r `
    '*S-1-5-18:F' `
    '*S-1-5-32-544:F' `
    '*S-1-5-19:R'
Get-Acl -LiteralPath $EnvFile | Format-List Owner,AccessToString
& 'C:\Program Files\Git\cmd\git.exe' -C $AppRoot status --short
```

O arquivo não pode aparecer em `git status` e fica fora de `$AppRoot`.

### 6.2 Script wrapper externo

Criar `C:\ProgramData\SmartCRM\service\start-smart-crm-production.ps1` com o conteúdo abaixo. Ele codifica usuário, senha e banco para URL sem imprimi-los.

```powershell
[CmdletBinding()]
param(
    [string]$AppRoot = 'C:\brbots\apps\smart-crm',
    [string]$EnvFile = 'C:\ProgramData\SmartCRM\server.env'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$allowedKeys = @(
    'SMART_CRM_DB_NAME','SMART_CRM_DB_USER','SMART_CRM_DB_PASSWORD',
    'SMART_CRM_DB_HOST','SMART_CRM_DB_PORT','SMART_CRM_BIND_IP','SMART_CRM_PORT'
)
$settings = @{}
foreach ($rawLine in Get-Content -LiteralPath $EnvFile) {
    $line = $rawLine.Trim()
    if (-not $line -or $line.StartsWith('#')) { continue }
    if ($line -notmatch '^(?<Key>[A-Z0-9_]+)=(?<Value>.*)$') { throw 'Linha de ambiente inválida.' }
    $key = $Matches.Key
    if ($key -notin $allowedKeys -or $settings.ContainsKey($key)) { throw 'Chave inválida ou duplicada.' }
    $settings[$key] = $Matches.Value
}
foreach ($key in $allowedKeys) {
    if (-not $settings.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($settings[$key])) {
        throw "Variável obrigatória ausente: $key"
    }
}
if ($settings.SMART_CRM_BIND_IP -ne '127.0.0.1') { throw 'Binding público proibido.' }
if ($settings.SMART_CRM_PORT -ne '8080') { throw 'Porta interna deve ser 8080.' }
if ($settings.SMART_CRM_DB_PORT -notmatch '^\d{1,5}$' -or [int]$settings.SMART_CRM_DB_PORT -gt 65535) {
    throw 'Porta PostgreSQL inválida.'
}

$python = Join-Path $AppRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Python da virtualenv ausente.' }
$encodedUser = [Uri]::EscapeDataString($settings.SMART_CRM_DB_USER)
$encodedPassword = [Uri]::EscapeDataString($settings.SMART_CRM_DB_PASSWORD)
$encodedDatabase = [Uri]::EscapeDataString($settings.SMART_CRM_DB_NAME)
$env:SMART_CRM_DATABASE_URL = 'postgresql+psycopg://{0}:{1}@{2}:{3}/{4}?connect_timeout=5' -f `
    $encodedUser,$encodedPassword,$settings.SMART_CRM_DB_HOST,$settings.SMART_CRM_DB_PORT,$encodedDatabase
$env:SMART_CRM_TEST_MODE = '0'

Push-Location -LiteralPath $AppRoot
try {
    & $python -m uvicorn app.main:create_app --factory `
        --host 127.0.0.1 --port 8080 `
        --proxy-headers --forwarded-allow-ips 127.0.0.1 `
        --no-use-colors --log-level info
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:SMART_CRM_DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:SMART_CRM_TEST_MODE -ErrorAction SilentlyContinue
    Pop-Location
}
```

Validar sintaxe sem executar a aplicação:

```powershell
$Wrapper = Join-Path $ServiceRoot 'start-smart-crm-production.ps1'
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($Wrapper,[ref]$tokens,[ref]$errors) | Out-Null
if ($errors.Count -gt 0) { $errors; throw 'Wrapper PowerShell inválido.' }
```

## 7. PostgreSQL 11.22 existente

### 7.1 Inventário bloqueante e colisões

Usar os binários **PostgreSQL 11.22** para backup/restore do servidor 11. O caminho real é pendente. Não usar cliente mais antigo que o servidor.

**PowerShell — senha solicitada sem aparecer no comando:**

```powershell
$PgBin = '<CAMINHO_POSTGRESQL_11_22_BIN>'
$Psql = Join-Path $PgBin 'psql.exe'
$PgDump = Join-Path $PgBin 'pg_dump.exe'
$PgRestore = Join-Path $PgBin 'pg_restore.exe'
$dbCredential = Get-Credential -UserName $DbMigrationUser -Message 'Credencial de inventário/migração'
$env:PGPASSWORD = $dbCredential.GetNetworkCredential().Password
try {
    & $Psql -X -v ON_ERROR_STOP=1 -h $DbHost -p $DbPort -U $DbMigrationUser -d $DbName `
        -c "SELECT version(), current_database(), current_user, pg_encoding_to_char(encoding), datcollate, datctype FROM pg_database WHERE datname=current_database();"
    & $Psql -X -v ON_ERROR_STOP=1 -h $DbHost -p $DbPort -U $DbMigrationUser -d $DbName `
        -c "SELECT extname, extversion FROM pg_extension ORDER BY 1;"
    & $Psql -X -v ON_ERROR_STOP=1 -h $DbHost -p $DbPort -U $DbMigrationUser -d $DbName `
        -c "SELECT schemaname, tablename, tableowner FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2;"
    & $Psql -X -v ON_ERROR_STOP=1 -h $DbHost -p $DbPort -U $DbMigrationUser -d $DbName `
        -c "SELECT to_regclass('public.alembic_version') AS alembic_table;"
    & $Psql -X -v ON_ERROR_STOP=1 -h $DbHost -p $DbPort -U $DbMigrationUser -d $DbName `
        -c "SELECT version_num FROM public.alembic_version;"
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    $dbCredential = $null
}
```

A última consulta pode falhar se não houver `alembic_version`; registre o resultado, não crie nem carimbe a tabela manualmente.

As migrações criam, sem schema explícito, estes objetos no schema resolvido pelo `search_path`: `workspaces`, `custom_field_definitions`, `external_source_fields`, `module_field_settings`, `record_visible_custom_fields`, `teams`, `crm_users`, `custom_field_values`, `companies`, `leads`, `notifications`, `saved_filters`, `user_dashboard_preferences`, `user_module_preferences`, `contacts`, `lead_assistants`, `deals`, `deal_assistants`, `deal_stage_history`, `quotes` e `alembic_version`.

**Pare e abra decisão de arquitetura se:**

- o banco for compartilhado;
- qualquer nome acima já existir sem ter sido criado por estas migrações;
- houver tabelas CRM sem `alembic_version` coerente;
- houver mais de um sistema controlando `alembic_version` no mesmo schema;
- a revisão não for ancestral de `9f7a2c31d5e8`;
- encoding não for UTF8;
- o `search_path` não estiver documentado.

O código não qualifica schema. Isolar em schema dedicado por `search_path` pode ser tecnicamente possível, mas **não está configurado nem validado pelo repositório**; portanto é PENDENTE DE CONFIRMAÇÃO e exige teste/revisão antes do uso. Nunca execute `alembic stamp` para “resolver” divergência sem comparar integralmente o schema e obter aprovação do DBA.

### 7.2 Backup obrigatório

Fazer backup lógico custom format e globals. O comando é não destrutivo.

**PowerShell:**

```powershell
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$BackupDir = Join-Path $BackupRoot $Stamp
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
$DumpFile = Join-Path $BackupDir "$DbName-$Stamp.dump"
$GlobalsFile = Join-Path $BackupDir "globals-$Stamp.sql"
$dbCredential = Get-Credential -UserName $DbMigrationUser -Message 'Credencial de backup'
$env:PGPASSWORD = $dbCredential.GetNetworkCredential().Password
try {
    & $PgDump -h $DbHost -p $DbPort -U $DbMigrationUser -d $DbName `
        --format=custom --blobs --verbose --file=$DumpFile
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump falhou.' }
    & (Join-Path $PgBin 'pg_dumpall.exe') -h $DbHost -p $DbPort -U $DbMigrationUser `
        --globals-only --file=$GlobalsFile
    if ($LASTEXITCODE -ne 0) { throw 'Backup de globals falhou.' }
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    $dbCredential = $null
}
if ((Get-Item -LiteralPath $DumpFile).Length -le 0) { throw 'Dump vazio.' }
& $PgRestore --list $DumpFile | Select-Object -First 30
if ($LASTEXITCODE -ne 0) { throw 'Catálogo do dump inválido.' }
Get-FileHash -LiteralPath $DumpFile,$GlobalsFile -Algorithm SHA256 |
    Format-Table Path,Hash
```

Copiar dump, globals, hashes, inventário, revisão Alembic e SHA da aplicação para armazenamento externo imutável. Um `pg_restore --list` comprova legibilidade do catálogo, não restauração completa.

### 7.3 Ensaio obrigatório de restauração

Restaurar em host/banco **separado e descartável**, nunca sobre o original. O nome `<DB_RESTORE_TEST>` deve ser novo. A criação desse banco de ensaio requer aprovação do DBA e espaço suficiente.

```powershell
$RestoreDb = '<DB_RESTORE_TEST_NOVO>'
if ($RestoreDb -match '<|PENDENTE') { throw 'Nome do banco de ensaio pendente.' }
$restoreCredential = Get-Credential -UserName $DbOwner -Message 'Credencial para banco de ensaio'
$env:PGPASSWORD = $restoreCredential.GetNetworkCredential().Password
try {
    & (Join-Path $PgBin 'createdb.exe') -h $DbHost -p $DbPort -U $DbOwner `
        --owner=$DbOwner --encoding=UTF8 $RestoreDb
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o banco de ensaio novo.' }
    & $PgRestore -h $DbHost -p $DbPort -U $DbOwner -d $RestoreDb `
        --exit-on-error --verbose --no-owner $DumpFile
    if ($LASTEXITCODE -ne 0) { throw 'Restauração de ensaio falhou.' }
    & $Psql -X -v ON_ERROR_STOP=1 -h $DbHost -p $DbPort -U $DbOwner -d $RestoreDb `
        -c 'SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN (''pg_catalog'',''information_schema'');'
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    $restoreCredential = $null
}
```

**Aviso:** a remoção posterior do banco de ensaio é destrutiva. Este runbook não fornece `DROP DATABASE`; o DBA deve removê-lo em mudança separada somente depois de preservar as evidências necessárias.

### 7.4 Roles e privilégios mínimos

Preferir duas credenciais:

- `<DB_MIGRATOR_ROLE>`: owner/DDL, usada apenas na janela;
- `<DB_RUNTIME_ROLE>`: `CONNECT`, `USAGE` no schema e CRUD/sequence somente nos objetos CRM.

O SQL abaixo é modelo para o DBA após confirmar banco/schema e ownership; não executá-lo cegamente. Ele não altera senha e não cria/recria role.

```sql
GRANT CONNECT ON DATABASE <DB_NAME> TO <DB_RUNTIME_ROLE>;
GRANT USAGE ON SCHEMA public TO <DB_RUNTIME_ROLE>;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO <DB_RUNTIME_ROLE>;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO <DB_RUNTIME_ROLE>;
ALTER DEFAULT PRIVILEGES FOR ROLE <DB_MIGRATOR_ROLE> IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO <DB_RUNTIME_ROLE>;
ALTER DEFAULT PRIVILEGES FOR ROLE <DB_MIGRATOR_ROLE> IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO <DB_RUNTIME_ROLE>;
```

Em banco compartilhado, `ALL TABLES` é amplo demais e está proibido: o DBA deve gerar grants somente para a lista CRM. A aplicação não precisa de `CREATEDB`, `CREATEROLE`, superuser, ownership nem DDL em runtime.

### 7.5 Revisar e aplicar migrações com segurança

Primeiro gerar SQL para revisão usando credencial de migração. Não usar a credencial de runtime.

**PowerShell:**

```powershell
function New-DbUrl([string]$User,[string]$Password,[string]$HostName,[int]$Port,[string]$Database) {
    return 'postgresql+psycopg://{0}:{1}@{2}:{3}/{4}?connect_timeout=5' -f `
        [Uri]::EscapeDataString($User),[Uri]::EscapeDataString($Password),$HostName,$Port,[Uri]::EscapeDataString($Database)
}
$migrationCredential = Get-Credential -UserName $DbMigrationUser -Message 'Credencial temporária Alembic'
$env:SMART_CRM_DATABASE_URL = New-DbUrl $DbMigrationUser $migrationCredential.GetNetworkCredential().Password $DbHost $DbPort $DbName
try {
    Set-Location -LiteralPath $AppRoot
    & $VenvPython -m alembic heads
    & $VenvPython -m alembic history --verbose
    & $VenvPython -m alembic current --verbose
    & $VenvPython -m alembic upgrade head --sql |
        Out-File -LiteralPath (Join-Path $BackupDir 'alembic-upgrade-head.sql') -Encoding utf8
}
finally {
    Remove-Item Env:SMART_CRM_DATABASE_URL -ErrorAction SilentlyContinue
    $migrationCredential = $null
}
```

O DBA deve revisar o SQL. A base `be40ea4d21ad` cria vinte tabelas e insere `workspaces(id='default', version=0)`. O head `9f7a2c31d5e8` substitui a constraint de status de `crm_users`. Não há extensão. O downgrade da base derruba todas as tabelas; por isso não é estratégia de rollback.

Somente depois de backup, ensaio, ausência de colisões e aprovação:

```powershell
Stop-Service -Name 'SmartCRM' -ErrorAction SilentlyContinue
$migrationCredential = Get-Credential -UserName $DbMigrationUser -Message 'Credencial temporária Alembic'
$env:SMART_CRM_DATABASE_URL = New-DbUrl $DbMigrationUser $migrationCredential.GetNetworkCredential().Password $DbHost $DbPort $DbName
try {
    Set-Location -LiteralPath $AppRoot
    & $VenvPython -m alembic current --verbose
    & $VenvPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Migração falhou. Não iniciar aplicação/Apache.' }
    & $VenvPython -m alembic current --verbose
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível confirmar a revisão.' }
}
finally {
    Remove-Item Env:SMART_CRM_DATABASE_URL -ErrorAction SilentlyContinue
    $migrationCredential = $null
}
```

Se a migração falhar, preservar log, manter serviço parado e consultar o DBA. Não repetir sem entender a transação/estado e não carimbar revisão manualmente.

Alterações futuras destrutivas devem usar padrão expand/contract: adicionar objetos compatíveis, popular/validar em lotes, mudar a aplicação, observar e só remover objetos antigos em release posterior com backup próprio.

## 7.6 Cutover multiempresa: plano de controle e frota de bancos

> Gate normativo para a release multiempresa. Esta seção substitui o fluxo de banco único
> das seções 7, 11, 12 e 14 quando houver conflito. Os exemplos legados com `$DbName`
> não autorizam uma operação sobre a frota. Nenhuma instrução desta seção foi executada
> em servidor ou banco de produção.

### 7.6.1 Congelar o conjunto de mudança e a autorização

Antes de consultar ou migrar qualquer banco, criar um manifesto de mudança imutável e
assinado pelo operador e pelo DBA. Cada linha representa exatamente um banco e contém:

| Campo | Contrato |
| --- | --- |
| `database_kind` | `control_database`, `tenant_default` ou `tenant_remote` |
| `tenant_id` / `slug` | Vazios somente para `control_database`; explícitos para cada tenant |
| `database_fingerprint` | Hash aprovado da identidade host/porta/nome, nunca a DSN |
| `secret_ref` | secret_ref opaco existente no plano de controle; nunca o segredo |
| `expected_revision` | `c01a5d8e4f20` para controle ou `a4c9d2e7f1b6` para tenant |
| `change_ticket` / `authorized_by` | Mudança, operador e DBA que autorizaram aquele banco |
| `backup_sha256` | Hash da evidência de backup daquele banco |
| `restore_rehearsal` | Deve ser exatamente `restore_rehearsal=passed` |
| `uat_result` | Pendente até a validação isolada do banco/tenant |

O conjunto deve conter um `control_database`, o banco `tenant_default` que já possui os
dados atuais e somente os bancos `tenant_remote` nominalmente escolhidos.
Nenhum banco pode entrar no conjunto por descoberta automática. Não usar “todos os ativos” como
atalho. Autorização ausente para qualquer linha bloqueia toda migração.

Gerar e assinar o manifesto fora do repositório.
Nunca registrar DSN, usuário, senha ou conteúdo DPAPI. Saídas compartilháveis de preflight e migração ficam limitadas a
tenant_id, slug, status, revision, identity e code. Host, porta, nome do banco e caminhos
privados permanecem apenas na evidência operacional restrita; logs públicos usam o
`database_fingerprint`.

### 7.6.2 Gate global de backup e restauração ensaiada

Cada banco selecionado, inclusive o banco de controle, exige sua própria evidência antes
da primeira alteração. Para cada linha do manifesto:

1. congelar escritores daquele banco e registrar início/fim do congelamento;
2. executar backup lógico em formato custom com os binários PostgreSQL aprovados;
3. exigir saída zero, arquivo não vazio, `backup_sha256` e catálogo legível por
   `pg_restore --list`;
4. copiar a evidência para armazenamento externo imutável;
5. restaurar em banco novo e isolado, nunca sobre o original;
6. verificar revisão, contagens, constraints e identidade, registrando
   `restore_rehearsal=passed`;
7. obter confirmação final do operador e do DBA no `change_ticket`.

O backup do plano de controle não substitui backup de tenant, e backup de um tenant não
serve para outro. Todos os backups e ensaios devem estar verdes antes da primeira migração.
Se qualquer banco falhar, nenhum banco do conjunto pode ser migrado naquela
execução; corrigir a evidência e pedir nova autorização.

### 7.6.3 Ordem das duas linhagens de migração

A aplicação web jamais executa migração no startup ou durante request. A janela aprovada
usa credenciais de migração temporárias e processa uma linhagem por vez:

1. parar a aplicação central e manter o Apache/Basic Auth como barreira de homologação;
2. aplicar somente `alembic-control.ini` ao `control_database`;
3. confirmar exatamente `c01a5d8e4f20` em `alembic_control_version`;
4. executar preflight redigido com seletores explícitos para os tenants do manifesto;
5. para cada tenant, aplicar a linhagem `alembic.ini` somente ao banco daquela linha;
6. confirmar exatamente `a4c9d2e7f1b6`, identidade, contagens e RLS antes de avançar;
7. registrar sucesso ou falha de cada tenant independentemente, sem ativação automática.

Não passar slug, DSN ou nome do banco pelo navegador. O `FleetService` recebe seletores
explícitos, exige `backup_acknowledged=True` e `confirmed=True`, mas esses booleanos
não substituem as evidências por banco do manifesto. Até existir um wrapper operacional
separadamente revisado, não improvisar comandos de shell que injetem DSNs ou contornem
o cofre DPAPI.

#### Tratamento especial do tenant existente `default`

A migração de default nunca copia dados comerciais para outro banco. Ela preserva o
banco atual e o workspace `default`, adiciona somente estruturas de autenticação,
`tenant_identity`, escopo ausente e políticas de segurança.
Não usar pg_dump/pg_restore, COPY, INSERT SELECT ou exportação/importação para “mover” registros comerciais durante
esse cutover.

Antes e depois da migração, comparar contagens antes/depois por tabela comercial,
checksums aprovados, vínculos órfãos e `workspaces.version`. Qualquer divergência não
explicada é no-go. O primeiro administrador é criado apenas pelo fluxo administrativo
idempotente `activate-default`, depois da revisão e identidade corretas; usuários
existentes não recebem senha inventada.

### 7.6.4 Gate de identidade e RLS por tenant

Antes de liberar login ou escrita, o DBA e o operador verificam em cada banco tenant:

- existe uma única linha `tenant_identity`;
- `tenant_identity.control_tenant_id` é o UUID da linha correspondente no plano de
  controle e `workspace_id='default'`;
- `schema_contract` é o contrato suportado e o preflight não retorna
  `identity_mismatch`;
- todas as tabelas comerciais protegidas exibem `relrowsecurity=true` e
  `relforcerowsecurity=true`;
- a role de runtime, sem `smartcrm.workspace_id`, não lê dados comerciais e não grava;
- a mesma role com contexto ausente ou incorreto não lê e tem escrita rejeitada;
- com o contexto correto, somente o workspace daquele banco é visível e gravável;
- a role de runtime não é owner, superuser nem possui `BYPASSRLS`.

Executar esses testes com a role real de runtime, nunca apenas com owner/migrator, pois
o owner pode mascarar uma política mal aplicada. Falha de identidade ou RLS deixa o
tenant em `failed ou inactive`, invalida seu pool e bloqueia sua ativação.

### 7.6.5 UAT de isolamento e ativação

Registrar resultado UAT por tenant. Para pelo menos dois bancos de teste isolados, criar
o mesmo ID público nos tenants A e B e provar que a sessão de A não acessa B mesmo com
slug, corpo, header ou ID adulterado. Cobrir
leitura, criação, alteração, exclusão e restauração, além de versão otimista e vínculos.

O UAT também comprova que a indisponibilidade do tenant B não muda o roteamento do tenant A,
não usa cache comercial e não escolhe outro banco. Confirmar login genérico,
cookie opaco, logout/revogação, perfis no servidor e ausência de token no JavaScript.

Ativar cada tenant somente depois de backup, revisão, identidade, RLS e resultado UAT
por tenant aprovados. A ativação de um tenant não autoriza o próximo.
Basic Auth continua ativa até um corte separado e explicitamente autorizado.

### 7.6.6 Rollback independente e sem fallback entre bancos

Falha de um tenant não autoriza rollback em massa.
Os demais tenants permanecem nos próprios bancos e continuam somente se seus gates individuais estiverem verdes.

Para falha antes da ativação, manter o tenant `failed ou inactive`, invalidar seu pool
e preservar banco, dump, hashes e logs. Para reversão de dados indispensável:

1. parar a aplicação ou bloquear apenas o tenant afetado;
2. restaurar o backup daquele tenant em banco novo e isolado, sem `--clean`;
3. validar revisão, contagens, RLS e `tenant_identity` no banco restaurado;
4. criar uma nova referência no cofre e atualizar somente o secret_ref do tenant afetado;
5. repetir preflight e UAT antes de reativá-lo;
6. manter o banco anterior intacto até encerramento do incidente.

Rollback de um tenant nunca redireciona para o banco de outro tenant. É proibido apontar
um tenant para uma referência já pertencente a outro UUID, usar o banco `default` como
fallback ou restaurar o dump de um cliente sobre banco de outro cliente.

Se o plano de controle falhar, parar a aplicação central e restaurar somente seu backup
em um banco de controle novo e validado. Não alterar os bancos tenant durante esse
procedimento. Reconciliar os mesmos UUIDs, slugs e `secret_ref` opacos antes do restart.
Não executar downgrade Alembic: rollback de código requer compatibilidade com o schema
já aplicado ou uma migração forward aprovada.

### 7.6.7 Evidência de go/no-go

A decisão final deve anexar manifesto assinado, hashes, ensaios de restore, revisões,
preflight redigido, contagens, probes de identidade/RLS e UAT por tenant. O go é
registrado por banco. Qualquer item ausente é no-go para aquele banco, sem ampliar a
seleção, copiar dados ou reaproveitar a autorização de outro tenant.

## 8. Executar como serviço Windows com WinSW

### 8.1 Escolha

WinSW 2.12.0 NET4 foi escolhido porque transforma um processo console em serviço SCM, oferece dependência, auto-start, reinício por falha e rotação. NSSM é uma alternativa, mas não é necessário introduzir dois mecanismos. A tarefa agendada existente no repositório funciona para homologação, porém não atende ao requisito atual de serviço Windows.

Baixar `WinSW.NET4.exe` somente da release oficial `v2.12.0` no GitHub, em estação confiável. Registrar SHA-256 aprovado e transferir junto. No servidor:

```powershell
$WinSwSource = 'C:\Transfer\WinSW.NET4.exe'
$ExpectedWinSwSha256 = '<SHA256_APROVADO_WINSW_2_12_0>'
if ((Get-FileHash -LiteralPath $WinSwSource -Algorithm SHA256).Hash -ne $ExpectedWinSwSha256) {
    throw 'Hash WinSW divergente.'
}
$WinSw = Join-Path $ServiceRoot 'SmartCRMService.exe'
Copy-Item -LiteralPath $WinSwSource -Destination $WinSw
```

Criar ao lado `C:\ProgramData\SmartCRM\service\SmartCRMService.xml`, substituindo `PENDENTE_DB_SERVICE_NAME` pelo nome real:

```xml
<service>
  <id>SmartCRM</id>
  <name>SmartCRM</name>
  <description>Smart CRM FastAPI/Uvicorn em loopback</description>
  <executable>%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe</executable>
  <arguments>-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ProgramData\SmartCRM\service\start-smart-crm-production.ps1"</arguments>
  <workingdirectory>C:\brbots\apps\smart-crm</workingdirectory>
  <startmode>Automatic</startmode>
  <delayedAutoStart>true</delayedAutoStart>
  <depend>PENDENTE_DB_SERVICE_NAME</depend>
  <serviceaccount>
    <username>NT AUTHORITY\LocalService</username>
  </serviceaccount>
  <hidewindow>true</hidewindow>
  <stoptimeout>30 sec</stoptimeout>
  <onfailure action="restart" delay="10 sec" />
  <resetfailure>1 hour</resetfailure>
  <logpath>C:\ProgramData\SmartCRM\logs</logpath>
  <log mode="roll-by-size">
    <sizeThreshold>10240</sizeThreshold>
    <keepFiles>14</keepFiles>
  </log>
</service>
```

Validar placeholders antes da instalação:

```powershell
$WinSwXml = Join-Path $ServiceRoot 'SmartCRMService.xml'
[xml]$serviceXml = Get-Content -LiteralPath $WinSwXml -Raw
if ($serviceXml.OuterXml -match 'PENDENTE|<DB_|<CAMINHO|<SHA') {
    throw 'Configuração WinSW ainda contém placeholder.'
}
icacls $WinSw,$WinSwXml,$Wrapper /inheritance:r /grant:r `
    '*S-1-5-18:F' '*S-1-5-32-544:F' '*S-1-5-19:RX'
```

### 8.2 Instalar e operar

**PowerShell elevado:**

```powershell
Set-Location -LiteralPath $ServiceRoot
& $WinSw install
if ($LASTEXITCODE -ne 0) { throw 'Instalação do serviço falhou.' }
& $WinSw start
& $WinSw status
Get-Service -Name SmartCRM
Get-CimInstance Win32_Service -Filter "Name='SmartCRM'" |
    Select-Object Name,State,StartMode,StartName,PathName
```

Comandos operacionais:

```powershell
& $WinSw stop
& $WinSw start
& $WinSw restart
& $WinSw status
Get-WinEvent -FilterHashtable @{LogName='Application'; StartTime=(Get-Date).AddHours(-2)} |
    Where-Object ProviderName -Match 'WinSW|SmartCRM' |
    Select-Object -First 50 TimeCreated,LevelDisplayName,Message
```

`uninstall` remove o registro do serviço e é destrutivo para a configuração SCM. Executá-lo somente no rollback aprovado, depois de parar o serviço; ele não deve apagar aplicação, logs ou banco.

## 9. Apache reverse proxy e HTTPS

### 9.1 Módulos necessários

Confirmar uma ocorrência carregada de: `mod_alias`, `mod_auth_basic`, `mod_authn_core`, `mod_authn_file`, `mod_authz_core`, `mod_headers`, `mod_proxy`, `mod_proxy_http`, `mod_rewrite`, `mod_socache_shmcb` e `mod_ssl`. `mod_log_config` normalmente é base. Não carregar DLL duplicada.

```powershell
$Httpd = Join-Path $ApacheRoot 'bin\httpd.exe'
& $Httpd -M
```

### 9.2 Certificado

Salvar fora da aplicação:

- `C:\ProgramData\SmartCRM\tls\<DOMINIO>-fullchain.pem`;
- `C:\ProgramData\SmartCRM\tls\<DOMINIO>-privkey.pem`.

Validar SAN, datas e correspondência da chave:

```powershell
$OpenSsl = Join-Path $ApacheRoot 'bin\openssl.exe'
$FullChain = Join-Path $TlsRoot "$Domain-fullchain.pem"
$PrivateKey = Join-Path $TlsRoot "$Domain-privkey.pem"
& $OpenSsl x509 -in $FullChain -noout -subject -issuer -dates -ext subjectAltName
& $OpenSsl x509 -checkend 1209600 -noout -in $FullChain
if ($LASTEXITCODE -ne 0) { throw 'Certificado expira em menos de 14 dias.' }
& $OpenSsl x509 -pubkey -noout -in $FullChain -out (Join-Path $env:LOCALAPPDATA 'crm-cert-pub.pem')
& $OpenSsl pkey -pubin -in (Join-Path $env:LOCALAPPDATA 'crm-cert-pub.pem') -outform DER -out (Join-Path $env:LOCALAPPDATA 'crm-cert-pub.der')
& $OpenSsl pkey -in $PrivateKey -pubout -outform DER -out (Join-Path $env:LOCALAPPDATA 'crm-key-pub.der')
Get-FileHash -Algorithm SHA256 -LiteralPath `
    (Join-Path $env:LOCALAPPDATA 'crm-cert-pub.der'), `
    (Join-Path $env:LOCALAPPDATA 'crm-key-pub.der')
```

Os hashes públicos devem ser idênticos. Os arquivos públicos temporários podem ser removidos depois; nunca remova a chave/cadeia em uso. Restringir:

```powershell
icacls $PrivateKey /inheritance:r /grant:r `
    '*S-1-5-18:F' '*S-1-5-32-544:F' "$ApacheServiceAccount`:R"
icacls $FullChain /inheritance:r /grant:r `
    '*S-1-5-18:F' '*S-1-5-32-544:F' "$ApacheServiceAccount`:R"
```

### 9.3 Basic Auth temporária

A senha HTTP deve ser diferente do banco. Basic Auth é somente controle de perímetro e não implementa usuários/perfis do CRM.

```powershell
$Htpasswd = Join-Path $ApacheRoot 'bin\htpasswd.exe'
$HtpasswdFile = Join-Path $ApacheConfigRoot '.htpasswd-smart-crm'
& $Htpasswd -c $HtpasswdFile '<USUARIO_HTTP>'
icacls $HtpasswdFile /inheritance:r /grant:r `
    '*S-1-5-18:F' '*S-1-5-32-544:F' "$ApacheServiceAccount`:R"
```

### 9.4 VirtualHost completo

Criar `conf\extra\httpd-smart-crm.conf` no Apache, substituindo todos os placeholders. O exemplo usa TLS 1.2 para compatibilidade ampla; TLS 1.3 só deve ser acrescentado se `httpd -V`/OpenSSL confirmarem suporte e os clientes forem testados.

```apache
<VirtualHost *:80>
    ServerName <DOMINIO_FQDN>

    Alias "/.well-known/acme-challenge/" "C:/ProgramData/SmartCRM/acme-challenge/"
    <Directory "C:/ProgramData/SmartCRM/acme-challenge">
        Options None
        AllowOverride None
        Require all granted
    </Directory>

    RewriteEngine On
    RewriteCond %{REQUEST_URI} !^/\.well-known/acme-challenge/
    RewriteRule ^ https://<DOMINIO_FQDN>%{REQUEST_URI} [R=301,L,NE]

    ErrorLog "logs/smart-crm-error.log"
    CustomLog "logs/smart-crm-access.log" combined
</VirtualHost>

<VirtualHost *:443>
    ServerName <DOMINIO_FQDN>

    SSLEngine On
    SSLProtocol -all +TLSv1.2
    SSLCertificateFile "C:/ProgramData/SmartCRM/tls/<DOMINIO_FQDN>-fullchain.pem"
    SSLCertificateKeyFile "C:/ProgramData/SmartCRM/tls/<DOMINIO_FQDN>-privkey.pem"

    ProxyRequests Off
    ProxyPreserveHost On
    ProxyAddHeaders On
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-Port "443"

    ProxyPass "/" "http://127.0.0.1:8080/" connectiontimeout=5 timeout=60 retry=0
    ProxyPassReverse "/" "http://127.0.0.1:8080/"

    LimitRequestBody 26214400

    Header always set Strict-Transport-Security "max-age=31536000"
    Header always set X-Content-Type-Options "nosniff"
    Header always set Referrer-Policy "no-referrer"

    <Location "/">
        AuthType Basic
        AuthName "Smart CRM"
        AuthBasicProvider file
        AuthUserFile "C:/ProgramData/SmartCRM/apache/.htpasswd-smart-crm"
        Require valid-user
    </Location>

    ErrorLog "logs/smart-crm-error.log"
    CustomLog "logs/smart-crm-access.log" combined
</VirtualHost>
```

Se houver allowlist de rede, acrescentar `Require ip <CIDR_APROVADO>` com combinação de autorização revisada. Não ativar HSTS de um ano antes de confirmar TLS e ownership do domínio; durante ensaio controlado pode-se usar `max-age=300` e elevar após aprovação.

### 9.5 Backup, inclusão e teste

```powershell
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$ApacheBackup = Join-Path $BackupRoot "apache-$Stamp"
New-Item -ItemType Directory -Path $ApacheBackup -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $ApacheRoot 'conf\httpd.conf') -Destination $ApacheBackup
Copy-Item -LiteralPath (Join-Path $ApacheRoot 'conf\extra') -Destination (Join-Path $ApacheBackup 'extra') -Recurse
& $Httpd -S 2>&1 | Set-Content -LiteralPath (Join-Path $ApacheBackup 'vhosts-before.txt')
& $Httpd -M 2>&1 | Set-Content -LiteralPath (Join-Path $ApacheBackup 'modules-before.txt')
```

Adicionar uma única linha ao `httpd.conf`, se ainda não existir:

```apache
Include conf/extra/httpd-smart-crm.conf
```

Antes de reiniciar:

```powershell
& $Httpd -t
if ($LASTEXITCODE -ne 0) { throw 'Apache inválido; não reiniciar.' }
& $Httpd -S
& $Httpd -M
Get-Content -LiteralPath (Join-Path $ApacheRoot 'conf\httpd.conf') |
    Select-String 'httpd-smart-crm.conf'
```

Deve existir apenas um VirtualHost para o FQDN em cada porta. Somente com `Syntax OK`, serviço Python saudável e rollback disponível:

```powershell
Restart-Service -Name $ApacheService
Get-Service -Name $ApacheService
```

## 10. Firewall e DNS

Criar regras somente se não houver política central equivalente. Restringir perfis conforme política; não abrir 8080 ou PostgreSQL publicamente.

```powershell
Get-NetFirewallRule -Enabled True | Where-Object DisplayName -Match 'Apache|Smart CRM'
New-NetFirewallRule -DisplayName 'Smart CRM HTTPS 443' -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort 443 -Profile Domain,Private
New-NetFirewallRule -DisplayName 'Smart CRM HTTP 80 ACME Redirect' -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort 80 -Profile Domain,Private
Resolve-DnsName $Domain
Test-NetConnection -ComputerName $Domain -Port 443
Get-NetTCPConnection -State Listen |
    Where-Object LocalPort -In 80,443,8080,$DbPort |
    Select-Object LocalAddress,LocalPort,OwningProcess
```

Se o serviço for público, o perfil de firewall e o edge/NAT precisam ser aprovados explicitamente. `8080` deve mostrar apenas `127.0.0.1`; se PostgreSQL for local, a escuta deve seguir a política do DBA e nunca ser ampliada por este runbook.

## 11. Ordem exata do deploy

1. Abrir mudança, confirmar responsáveis, RPO/RTO, janela e rollback.
2. Preencher todas as pendências da seção 1 e executar o gate de placeholders.
3. Registrar inventário do Windows, patches, CPU/RAM/disco, portas, serviços, Apache/OpenSSL e PostgreSQL.
4. Corrigir patches/Visual C++/.NET em janela anterior; reiniciar e validar.
5. Na máquina confiável, fixar o commit aprovado e gerar bundle offline + SHA-256.
6. Baixar Python 3.11.5 e WinSW 2.12.0 das fontes indicadas; registrar hash/assinatura.
7. Transferir artefatos sem executá-los e validar todos os hashes no servidor.
8. Descobrir caminhos/contas reais de Apache e PostgreSQL; não alterar o serviço PG11.
9. Instalar/validar CPython 3.11.5 x64.
10. Extrair a aplicação em diretório novo, validar manifesto, criar virtualenv e instalar da wheelhouse com `--no-index`.
11. Criar estrutura `C:\ProgramData\SmartCRM`, wrapper, `server.env` e ACLs.
12. Inventariar banco, objetos, owner, encoding, extensions, `search_path` e Alembic.
13. Bloquear se houver colisão, banco compartilhado não aprovado ou revisão divergente.
14. Gerar backup custom + globals, hashes e cópia externa.
15. Restaurar o dump em banco/host de ensaio separado e validar dados.
16. Gerar SQL Alembic offline e obter revisão/aprovação do DBA.
17. Congelar escrita e confirmar que o serviço SmartCRM está parado.
18. Aplicar `alembic upgrade head` uma única vez com role de migração.
19. Confirmar head `9f7a2c31d5e8`, tabelas, owner, grants e contagens.
20. Instalar/iniciar serviço WinSW como LocalService e validar `http://127.0.0.1:8080/health`.
21. Validar que 8080 está somente em loopback e revisar logs.
22. Instalar/validar certificado e chave; criar Basic Auth/allowlist temporária.
23. Fazer backup do Apache, instalar VirtualHost, rodar `httpd -t`, `-S` e `-M`.
24. Reiniciar Apache e validar HTTP, HTTPS, certificado, health e frontend.
25. Executar smoke test e UAT controlado; nunca usar dados reais de clientes no primeiro teste.
26. Reiniciar somente o serviço SmartCRM, repetir testes.
27. Em janela aprovada, reiniciar o Windows e repetir o checklist pós-reboot.
28. Registrar SHA, revisões, hashes, evidências, horário e decisão go/no-go.
29. Liberar usuários somente após aceite de segurança/autenticação e resultado UAT.

## 12. Validação, smoke test e UAT

### 12.1 Infraestrutura

```powershell
Get-Service -Name SmartCRM,$ApacheService,$PostgresService
& $WinSw status
Get-NetTCPConnection -State Listen |
    Where-Object LocalPort -In 80,443,8080,$DbPort |
    Select-Object LocalAddress,LocalPort,OwningProcess
$localHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 10
$localHealth | ConvertTo-Json -Compress
if ($localHealth.status -ne 'ok' -or $localHealth.database -ne 'ok') { throw 'Health local falhou.' }
```

### 12.2 Banco e migração

```powershell
$runtimeCredential = Get-Credential -UserName $DbRuntimeUser -Message 'Credencial runtime para teste'
$env:PGPASSWORD = $runtimeCredential.GetNetworkCredential().Password
try {
    & $Psql -X -v ON_ERROR_STOP=1 -h $DbHost -p $DbPort -U $DbRuntimeUser -d $DbName `
        -c 'SELECT current_database(), current_user, now();'
    & $Psql -X -v ON_ERROR_STOP=1 -h $DbHost -p $DbPort -U $DbRuntimeUser -d $DbName `
        -c "SELECT id, version, initialized_at FROM workspaces WHERE id='default';"
    & $Psql -X -v ON_ERROR_STOP=1 -h $DbHost -p $DbPort -U $DbRuntimeUser -d $DbName `
        -c 'SELECT version_num FROM alembic_version;'
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    $runtimeCredential = $null
}
```

Resultado Alembic esperado: `9f7a2c31d5e8`.

### 12.3 HTTP/HTTPS

```powershell
curl.exe --fail --silent --show-error http://127.0.0.1:8080/health
curl.exe -I "http://$Domain/"
curl.exe -I "https://$Domain/"
curl.exe --user '<USUARIO_HTTP>' "https://$Domain/health"
curl.exe --user '<USUARIO_HTTP>' "https://$Domain/api/workspace"
& $OpenSsl s_client -connect "$Domain`:443" -servername $Domain -verify_return_error
```

Não usar `curl -k`/`--insecure`. Esperado: HTTP 301; HTTPS sem credencial 401 se Basic Auth estiver ativo; health autenticado retorna `{"status":"ok","database":"ok"}`.

### 12.4 Checklist de smoke test

- [ ] Serviço SmartCRM `Running` como `NT AUTHORITY\LocalService`.
- [ ] Apache e PostgreSQL nos estados esperados.
- [ ] `127.0.0.1:8080` é a única escuta Uvicorn.
- [ ] Health local e HTTPS estão OK.
- [ ] Certificado válido, SAN correto, cadeia completa e sem `--insecure`.
- [ ] `/` carrega HTML/CSS/JS sem 404 no console do navegador.
- [ ] `/api/workspace` responde no mesmo domínio.
- [ ] Nenhuma senha aparece em logs.
- [ ] Alembic está em `9f7a2c31d5e8`.
- [ ] Contagens do banco antes/depois são reconciliadas e explicadas.
- [ ] Logs Apache/WinSW não mostram 5xx repetidos.

### 12.5 UAT funcional controlado

Usar registro de teste identificável e previamente autorizado; não reutilizar contato real.

- [ ] Abrir dashboard e módulos Leads, Contatos, Empresas e Negócios.
- [ ] Confirmar carregamento do estado do banco.
- [ ] Validar autenticação de perímetro e registrar a limitação dos perfis demonstrativos.
- [ ] Criar um registro UAT, anotar ID/versão, ler em outro navegador/sessão e editar.
- [ ] Confirmar incremento de `workspaces.version`.
- [ ] Excluir logicamente e restaurar o mesmo registro.
- [ ] Validar filtros, Lista/Kanban e preferências persistidas.
- [ ] Criar orçamento sem PDF real; confirmar que somente o nome do arquivo é persistido.
- [ ] Reiniciar SmartCRM e reler o registro.
- [ ] Após reboot aprovado do Windows, repetir health, login de perímetro, leitura e logs.
- [ ] Remover logicamente/neutralizar o registro UAT conforme regra do negócio; não usar SQL direto.

## 13. Operação contínua

### 13.1 Logs e retenção

- WinSW/Uvicorn: `C:\ProgramData\SmartCRM\logs\SmartCRMService.out.log`, `.err.log` e arquivos rolados; 10 MB × 14 por stream na configuração proposta.
- Apache: `<APACHE_ROOT>\logs\smart-crm-access.log` e `smart-crm-error.log`.
- Windows: Event Viewer > Application/System.
- PostgreSQL: localização pendente conforme `log_directory`/serviço existente.

Coletar alertas para: serviço parado, 5xx/502, health != 200, disco <20%, certificado <30 dias, backup ausente/falho, erro Alembic, conexões/pool e crescimento anormal de logs/banco. Não enviar payloads comerciais ou segredos ao monitoramento.

Para logs Apache, usar `rotatelogs.exe` ou política central. Exemplo sujeito a validação do caminho:

```apache
CustomLog "|bin/rotatelogs.exe -l logs/smart-crm-access-%Y%m%d.log 86400" combined
ErrorLog "|bin/rotatelogs.exe -l logs/smart-crm-error-%Y%m%d.log 86400"
```

### 13.2 Backup recorrente

- Diário: `pg_dump -Fc` do banco com conta de backup somente leitura adequada.
- Após cada backup: código de saída, tamanho, `pg_restore --list`, SHA-256 e cópia externa/imutável.
- Semanal ou conforme RPO: ensaio automatizado em destino isolado.
- Antes de toda release/migração: backup sob demanda e restore testado.
- Retenção, criptografia, off-site e descarte: **PENDENTE DE CONFIRMAÇÃO**.

### 13.3 Renovação de certificado

Renovar antes de 30 dias do vencimento. Validar SAN, cadeia, `x509 -checkend`, chave correspondente e ACL. Instalar novos arquivos com nomes versionados, alterar VirtualHost, executar `httpd -t`, reiniciar Apache e testar sem `--insecure`. Manter certificado anterior até o novo passar; não apagar a chave anterior na mesma mudança.

### 13.4 Atualizar aplicação

Usar diretórios versionados para rollback de código, por exemplo `C:\brbots\apps\smart-crm-<SHA>`, e um caminho operacional aprovado. Como o serviço atual aponta a um caminho fixo, a troca deve ser feita alterando wrapper/XML durante a janela, com backup deles.

Sequência: gerar bundle do commit, validar hashes, extrair em diretório novo, criar nova virtualenv, `pip check`, backup/restore rehearsal, revisar/aplicar migração, parar serviço, atualizar caminho, iniciar, smoke/UAT. Manter versão anterior somente leitura até o fim da retenção.

Não executar `git pull` diretamente em produção no caminho ativo e não instalar dependências sem pins/wheelhouse. Atualizações de Python, FastAPI, Uvicorn, SQLAlchemy, Psycopg ou Alembic são mudanças independentes com testes backend/browser e compatibilidade PG11.

## 14. Rollback e restauração

### 14.1 Critérios de rollback

- migração falhou ou revisão não é o head esperado;
- health local/externo falha;
- 502/5xx persistente;
- corrupção/perda de dados, contagens divergentes ou falha de gravação/leitura;
- TLS/DNS/autenticação de perímetro incorretos;
- UAT crítico reprovado.

### 14.2 Rollback sem mudança de banco

Se o problema for serviço/Apache e o schema continuar compatível:

```powershell
Stop-Service -Name SmartCRM
Copy-Item -LiteralPath (Join-Path $ApacheBackup 'httpd.conf') `
    -Destination (Join-Path $ApacheRoot 'conf\httpd.conf') -Force
$ApacheExtraBackup = Join-Path $ApacheBackup 'extra'
$ApacheExtraTarget = Join-Path $ApacheRoot 'conf\extra'
Get-ChildItem -LiteralPath $ApacheExtraBackup -Force |
    Copy-Item -Destination $ApacheExtraTarget -Recurse -Force
& $Httpd -t
if ($LASTEXITCODE -ne 0) { throw 'Configuração Apache anterior não validou; não reiniciar.' }
Restart-Service -Name $ApacheService
```

**Aviso:** `Copy-Item -Force` sobrescreve somente os arquivos de configuração Apache que acabaram de ser respaldados. O backup permanece em `$ApacheBackup`; validar o caminho exibido antes de executar. Nenhum arquivo de banco é tocado.

Reapontar WinSW para o diretório da aplicação anterior somente se essa versão for compatível com o schema atual. Não fazer downgrade Alembic.

### 14.3 Restauração preservando o banco original

Quando a reversão de dados for indispensável, restaurar o dump em **novo banco**, validar e trocar a URL do SmartCRM. O banco original permanece intacto e offline para a aplicação.

1. Parar SmartCRM e congelar escritores.
2. Criar `<DB_RESTORE_PRODUCAO_NOVO>` com owner aprovado.
3. Restaurar com `pg_restore --exit-on-error --no-owner`, sem `--clean`.
4. Validar Alembic, contagens, constraints e UAT interno.
5. Alterar apenas `SMART_CRM_DB_NAME` em `server.env` para o novo nome.
6. Revisar ACL, iniciar serviço, health e UAT.
7. Manter o banco original sem alterações até encerramento do incidente.

**Não restaurar globals automaticamente em produção.** `globals.sql` pode conter roles/atributos em nível de cluster e deve ser revisado pelo DBA.

### 14.4 O que nunca fazer no rollback

- não executar `alembic downgrade`;
- não restaurar com `--clean` ou sobre o banco existente;
- não dropar/recriar banco, schema, tabelas ou roles;
- não trocar senha/owner do banco compartilhado como atalho;
- não apagar diretório anterior, logs ou backups durante o incidente;
- não reiniciar/parar PostgreSQL 11 sem mudança própria e impacto analisado.

## 15. Troubleshooting

| Sintoma | Causas prováveis | Diagnóstico/ação segura |
| --- | --- | --- |
| SmartCRM não inicia | placeholder, ACL, Python/venv ausente, porta ocupada, banco indisponível | `Get-Service SmartCRM`; `& $WinSw status`; Event Viewer; logs WinSW; `Test-Path $Wrapper,$EnvFile,$VenvPython`; `Get-NetTCPConnection -LocalPort 8080` |
| Apache 502 | Uvicorn parado, health degradado, porta/timeout incorreto | `Invoke-RestMethod http://127.0.0.1:8080/health`; `Test-NetConnection 127.0.0.1 -Port 8080`; logs Apache; reiniciar apenas SmartCRM após causa corrigida |
| Banco inacessível | host/porta/role/senha, `pg_hba.conf`, serviço ou rede | `Test-NetConnection $DbHost -Port $DbPort`; `psql -X ... -c 'SELECT 1'`; log PG. Não editar/reiniciar PG11 sem DBA |
| Migração falha | colisão, privilégio DDL, revisão divergente, constraint/dados | preservar stdout/stderr; `alembic current --verbose`; consultar `alembic_version`; revisar SQL e transação. Não repetir/stamp/downgrade |
| Estáticos não carregam | proxy/vhost errado, arquivo ausente, ACL | `Test-Path $AppRoot\app\static\index.html`; `curl.exe -I http://127.0.0.1:8080/`; DevTools Network; logs Apache/Uvicorn |
| PDF não aparece | comportamento esperado do protótipo | o código guarda somente `pdf_name`; não há diretório/serviço de upload binário |
| Access denied NTFS | LocalService/Apache sem RX/R/M necessários | `Get-Acl`; `icacls`; `Get-CimInstance Win32_Service`. Corrigir só o caminho exato, sem `Everyone:F` |
| Porta ocupada | processo antigo/duplicado | `Get-NetTCPConnection -State Listen -LocalPort 8080`; `Get-Process -Id <PID>`; não matar processo antes de identificar owner/serviço |
| DLL ausente | VC++ runtime, wheel/arquitetura errada | validar CPython x64; `pip check`; importar módulos; Event Viewer; reinstalar VC++ oficial, não baixar DLL avulsa |
| TLS inválido | certificado expirado/SAN/cadeia/chave, relógio, OpenSSL | `openssl s_client ... -verify_return_error`; `x509 -dates -ext subjectAltName`; comparar chaves públicas; `w32tm /query /status` |
| HTTP não redireciona | mod_rewrite/vhost/DNS | `httpd -M`; `httpd -S`; `curl.exe -I http://$Domain/` |
| Health 503 | `SELECT 1` falhou | testar `psql`, credencial e log; UI pode abrir com cache, mas escrita deve permanecer bloqueada |
| Gravação retorna 409 | versão otimista desatualizada | recarregar estado canônico; não editar banco diretamente |
| Payload 413 | corpo acima de 25 MB | limite conjunto da aplicação e Apache é 26.214.400 bytes; reduzir payload, não elevar sem análise |

Comandos adicionais de diagnóstico:

```powershell
Get-Content -LiteralPath (Join-Path $LogRoot 'SmartCRMService.err.log') -Tail 200
Get-Content -LiteralPath (Join-Path $ApacheRoot 'logs\smart-crm-error.log') -Tail 200
& $Httpd -t
& $Httpd -S
& $Httpd -M
& $VenvPython -m pip check
& $VenvPython -c "import platform,struct,fastapi,psycopg,sqlalchemy,uvicorn; print(platform.platform(),struct.calcsize('P')*8,fastapi.__version__,psycopg.__version__,sqlalchemy.__version__,uvicorn.__version__)"
```

## 16. Checklists de mudança

### Pré-instalação

- [ ] Pendências preenchidas e aprovadas.
- [ ] Risco de autenticação/autorização aceito ou corrigido.
- [ ] Windows atualizado; reboot concluído.
- [ ] Espaço, RAM, CPU, portas e DNS validados.
- [ ] PostgreSQL 11.22/EOL reconhecido; nenhum restart planejado.
- [ ] Bundle/instaladores/WinSW vindos de fontes aprovadas e hashes registrados.
- [ ] Backup/restore, RPO/RTO e janela definidos.

### Instalação

- [ ] Apache real inventariado ou instalado sem sobrescrever instância.
- [ ] CPython exatamente 3.11.5 x64 validado.
- [ ] Bundle extraído em diretório novo e manifesto válido.
- [ ] Virtualenv criada com o executável correto.
- [ ] Dependências instaladas offline; `pip check` passou.
- [ ] Nenhum build Node executado no servidor.
- [ ] Diretórios e ACLs aplicados sem permissões amplas.
- [ ] `server.env` fora do Git e sem placeholders.
- [ ] Wrapper PowerShell e XML WinSW validados.

### Pré-deploy

- [ ] Banco/owner/role/host/porta/encoding/search_path confirmados.
- [ ] Ausência de colisões confirmada.
- [ ] Revisão Alembic atual conhecida.
- [ ] Backup custom/globals, hashes e cópia externa concluídos.
- [ ] Restauração de ensaio passou.
- [ ] SQL Alembic revisado/aprovado.
- [ ] Certificado, cadeia, chave e Basic Auth/allowlist prontos.
- [ ] Backup Apache e aplicação anterior disponíveis.

### Deploy

- [ ] Escrita congelada e SmartCRM parado.
- [ ] `alembic upgrade head` terminou com código zero.
- [ ] Head `9f7a2c31d5e8` confirmado.
- [ ] Grants mínimos aplicados/testados.
- [ ] WinSW instalado como LocalService, automático e dependente do PG real.
- [ ] Health local OK antes do Apache.
- [ ] `httpd -t`, `-S` e `-M` passaram.
- [ ] Apache reiniciado sem afetar PostgreSQL.

### Pós-deploy

- [ ] HTTP 301 e HTTPS válido.
- [ ] Sem credencial retorna 401 quando Basic Auth ativo.
- [ ] Health HTTPS autenticado OK.
- [ ] Frontend/estáticos/API carregam.
- [ ] Smoke e UAT de leitura/gravação controlada passaram.
- [ ] Reinício do serviço e reboot do Windows testados.
- [ ] Logs limpos de erro crítico e segredos.
- [ ] SHA Git, hashes, revisão DB e evidências registrados.
- [ ] Monitoramento, backup recorrente e renovação TLS agendados.

### Rollback

- [ ] Critério de rollback declarado e aprovador comunicado.
- [ ] Escrita congelada; SmartCRM parado.
- [ ] Banco original não foi apagado/sobrescrito.
- [ ] Apache anterior restaurado a partir do backup exato e validado.
- [ ] Código anterior usado somente se compatível com schema.
- [ ] Se necessário, dump restaurado em banco novo e validado.
- [ ] Nunca foi usado `alembic downgrade`, `--clean`, `DROP` ou `TRUNCATE`.
- [ ] Evidências e linha do tempo preservadas.

## 17. Riscos conhecidos

1. **Crítico — autenticação/autorização:** perfis da interface são demonstrativos; não há controle real no backend. Basic Auth compartilhada não resolve segregação, auditoria ou menor privilégio.
2. **Crítico — PostgreSQL 11.22 EOL:** sem correções desde novembro de 2023.
3. **Alto — Windows Server 2016 perto do EOL:** suporte estendido termina em janeiro de 2027.
4. **Alto — banco existente desconhecido:** migrações usam nomes não qualificados; colisões ou `alembic_version` compartilhada podem atingir dados alheios.
5. **Alto — downgrade destrutivo:** a migration base derruba todas as tabelas CRM.
6. **Alto — pins antigos:** dependências fixadas têm releases posteriores; atualizar sem regressão também é arriscado.
7. **Médio/alto — Python 3.11.5 antigo:** a série ainda recebe segurança, mas esse patch está ultrapassado.
8. **Médio — bundle antigo:** o ZIP presente em `dist` não corresponde ao commit analisado.
9. **Médio — frontend monolítico/agregado:** payload máximo 25 MB, ausência de paginação e crescimento linear.
10. **Médio — PDF:** somente o nome é persistido; não existe armazenamento/antivírus/backup de arquivo.
11. **Médio — observabilidade:** logs básicos, sem métricas/tracing/auditoria produtiva no código.
12. **Médio — processo único:** um worker é o padrão validado, mas capacidade/HA não foram testadas.
13. **Médio — WinSW 2.x:** wrapper adicional exige manutenção, hash e monitoramento de releases.

## 18. Evidências do repositório utilizadas

- `README.md`
- `pyproject.toml`
- `requirements-runtime.txt`
- `package.json` e `pnpm-lock.yaml`
- `Dockerfile`, `compose.yaml` e `compose.server.yaml` (somente como evidência; Docker não é usado)
- `app/main.py`, `app/database.py`, `app/models.py`, `app/schemas.py`
- `app/repositories/workspace.py` e `app/services/workspace.py`
- `app/static/index.html`
- `alembic.ini`, `migrations/env.py` e as duas revisões em `migrations/versions`
- todo `deploy/manual-windows-pg11`
- todo `deploy/windows-apache`
- `deploy/server` como contraste da implantação Docker/Linux
- `scripts/build_manual_windows_pg11_bundle.py`
- verificadores `scripts/verify_*windows*` e testes de deploy/migração/backend
- especificações de deploy Windows, persistência PostgreSQL e CRM em `.specs/features`

Não existem no repositório analisado: `AGENTS.md`, `PROJECT_OVERVIEW.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `DISCOVERY.md` ou `.env.example` na raiz. Existem exemplos de ambiente dentro de `deploy`, analisados com as ressalvas registradas.

## 19. Decisões técnicas resumidas

- Deploy nativo Windows, sem Docker.
- FastAPI é ASGI; Uvicorn é o servidor, nunca Gunicorn.
- WinSW 2.12.0 registra Uvicorn como serviço SCM sob LocalService.
- Apache termina TLS e faz reverse proxy de todo o site para loopback.
- Frontend não tem build de produção; é servido pela própria FastAPI.
- Wheelhouse offline + manifesto/hash é o mecanismo reproduzível.
- PostgreSQL existente é preservado; migração somente após inventário/backup/restore rehearsal.
- Role de migração separada da role de runtime.
- Rollback de dados sempre restaura em banco novo; não sobrescreve o original.
- Alembic downgrade não é permitido devido ao downgrade destrutivo existente.

## 20. Comandos documentados versus executados

Todos os comandos Windows, Apache, WinSW, Python, firewall, DNS, TLS, `psql`, `pg_dump`, `pg_restore` e Alembic deste arquivo são **somente documentados e não foram executados no servidor de produção**.

Durante a elaboração foram executadas apenas inspeções locais e somente leitura do repositório, listagem do bundle e consultas a documentação pública. Nenhum banco, serviço, firewall, DNS, certificado ou arquivo de aplicação em produção foi alterado.
