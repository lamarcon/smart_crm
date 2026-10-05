# Smart CRM

CRM em desenvolvimento para substituir o uso comercial atual do Bitrix24. O repositório contém as especificações do MVP de produção e um protótipo local navegável para validação antecipada do layout e dos fluxos.

**Status:** a aplicação multiempresa já está em operação na release atualmente publicada. O funil de Negócios personalizável, com revisão tenant `c7f3a9d8e2b1`, está implementado e validado somente no ambiente local deste repositório. Essa atualização ainda não foi enviada nem aplicada em produção; upload, migração e cutover exigem autorização própria.

## Modelo multiempresa: plano de controle e bancos dedicados

A aplicação central atende `/`, `/{slug}` e `/api`, mas não compartilha dados comerciais entre empresas. O slug localiza apenas um candidato antes do login; depois da autenticação, o tenant vem exclusivamente da sessão opaca armazenada no servidor. O navegador nunca recebe DSN, senha de banco ou secret_ref.

O banco de controle armazena somente diretório de tenants, referências opacas de segredo, sessões, limites de login e eventos de segurança. Nunca armazena usuários, hashes de senha, workspaces ou dados comerciais de tenants. Cada banco tenant armazena seus próprios usuários, hashes Argon2id, workspace e dados comerciais.

| Fronteira | Conteúdo | Não contém |
| --- | --- | --- |
| Controle central | `control_tenants`, sessões opacas, throttles e auditoria | CRM, usuários tenant, hashes de senha ou DSNs |
| Tenant A | identidade vinculada ao UUID de controle, usuários e CRM da empresa A | metadados/sessões centrais ou dados da empresa B |
| Tenant B | identidade vinculada ao UUID de controle, usuários e CRM da empresa B | metadados/sessões centrais ou dados da empresa A |
| Navegador | cookie HttpOnly e preferências visuais namespaced | token de sessão, perfil confiável, snapshot comercial ou segredo de banco |

O roteador abre cada PostgreSQL apenas a partir do `tenant_id` confiável da sessão e da referência guardada no plano de controle. Não existe banco default de fallback: indisponibilidade, revisão incompatível ou identidade divergente falham fechadas somente para o tenant afetado.

## Funil de Negócios personalizável V1

Cada workspace possui um único funil padrão de Negócios nesta versão. As etapas são carregadas do banco tenant e usam UUID imutável como identidade. Nome, cor, ordem e etapa inicial podem ser configurados pelo Administrador sem alterar vínculos existentes. Leads continuam com o processo fixo atual.

Regras, indicadores e automações usam semântica interna (`open`, `won` e `lost`) e `system_key`, nunca o nome visível. A automação de Faturamento permanece vinculada a `system_key=billing`, mesmo depois de renomear a etapa. Se o funil canônico estiver indisponível, a interface bloqueia ações dependentes de etapa e não recorre às nove etapas antigas como fallback.

Arquivar uma etapa vazia não exige destino. Arquivar uma etapa ocupada exige transferir, na mesma transação, todos os Negócios ativos e excluídos logicamente para outra etapa ativa. O histórico administrativo registra ator, instante, versão, ações, antes/depois e resumo da transferência. Somente Administradores podem editar o funil ou consultar essa auditoria.

O código e os gates locais desta V1 estão concluídos até T11. A evidência final e o checklist autoral de T12 aguardam verificação independente antes do commit de release. Nenhum resultado local autoriza deploy ou migração de produção.

### Setup local com controle + tenant A + tenant B

Este roteiro é somente para desenvolvimento em uma máquina controlada. Não execute estes comandos contra produção. Nenhum comando desta seção faz deploy, acessa servidor remoto ou altera o ambiente Windows Server.

O PostgreSQL local pode ser uma única instância contendo três bancos separados; produção mantém a topologia de banco/servidor dedicado por empresa. Os nomes locais são:

- `smartcrm_control_local`: metadados e sessões centrais;
- `smartcrm_tenant_a_local`: usuários e dados comerciais do cliente A;
- `smartcrm_tenant_b_local`: usuários e dados comerciais do cliente B.

Em outras palavras, o gate local usa controle + tenant A + tenant B. Inicie somente o serviço PostgreSQL legado e crie os três bancos uma vez, sem apagar bancos existentes:

```powershell
docker compose up -d postgres
docker compose exec -T postgres createdb -U smartcrm -O smartcrm smartcrm_control_local
docker compose exec -T postgres createdb -U smartcrm -O smartcrm smartcrm_tenant_a_local
docker compose exec -T postgres createdb -U smartcrm -O smartcrm smartcrm_tenant_b_local
```

Se `createdb` informar que o banco já existe, confira owner e conteúdo em vez de recriá-lo. Não use `DROP DATABASE`, `docker compose down -v` ou restauração sobre um banco existente como parte deste setup.

Capture a senha local sem colocá-la no histórico e monte as URLs apenas na sessão atual:

```powershell
$localCredential = Get-Credential -UserName smartcrm -Message "PostgreSQL local"
$localPassword = [Uri]::EscapeDataString($localCredential.GetNetworkCredential().Password)
$controlUrl = "postgresql+psycopg://smartcrm:$localPassword@127.0.0.1:5432/smartcrm_control_local"
$tenantAUrl = "postgresql+psycopg://smartcrm:$localPassword@127.0.0.1:5432/smartcrm_tenant_a_local"
$tenantBUrl = "postgresql+psycopg://smartcrm:$localPassword@127.0.0.1:5432/smartcrm_tenant_b_local"
```

Essas variáveis não devem ser impressas, persistidas em arquivo versionado ou copiadas para logs. Limpe-as ao terminar a sessão.

### Migrações explícitas e revisões suportadas

Existem duas linhagens Alembic independentes. O runtime nunca executa upgrade no startup nem durante requests. Migre primeiro o controle e depois cada banco tenant explicitamente:

```powershell
$env:SMART_CRM_CONTROL_DATABASE_URL = $controlUrl
python -m alembic -c alembic-control.ini upgrade c01a5d8e4f20
python -m alembic -c alembic-control.ini current

$env:SMART_CRM_DATABASE_URL = $tenantAUrl
python -m alembic -c alembic.ini upgrade a4c9d2e7f1b6
python -m alembic -c alembic.ini current
python -m alembic -c alembic.ini upgrade c7f3a9d8e2b1
python -m alembic -c alembic.ini current

$env:SMART_CRM_DATABASE_URL = $tenantBUrl
python -m alembic -c alembic.ini upgrade a4c9d2e7f1b6
python -m alembic -c alembic.ini current
python -m alembic -c alembic.ini upgrade c7f3a9d8e2b1
python -m alembic -c alembic.ini current
```

No controle, current deve confirmar c01a5d8e4f20. Em cada tenant, o primeiro `current deve confirmar a4c9d2e7f1b6` é o checkpoint da release multiempresa já publicada; o `current` final deve confirmar `c7f3a9d8e2b1`, head local do funil personalizável. Pare se qualquer revisão divergir; não use `stamp`, downgrade ou migração automática para contornar drift.

### Provisionamento administrativo local

Não há endpoint público para cadastrar empresas. As operações administrativas são locais, idempotentes e solicitam segredos interativamente: senhas e DSNs são digitados em prompts, nunca em argumentos de linha de comando. Defina o mesmo diretório local para o comando administrativo e o runtime:

```powershell
$secretStore = Join-Path $PWD ".local\tenant-secrets"
$env:SMART_CRM_SECRET_STORE = $secretStore
$env:SMART_CRM_TENANT_SECRET_STORE = $secretStore
$env:SMART_CRM_CONTROL_DATABASE_URL = $controlUrl
$env:SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK = "1"

python -m app.admin_cli register-tenant cliente-a --display-name "Cliente A" --secret-ref local-cliente-a --expected-revision c7f3a9d8e2b1
python -m app.admin_cli register-tenant cliente-b --display-name "Cliente B" --secret-ref local-cliente-b --expected-revision c7f3a9d8e2b1
python -m app.admin_cli activate-default cliente-a --admin-email admin-a@example.test --admin-name "Admin A"
python -m app.admin_cli resume-provisioning cliente-b --admin-email admin-b@example.test --admin-name "Admin B"
```

`register-tenant` pede a URL completa do banco e a protege no Windows com DPAPI. Os comandos seguintes pedem a senha inicial e persistem somente hash Argon2id. `SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK=1` vale somente neste setup local de três bancos; qualquer outro valor mantém o bloqueio e não autoriza PostgreSQL remoto sem verify-full e CA. Em produção, secret refs, autorizações, backup e UAT seguem o runbook; não existe cadastro público de empresa ou primeiro administrador.

Depois de confirmar as revisões e provisionar ambos os tenants, gere um certificado temporário para o loopback e inicie a aplicação central sem executar migração. O comando usa o OpenSSL disponível no `PATH` ou o distribuído com Git for Windows:

```powershell
$openssl = (Get-Command openssl.exe -ErrorAction SilentlyContinue).Source
if (-not $openssl) { $openssl = Join-Path $env:ProgramFiles "Git\usr\bin\openssl.exe" }
if (-not (Test-Path -LiteralPath $openssl)) { throw "OpenSSL local não encontrado." }

$tlsDir = Join-Path $PWD ".local\dev-tls"
$keyPath = Join-Path $tlsDir "loopback-key.pem"
$certPath = Join-Path $tlsDir "loopback-cert.pem"
New-Item -ItemType Directory -Force -Path $tlsDir | Out-Null

& $openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 7 `
  -keyout $keyPath -out $certPath `
  -subj "/CN=127.0.0.1" `
  -addext "subjectAltName=IP:127.0.0.1" `
  -addext "extendedKeyUsage=serverAuth"
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o certificado TLS local." }

$env:SMART_CRM_EXPECTED_ORIGIN = "https://127.0.0.1:8080"
python -m uvicorn app.server:create_central_app --factory --host 127.0.0.1 --port 8080 --ssl-keyfile $keyPath --ssl-certfile $certPath
```

Esse certificado autoassinado é apenas para desenvolvimento local. O aviso de confiança do navegador é esperado; não instale esse material como autoridade confiável e nunca reutilize a chave ou o certificado em produção. O diretório `.local/` é ignorado pelo Git.

Abra `https://127.0.0.1:8080/`, localize `cliente-a` ou `cliente-b` e autentique com o administrador do respectivo banco. Encerre o Uvicorn antes da limpeza. Ao encerrar o runtime local, remova o opt-in, a origem temporária e o material TLS:

```powershell
Remove-Item Env:SMART_CRM_ALLOW_INSECURE_TENANT_LOOPBACK -ErrorAction SilentlyContinue
Remove-Item Env:SMART_CRM_EXPECTED_ORIGIN -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $tlsDir -Recurse -Force
```

### Gate local de isolamento

O gate negativo cria bancos temporários únicos e verifica IDs iguais nos dois tenants, rota forjada, falha de conexão, identidade, RLS, leitura, alteração, exclusão e restauração:

```powershell
.venv\Scripts\pytest --basetemp .pytest-tmp tests/backend/test_repository_tenant_scope.py tests/backend/test_tenant_router.py tests/backend/test_fleet.py -q
```

A variável `SMART_CRM_TEST_DATABASE_URL` deve apontar somente para a instância local descartável usada pelos testes. O harness cria e remove apenas bancos com nomes aleatórios próprios; nunca aponte esse gate para produção.

### PostgreSQL 11

PostgreSQL 11 está EOL desde 09/11/2023 e não recebe correções de segurança ou bugs. O uso de PostgreSQL 17 local não elimina esse risco: a compatibilidade mínima continua sendo PostgreSQL 11 por causa do servidor existente e do pacote offline. Antes de qualquer corte, execute os testes e migrações em PostgreSQL 11 isolado, limite rede/privilégios e mantenha plano prioritário de atualização.

## Compose legado do protótipo local

O protótipo é uma demonstração funcional com dados fictícios. Ele inclui:

- Dashboard e navegação responsiva;
- listas de Leads, Contatos, Empresas e Negócios;
- criação, edição, exclusão lógica e recuperação persistidas no PostgreSQL;
- busca em todos os campos pesquisáveis e filtros configuráveis por campo, operador, responsável, período e etapa;
- filtros nomeados salvos por usuário e por módulo no banco;
- alternância entre Lista e Kanban para Leads e Negócios;
- funil canônico de Negócios configurável por Administrador, com IDs estáveis, semântica interna, Kanban, barra segmentada, transferências protegidas e ação de desfazer;
- conversão demonstrativa de Lead em Negócio;
- orçamento com cálculo de total e seleção opcional de PDF;
- automação demonstrativa de atribuição ao Faturamento;
- Dashboard filtrável nos escopos Todos, Leads e Negócios, com recálculo de indicadores, Pipeline e movimentações;
- notificações internas;
- identidade e perfil imutáveis carregados da sessão autenticada no servidor;
- API FastAPI e banco tenant como fonte exclusiva dos dados comerciais daquele cliente.

### Usar o workspace comercial

- Em Leads, Contatos, Empresas ou Negócios, clique no nome de um registro para editar seus dados no painel lateral direito.
- Use **Filtros** para combinar quantos critérios forem necessários. Valores múltiplos de um mesmo campo funcionam como alternativas; campos diferentes são combinados simultaneamente.
- Em Leads e Negócios, alterne entre **Lista** e **Kanban**. A preferência e os filtros ativos são preservados no navegador.
- Na Visão geral, use **Filtrar painel** para escolher o escopo e analisar um responsável, uma equipe, um período ou uma etapa específica.
- Mudanças para Faturando, etapas de encerramento, descarte ou conversão pedem confirmação ou motivo. Transições de etapa concluídas exibem **Desfazer** por alguns segundos.

### Iniciar

Pré-requisito: Docker Desktop em execução.

```powershell
docker compose up --build -d
```

Abra [http://localhost:8080](http://localhost:8080).

Para usar outra porta local:

```powershell
$env:SMART_CRM_PORT=8081
docker compose up --build -d
```

### Verificar

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8080/health
```

Os serviços `crm` e `postgres` devem aparecer como `healthy`, e a rota de saúde deve retornar `{"status":"ok","database":"ok"}`. Se o banco estiver indisponível, a mesma rota retorna HTTP 503 com `{"status":"degraded","database":"unavailable"}`; a página estática continua acessível.

### PostgreSQL local de testes

O Compose inicia um PostgreSQL exclusivo para desenvolvimento. Por padrão, ele fica disponível somente nesta máquina em `127.0.0.1:5432`, com banco `smartcrm_test`, usuário `smartcrm` e senha local `smartcrm_local_dev`. A API recebe a URL de conexão apenas no container; ela não é enviada ao código do navegador.

Esses valores podem ser alterados antes de iniciar os serviços:

```powershell
$env:SMART_CRM_DB_NAME="smartcrm_test"
$env:SMART_CRM_DB_USER="smartcrm"
$env:SMART_CRM_DB_PASSWORD="outra_senha_local"
$env:SMART_CRM_DB_PORT="55432"
docker compose up --build -d
```

Para abrir o console SQL ou acompanhar o banco:

```powershell
docker compose exec -T postgres psql -U smartcrm -d smartcrm_test
docker compose logs -f postgres
```

Somente este Compose legado aplica a linhagem tenant automaticamente antes do Uvicorn; ele não representa o runtime central multiempresa e não deve ser usado para validar cutover. Para conferir a revisão e inspecionar o workspace legado sem alterar dados:

```powershell
docker compose exec -T crm alembic current
docker compose exec -T postgres psql -X -U smartcrm -d smartcrm_test -c "SELECT version, initialized_at FROM workspaces WHERE id = 'default';"
docker compose exec -T postgres psql -X -U smartcrm -d smartcrm_test -c "SELECT (SELECT count(*) FROM leads WHERE deleted_at IS NULL) AS leads, (SELECT count(*) FROM contacts WHERE deleted_at IS NULL) AS contacts, (SELECT count(*) FROM companies WHERE deleted_at IS NULL) AS companies, (SELECT count(*) FROM deals WHERE deleted_at IS NULL) AS deals;"
```

No fluxo multiempresa, o banco tenant e o primeiro administrador são provisionados explicitamente antes do login. Falha de banco nunca carrega massa fictícia, cache comercial ou dados de outro tenant.

O `localStorage` mantém somente preferências visuais separadas por tenant e usuário; não mantém identidade, perfil confiável, token de sessão ou snapshot comercial. Falha de carga/gravação bloqueia a operação sem fallback.

O volume nomeado `postgres_data` preserva dados após reinícios, recriações do container e `docker compose down`. Antes de qualquer limpeza intencional, gere uma cópia:

```powershell
docker compose exec -T postgres pg_dump -U smartcrm -d smartcrm_test --format=custom --file=/tmp/smartcrm_test.dump
docker compose cp postgres:/tmp/smartcrm_test.dump .\smartcrm_test.dump
```

`docker compose down -v` apaga definitivamente o banco local de testes. Esse comando **nunca faz parte da validação normal**; use-o somente quando a intenção explícita for remover o volume e reiniciar com um banco vazio.

Para instalar as dependências de desenvolvimento e executar o gate completo:

```powershell
python -m pip install -e ".[dev]"
pnpm install
python -m compileall -q app
docker compose config --quiet
python -m pytest tests/backend -q
pnpm test
python scripts/verify_demo.py
```

O verificador Compose constrói os serviços, confere o head Alembic e as contagens API/SQL, realiza uma mutação versionada, recria o CRM, reinicia e interrompe temporariamente o PostgreSQL, confirma degradação/recuperação e preserva o volume e a tabela técnica `_smartcrm_test_probe`.

### Restaurar os dados

Use o botão **Restaurar demo** na Visão geral. A ação substitui a massa comercial no PostgreSQL em uma transação e incrementa a versão do workspace; ela não remove o schema nem o volume. Registros excluídos logicamente podem ser consultados e recuperados pelo Administrador em **Recuperar excluídos**.

### Logs e encerramento

```powershell
docker compose logs -f crm
docker compose down
```

## Limitações importantes

O Compose legado serve apenas à regressão local de interface e um banco; não representa a topologia multiempresa segura. A porta publicada pode ficar acessível na rede local conforme a configuração do host, portanto não a exponha à internet. Ainda não há integração com WordPress, migração direta/sincronização com o Bitrix24, paginação para alto volume ou armazenamento binário de PDFs. Dados reais dependem do cutover autorizado, backups, migrações explícitas, UAT e controles operacionais do runbook.

O escopo produtivo permanece documentado em [.specs/features/crm-mvp/spec.md](.specs/features/crm-mvp/spec.md). O recorte inicial da demonstração está em [.specs/features/ui-prototype/spec.md](.specs/features/ui-prototype/spec.md), e a evolução deste workspace está em [.specs/features/ui-crm-workspace/spec.md](.specs/features/ui-crm-workspace/spec.md).
