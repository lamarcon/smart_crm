# Smart CRM

CRM em desenvolvimento para substituir o uso comercial atual do Bitrix24. O repositório contém as especificações do MVP de produção e um protótipo local navegável para validação antecipada do layout e dos fluxos.

## Protótipo local

O protótipo é uma demonstração funcional com dados fictícios. Ele inclui:

- Dashboard e navegação responsiva;
- listas de Leads, Contatos, Empresas e Negócios;
- criação, edição, exclusão lógica e recuperação persistidas no PostgreSQL;
- busca em todos os campos pesquisáveis e filtros configuráveis por campo, operador, responsável, período e etapa;
- filtros nomeados salvos por usuário e por módulo no banco;
- alternância entre Lista e Kanban para Leads e Negócios;
- Pipeline fixa com barra de etapas segmentada, confirmações para transições protegidas e ação de desfazer;
- conversão demonstrativa de Lead em Negócio;
- orçamento com cálculo de total e seleção opcional de PDF;
- automação demonstrativa de atribuição ao Faturamento;
- Dashboard filtrável nos escopos Todos, Leads e Negócios, com recálculo de indicadores, Pipeline e movimentações;
- notificações internas;
- seletor de perfil para simular Administrador, Gestor, Vendedor e Assistente;
- API FastAPI e PostgreSQL local como fonte principal do workspace comercial.

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

As migrações Alembic são aplicadas automaticamente antes de o Uvicorn iniciar. Para conferir a revisão e inspecionar o workspace sem alterar dados:

```powershell
docker compose exec -T crm alembic current
docker compose exec -T postgres psql -X -U smartcrm -d smartcrm_test -c "SELECT version, initialized_at FROM workspaces WHERE id = 'default';"
docker compose exec -T postgres psql -X -U smartcrm -d smartcrm_test -c "SELECT (SELECT count(*) FROM leads WHERE deleted_at IS NULL) AS leads, (SELECT count(*) FROM contacts WHERE deleted_at IS NULL) AS contacts, (SELECT count(*) FROM companies WHERE deleted_at IS NULL) AS companies, (SELECT count(*) FROM deals WHERE deleted_at IS NULL) AS deals;"
```

No primeiro acesso a um banco vazio, o perfil **Administrador** recebe uma confirmação única antes da migração da massa fictícia ou do cache legado. O diálogo mostra as contagens de usuários, Leads, Contatos, Empresas, Negócios, orçamentos, notificações e campos personalizados; nada é enviado antes da confirmação. Depois que o workspace existe, o estado do PostgreSQL prevalece sobre qualquer cópia comercial alterada no navegador.

O `localStorage` mantém somente o último snapshot confirmado e estados transitórios, como busca, perfil selecionado, drawer e filtros ainda não salvos. Se a carga falhar, a interface usa esse cache apenas para leitura e mostra `Banco indisponível. Alterações bloqueadas.`. Se uma gravação falhar, ela restaura o estado confirmado e mostra `Não foi possível salvar no banco.`.

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

Esta versão serve apenas para desenvolvimento e validação local. Embora o workspace comercial já seja persistido no PostgreSQL, o seletor de perfil não é autenticação e a API não implementa autorização real no servidor. A porta web publicada pelo Docker pode ficar acessível na rede local conforme a configuração do host; não exponha este Compose à internet. Ainda não há integração com WordPress, migração direta/sincronização com o Bitrix24, paginação para alto volume, auditoria produtiva ou armazenamento binário de PDFs. Não devem ser inseridos dados pessoais ou comerciais reais.

O escopo produtivo permanece documentado em [.specs/features/crm-mvp/spec.md](.specs/features/crm-mvp/spec.md). O recorte inicial da demonstração está em [.specs/features/ui-prototype/spec.md](.specs/features/ui-prototype/spec.md), e a evolução deste workspace está em [.specs/features/ui-crm-workspace/spec.md](.specs/features/ui-crm-workspace/spec.md).
