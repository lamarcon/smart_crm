# STATE

## Decisions

### AD-001
- **Decision**: O Smart CRM substituirá integralmente o Bitrix24, incluindo a captação direta de Leads enviados pelos formulários do WordPress.
- **Reason**: O cliente deixará de usar o Bitrix24 e concentrará no novo CRM os módulos, dados, pipelines, automações e integrações atualmente utilizados.
- **Trade-off**: Não haverá coexistência permanente nem dependência operacional do Bitrix24; a migração deverá preservar os dados e comportamentos necessários antes da desativação.
- **Scope**: Todos os módulos do CRM, integração com WordPress, migração de dados, pipelines e automações.
- **Date**: 2026-08-17
- **Status**: active

### AD-002
- **Decision**: A migração do Bitrix24 para o Smart CRM abrangerá todas as informações que puderem ser extraídas e importadas de forma tecnicamente viável.
- **Reason**: O novo CRM substituirá integralmente o sistema atual e precisa preservar o máximo possível do contexto operacional e histórico do cliente.
- **Trade-off**: A migração será mais extensa e exigirá inventário, mapeamento, validação e reconciliação; dados indisponíveis ou não exportáveis deverão ser documentados como exceções, em vez de serem considerados migrados.
- **Scope**: Leads, contatos, empresas, tarefas, projetos, pipelines, campos personalizados, automações, atividades, vínculos, arquivos e demais dados acessíveis no Bitrix24.
- **Date**: 2026-08-17
- **Status**: active

### AD-003
- **Decision**: A API local do Smart CRM usará FastAPI, SQLAlchemy 2 com o driver Psycopg 3 e migrações versionadas pelo Alembic; o PostgreSQL será a fonte principal após a inicialização do workspace.
- **Reason**: A persistência exige validação estruturada, transações explícitas, controle de concorrência e evolução reproduzível do esquema sem substituir a interface já validada.
- **Trade-off**: O serviço deixa de ser livre de dependências Python e passa a exigir dependências fixadas, migrações e testes de integração com banco.
- **Scope**: Backend Python, acesso ao PostgreSQL, migrações, saúde do serviço e integrações futuras que reutilizem a API do CRM.
- **Date**: 2026-08-26
- **Status**: active

## Handoff

- **Feature**: Smart CRM MVP produtivo / `.specs/features/crm-mvp`
- **Phase / Task**: Specify reconciliado com a base local; escolha da arquitetura produtiva pendente
- **Completed**: Base local e persistência validadas; escopo produtivo especificado; baseline reconciliada
- **In-progress** (file:line): none
- **Next step**: Confirmar a abordagem arquitetural e produzir `design.md`, depois `tasks.md`.
- **Blockers**: decisão arquitetural do usuário antes de detalhar componentes
- **Uncommitted files**: README.md, .specs/STATE.md, .specs/features/crm-mvp/context.md, .specs/features/crm-mvp/spec.md
- **Branch**: main
