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

### AD-005
- **Decision**: O Smart CRM usará uma aplicação central com plano de controle central e um banco PostgreSQL de negócio exclusivo por empresa, selecionado somente a partir do tenant gravado na sessão opaca do servidor.
- **Reason**: O usuário escolheu isolamento físico dos dados por empresa e quer preservar uma única aplicação e URLs por caminho para facilitar a evolução e a escalabilidade futuras.
- **Trade-off**: Migrações, credenciais, pools, saúde, backup e recuperação passam a ser operados como uma frota de bancos; o provisionamento entre o plano de controle e o banco da empresa exige estado idempotente em vez de uma única transação SQL.
- **Scope**: Autenticação, sessões, roteamento de dados, persistência de negócio, provisionamento, migrações, operação e testes de isolamento multiempresa.
- **Date**: 2026-09-14
- **Status**: active

### AD-006
- **Decision**: O primeiro corte multiempresa no Windows Server usará uma release versionada lado a lado, manterá o database existente `smartcrm` como banco de negócio do tenant `brbots`, criará `smartcrm_control` somente para o plano de controle e executará o serviço e a proteção DPAPI sob a conta dedicada `SmartCRMService`.
- **Reason**: Preservar os dados atuais sem cópia comercial, permitir rollback para a release anterior e vincular os segredos à mesma identidade que executa a aplicação.
- **Trade-off**: O corte exige backup verificado, credenciais inseridas interativamente, duas cadeias Alembic confirmadas e uma janela operacional; a release não pode ser sobrescrita nem atualizada por `git pull`.
- **Scope**: Pacote offline, startup central, migrações control/tenant, onboarding inicial da BRBots, rollback e operação do serviço Windows.
- **Date**: 2026-09-21
- **Status**: active

### AD-007
- **Decision**: O PostgreSQL 11 do primeiro corte é compartilhado com `DW_CMS` e `DW_PRODUTOS`, que mantêm acesso remoto. O listener global não será restringido; regras `pg_hba.conf` anteriores às regras amplas permitirão `smartcrm` e `smartcrm_control` somente por loopback e rejeitarão acesso remoto a esses dois databases.
- **Reason**: Restringir globalmente o serviço a `127.0.0.1` interromperia sistemas existentes, enquanto regras por database preservam a operação externa e mantêm os bancos do Smart CRM locais.
- **Trade-off**: A instância continua compartilhada e exige ordem de regras HBA, backup, reload e UAT remoto verificáveis; isolamento por instância fica adiado.
- **Scope**: Instalador Windows, preflight de migração, `pg_hba.conf`, runbook e UAT do primeiro corte; nenhum schema ou dado de `DW_CMS`/`DW_PRODUTOS` entra no escopo.
- **Date**: 2026-09-21
- **Status**: active

## Handoff

- **Feature**: Multiempresa Seguro / `.specs/features/secure-multitenancy`
- **Phase / Task**: Execute concluído; T1-T45 e Fresh Verifier completos
- **Completed**: validação independente T45 PASS com 56/56 critérios, 586 backend, 93 browser, compatibilidade 27/27, pacote 19/19, runbook 41/41, Apache 32/32 e sensor 3/3; no servidor, release 18f5a7d1 copiada/validada/extraída lado a lado, conta `SmartCRMService` criada com batch logon e backups de `server.env`/tarefa salvos; aplicação atual permanece ativa
- **In-progress** (file:line): none
- **Next step**: gerar novo ZIP do commit verificado e retomar o servidor com backup/HBA/preflight, sem tocar em `DW_CMS`/`DW_PRODUTOS`
- **Blockers**: pacote 18f5a7d1 não deve continuar porque rejeita corretamente o listener compartilhado; nenhum banco foi migrado e nenhuma tarefa foi trocada
- **Uncommitted files**: `.pytest-tmp/`, `.specs/features/crm-mvp/tasks.md`, `.venv/`, `smart_crm_demo.egg-info/` (untracked preexistentes, preservados)
- **Branch**: main
