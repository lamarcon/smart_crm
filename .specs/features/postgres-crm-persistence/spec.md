# Persistência do Smart CRM no PostgreSQL

## Problem Statement

O PostgreSQL local está saudável, mas contém apenas uma tabela técnica. Todos os cadastros e configurações comerciais ainda ficam no `localStorage`, portanto não são compartilhados, auditáveis nem duráveis fora do navegador. Esta entrega conecta o ambiente de teste ao banco por uma API Python e torna o PostgreSQL a fonte principal dos dados atuais.

## Goals

- [ ] Persistir em tabelas normalizadas os dados comerciais e configurações duráveis existentes no protótipo.
- [ ] Migrar de forma controlada e atômica o estado atual do navegador quando o banco estiver vazio.
- [ ] Carregar e salvar alterações pela API, com controle de concorrência e sem confirmações falsas.
- [ ] Preservar os fluxos, campos personalizados, vínculos e testes atuais da interface.
- [ ] Comprovar persistência após recarga, recriação do container da aplicação e reinício do PostgreSQL.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Autenticação e autorização reais no servidor | Esta integração continua local e usa os perfis demonstrativos; segurança produtiva será uma entrega própria. |
| API paginada otimizada para os volumes completos do Bitrix24 | A primeira integração persiste a massa do ambiente de teste; escala produtiva será validada em endpoints granulares posteriores. |
| Integração WordPress e migração direta do Bitrix24 | Dependem da base persistente, mas possuem regras e reconciliação próprias. |
| Armazenamento binário de PDFs | O protótipo continuará persistindo apenas os metadados atuais do anexo. |
| Auditoria produtiva completa e histórico campo a campo | Esta entrega registra versões e timestamps; o histórico de negócio será aprofundado depois. |
| Implantação e credenciais de produção | O Compose e as credenciais permanecem exclusivos do ambiente local. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Estrutura do banco | Tabelas normalizadas para usuários, equipes, módulos comerciais, vínculos, campos personalizados, orçamentos, notificações e preferências duráveis | Evita transformar o PostgreSQL em apenas outro `localStorage`. | y |
| Primeiro carregamento com banco vazio | Exibir ao Administrador uma confirmação com contagens antes de enviar o estado atual do navegador | Evita sobrescrever o banco ou importar dados sem conhecimento do usuário. | n |
| Primeiro carregamento com banco preenchido | Ignorar o estado comercial local e carregar a versão do servidor | Garante uma única fonte principal. | y |
| Estado mantido somente no navegador | Busca digitada, drawer aberto, modal aberto e filtros temporários | São estados transitórios de interface, não dados compartilhados. | n |
| Preferências duráveis | Presets nomeados, visualização Lista/Kanban e configuração de campos ficam no banco por usuário ou módulo | Essas escolhas já sobrevivem à recarga e precisam acompanhar o usuário. | n |
| Concorrência | Cada workspace possui versão inteira; gravação com versão antiga retorna HTTP 409 sem alterações | Impede sobrescrita silenciosa nesta primeira API agregada. | y |
| Falha do banco no carregamento | Exibir o último cache em modo somente leitura com o aviso `Banco indisponível. Alterações bloqueadas.` | Mantém consulta local sem fingir persistência. | y |
| Falha do banco durante uma alteração | Reverter a alteração visual e exibir `Não foi possível salvar no banco.` | O usuário não pode receber confirmação de algo não persistido. | y |
| Exclusão | Marcar `deleted_at` e omitir o registro das listas ativas | Mantém dados recuperáveis e prepara a exclusão lógica do MVP. | n |
| Limite da migração inicial | Rejeitar payload acima de 25 MB com HTTP 413 | Protege o servidor local; a massa atual de teste é muito menor. | n |
| Escopo de segurança | API acessível somente no ambiente local, sem afirmar fronteira de autorização no servidor | O seletor de perfil atual não é autenticação. | y |

**Open questions:** none - all resolved or logged above.

---

## Implicit-Requirement Dimensions

| Dimension | Resolution |
| --------- | ---------- |
| Input validation & bounds | Validar o formato completo da migração e limitar o corpo a 25 MB. |
| Failure / partial-failure states | Toda migração e gravação ocorre em transação; qualquer falha restaura banco e interface ao estado anterior. |
| Idempotency / retry / duplicate handling | Banco preenchido rejeita nova migração; IDs de cada entidade permanecem únicos. |
| Auth boundaries & rate limits | Autenticação e rate limit são N/A nesta entrega local; a interface só oferece a migração ao Administrador simulado. |
| Concurrency / ordering | Controle otimista por versão inteira do workspace, com conflito HTTP 409. |
| Data lifecycle / expiry | Exclusão lógica sem expiração automática. |
| Observability | Saúde distingue aplicação e banco; erros recebem identificador e log no servidor. |
| External-dependency failure | Banco indisponível produz HTTP 503 e interface somente leitura. |
| State-transition integrity | O estado completo é validado e persistido atomicamente antes de confirmar qualquer fluxo existente. |

---

## User Stories

### P1: Preparar e preencher o banco normalizado ⭐ MVP

**User Story**: Como Administrador do ambiente de teste, quero migrar os dados atuais para tabelas reais para verificar o conteúdo diretamente no PostgreSQL.

**Why P1**: Sem esquema e migração, o banco saudável não prova persistência do CRM.

**Acceptance Criteria**:

1. [DBP-01] WHEN o serviço iniciar em um banco sem o esquema atual THEN o sistema SHALL aplicar migrações versionadas e criar tabelas normalizadas para usuários, equipes, Leads, Contatos, Empresas, Negócios, Assistentes, vínculos, campos personalizados, valores personalizados, orçamentos, notificações, preferências e controle do workspace.
2. [DBP-02] WHEN o banco estiver vazio e o Administrador confirmar a migração inicial THEN o sistema SHALL validar e persistir o estado comercial do navegador em uma única transação.
3. [DBP-03] WHEN a migração inicial terminar THEN o sistema SHALL retornar HTTP 201 com as contagens exatas de usuários, Leads, Contatos, Empresas, Negócios, orçamentos, notificações e campos personalizados persistidos.
4. [DBP-04] IF qualquer registro, vínculo ou campo da migração inicial for inválido THEN o sistema SHALL rejeitar o payload inteiro com HTTP 422 e manter todas as contagens comerciais anteriores inalteradas.
5. [DBP-05] IF o banco já contiver um workspace inicializado THEN o sistema SHALL rejeitar nova migração inicial com HTTP 409 e não alterar nenhum dado.
6. [DBP-06] IF o corpo da migração exceder 25 MB THEN o sistema SHALL retornar HTTP 413 sem iniciar uma transação comercial.

**Independent Test**: Migrar uma massa com todos os módulos, consultar tabelas e contagens, repetir a migração e enviar um payload inválido e outro acima do limite.

---

### P1: Usar o PostgreSQL como fonte principal ⭐ MVP

**User Story**: Como usuário do CRM, quero que cada alteração confirmada sobreviva fora do navegador e seja vista após uma nova sessão.

**Why P1**: Persistência real exige leitura e escrita no servidor, não uma cópia ocasional do `localStorage`.

**Acceptance Criteria**:

1. [DBP-07] WHEN a interface abrir com um workspace inicializado THEN o sistema SHALL carregar o estado comercial e sua versão a partir da API antes de liberar alterações.
2. [DBP-08] WHEN uma alteração válida for salva com a versão atual THEN o sistema SHALL persistir todos os registros afetados atomicamente e incrementar a versão do workspace em exatamente um.
3. [DBP-09] WHEN a API confirmar uma alteração THEN o sistema SHALL exibir a confirmação visual somente depois de receber a nova versão persistida.
4. [DBP-10] IF uma alteração usar uma versão anterior à atual THEN o sistema SHALL retornar HTTP 409 com a versão atual e manter o banco inalterado.
5. [DBP-11] IF qualquer parte de uma alteração falhar THEN o sistema SHALL desfazer toda a transação e retornar um identificador de erro sem dados parciais.
6. [DBP-12] WHEN um registro for excluído pela interface THEN o sistema SHALL preencher `deleted_at`, ocultá-lo das listas ativas e preservar seus vínculos no banco.
7. [DBP-13] WHEN um registro excluído for recuperado THEN o sistema SHALL limpar `deleted_at` e restaurar os vínculos anteriores.

**Independent Test**: Editar um registro, recarregar em novo contexto, provocar conflito de versão, forçar falha intermediária, excluir, recuperar e consultar o banco após cada ação.

---

### P1: Preservar todos os dados e fluxos atuais ⭐ MVP

**User Story**: Como avaliador, quero continuar usando o CRM atual sem perder campos, vínculos ou configurações ao trocar a fonte de dados.

**Why P1**: A integração não pode reimplementar nem reduzir o protótipo já validado.

**Acceptance Criteria**:

1. [DBP-14] WHEN o estado for migrado e recarregado THEN o sistema SHALL preservar por valor usuários, Leads, Contatos, Empresas, Negócios, Assistentes, orçamentos, notificações, campos personalizados e seus vínculos.
2. [DBP-15] WHEN preferências duráveis forem alteradas THEN o sistema SHALL persistir presets nomeados, visualização Lista/Kanban e configuração geral de campos no escopo correto.
3. [DBP-16] WHILE o PostgreSQL for a fonte principal, o sistema SHALL manter no navegador somente o cache da última versão e os estados transitórios de interface.
4. [DBP-17] WHEN o usuário executar criação, edição, conversão de Lead, mudança de etapa, orçamento, importação CSV ou personalização de campos THEN o sistema SHALL preservar o resultado após recarga e em outro contexto de navegador.
5. [DBP-18] WHEN o serviço da aplicação for recriado ou o PostgreSQL for reiniciado THEN o sistema SHALL apresentar as mesmas contagens e valores persistidos antes do reinício.

**Independent Test**: Executar os fluxos críticos existentes, abrir um segundo contexto, reiniciar os serviços e comparar os dados e configurações com os valores anteriores.

---

### P1: Tornar falhas de persistência visíveis ⭐ MVP

**User Story**: Como usuário, quero saber quando o banco está indisponível para não acreditar que uma alteração foi salva.

**Why P1**: O maior risco da transição é confirmar localmente uma gravação que não existe no servidor.

**Acceptance Criteria**:

1. [DBP-19] WHILE o PostgreSQL estiver acessível, a rota `/health` SHALL retornar HTTP 200 com `status: ok` e `database: ok`.
2. [DBP-20] IF o PostgreSQL estiver indisponível THEN a rota `/health` SHALL retornar HTTP 503 com `status: degraded` e `database: unavailable`.
3. [DBP-21] IF a carga inicial falhar e existir cache válido THEN a interface SHALL exibir o cache em modo somente leitura com `Banco indisponível. Alterações bloqueadas.`.
4. [DBP-22] IF uma gravação falhar THEN a interface SHALL restaurar o último estado confirmado e exibir `Não foi possível salvar no banco.`.
5. [DBP-23] WHEN a API retornar um erro de persistência THEN o sistema SHALL registrar no servidor um identificador de erro também devolvido ao cliente.

**Independent Test**: Interromper o PostgreSQL antes da carga e durante uma edição, comparar interface e banco e correlacionar o identificador retornado com o log.

---

## Edge Cases

- WHEN o banco estiver vazio e não houver estado local válido THEN o sistema SHALL oferecer a massa inicial fictícia para confirmação da migração.
- WHEN dois navegadores salvarem a mesma versão simultaneamente THEN o sistema SHALL aceitar somente a primeira gravação e devolver HTTP 409 à segunda.
- WHEN uma chave de campo personalizado estiver oculta globalmente THEN o sistema SHALL persistir seus valores sem torná-la visível por efeito da migração.
- WHEN um registro importado do Bitrix contiver campos adicionais vazios THEN o sistema SHALL manter as definições e os valores vazios sem descartá-los.
- IF um identificador referenciado não existir no mesmo payload ou no banco THEN o sistema SHALL rejeitar a operação com HTTP 422 e indicar o caminho inválido.
- WHEN o usuário solicitar `Restaurar demo` THEN o sistema SHALL substituir a massa comercial em uma transação, incrementar a versão em um e preservar o esquema.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| DBP-01 | P1: Banco normalizado | Execute | In progress (T1, T3-T4 complete) |
| DBP-02 | P1: Banco normalizado | Execute | In progress (T5 complete) |
| DBP-03 | P1: Banco normalizado | Execute | In progress (T5 complete) |
| DBP-04 | P1: Banco normalizado | Execute | In progress (T5 complete) |
| DBP-05 | P1: Banco normalizado | Design | Complete |
| DBP-06 | P1: Banco normalizado | Execute | In progress (T5 complete) |
| DBP-07 | P1: Fonte principal | Design | Complete |
| DBP-08 | P1: Fonte principal | Design | Complete |
| DBP-09 | P1: Fonte principal | Design | Complete |
| DBP-10 | P1: Fonte principal | Design | Complete |
| DBP-11 | P1: Fonte principal | Execute | In progress (T2 complete) |
| DBP-12 | P1: Fonte principal | Execute | In progress (T3 complete) |
| DBP-13 | P1: Fonte principal | Execute | In progress (T3 complete) |
| DBP-14 | P1: Compatibilidade | Execute | In progress (T3, T5 complete) |
| DBP-15 | P1: Compatibilidade | Execute | In progress (T3, T5 complete) |
| DBP-16 | P1: Compatibilidade | Design | Complete |
| DBP-17 | P1: Compatibilidade | Design | Complete |
| DBP-18 | P1: Compatibilidade | Execute | In progress (T4 complete) |
| DBP-19 | P1: Falhas visíveis | Execute | In progress (T1-T2 complete) |
| DBP-20 | P1: Falhas visíveis | Execute | In progress (T1-T2 complete) |
| DBP-21 | P1: Falhas visíveis | Design | Complete |
| DBP-22 | P1: Falhas visíveis | Design | Complete |
| DBP-23 | P1: Falhas visíveis | Execute | In progress (T2 complete) |

**Coverage:** 23 total, 0 pending design, 0 unmapped.

---

## Success Criteria

- [ ] O PostgreSQL contém tabelas comerciais e contagens conferíveis para todos os módulos persistidos.
- [ ] Uma alteração confirmada aparece em outro contexto de navegador e após reiniciar os serviços.
- [ ] Migração, atualização e restauração falham atomicamente sem dados parciais.
- [ ] Conflitos de versão e indisponibilidade do banco nunca produzem confirmação falsa.
- [ ] Todos os testes atuais permanecem verdes usando a API como fonte principal.
- [ ] A validação independente termina em PASS sem mutantes sobreviventes.
