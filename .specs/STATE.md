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

### AD-004
- **Decision**: A primeira implantação no Windows Server reutilizará o PostgreSQL 11 existente em `127.0.0.1:5432`, com role e database exclusivos do Smart CRM e sem reconfigurar o serviço.
- **Reason**: O usuário priorizou uma instalação manual rápida, aproveitando os runtimes já disponíveis e evitando uma nova instalação no servidor.
- **Trade-off**: PostgreSQL 11 está fora de suporte e deverá ser atualizado após a estabilização; até lá, a exposição fica restrita ao loopback e o corte depende de UAT.
- **Scope**: Implantação Windows manual, persistência de produção e procedimentos operacionais do Smart CRM até esta decisão ser supersedida.
- **Date**: 2026-09-03
- **Status**: active

## Handoff

- **Feature**: Implantação manual Windows/PostgreSQL 11 / `.specs/features/manual-windows-pg11-deployment`
- **Phase / Task**: Pacote verificado; instalação e UAT no servidor pendentes
- **Completed**: ZIP offline, SHA-256, 14 testes, 14/14 requisitos e 3/3 mutações detectadas
- **In-progress** (file:line): none
- **Next step**: Copiar o ZIP e o `.sha256` para o servidor, seguir as seções 1 a 4 de `LEIA-ME.md` e trazer a saída do gate local.
- **Blockers**: execução na máquina de destino, senha administrativa do PostgreSQL, descoberta do caminho do Apache e renovação TLS
- **Uncommitted files**: `.specs/features/crm-mvp/tasks.md` (preexistente, preservado)
- **Branch**: main
