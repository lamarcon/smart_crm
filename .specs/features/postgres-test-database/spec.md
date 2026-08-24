# Banco PostgreSQL local para testes

## Problem Statement

O ambiente Docker executa somente a interface demonstrativa. A equipe precisa de um PostgreSQL local e reproduzível para iniciar testes de persistência sem alterar os dados atuais do navegador.

## Goals

- [x] Disponibilizar PostgreSQL saudável no mesmo Docker Compose do Smart CRM.
- [x] Preservar os dados do banco entre reinicializações do contêiner.
- [x] Manter o protótipo atual independente do banco nesta etapa.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Migrar o `localStorage` para PostgreSQL | Exige API, modelo de dados e estratégia de migração próprios. |
| Autenticação e autorização reais | Não fazem parte da inicialização do banco de testes. |
| Credenciais ou implantação de produção | Os valores desta entrega são exclusivamente locais. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Versão do banco | `postgres:17-alpine` | Imagem oficial compacta e versão estável para o ambiente de testes. | y |
| Banco e usuário | `smartcrm_test` e `smartcrm` | Nomes explícitos evitam confusão com produção. | y |
| Acesso pelo host | `127.0.0.1:5432`, configurável | Permite ferramentas locais sem expor o banco na rede. | y |
| Persistência | Volume nomeado `postgres_data` | Recriar o contêiner não deve apagar os testes locais. | y |
| Integração do CRM | Adiada; interface continua no `localStorage` | Evita uma migração implícita e mantém o escopo reversível. | y |

**Open questions:** none - all resolved or logged above.

---

## User Stories

### P1: Executar PostgreSQL no ambiente local ⭐ MVP

**User Story**: Como desenvolvedor do Smart CRM, quero um PostgreSQL local no Docker para testar persistência e consultas antes da integração com a aplicação.

**Why P1**: O banco é a dependência inicial para evoluir do protótipo local para persistência no servidor.

**Acceptance Criteria**:

1. WHEN `docker compose up -d` concluir THEN o sistema SHALL iniciar os serviços `crm` e `postgres` com estado saudável.
2. WHILE o serviço `postgres` estiver ativo, o sistema SHALL disponibilizar o banco `smartcrm_test` para o usuário `smartcrm`.
3. WHILE a porta padrão estiver configurada, o sistema SHALL publicar o PostgreSQL somente em `127.0.0.1:5432`.
4. WHERE as variáveis `SMART_CRM_DB_NAME`, `SMART_CRM_DB_USER`, `SMART_CRM_DB_PASSWORD` ou `SMART_CRM_DB_PORT` estiverem definidas, o sistema SHALL substituir os respectivos valores locais padrão.
5. WHEN um dado de prova for criado e o serviço `postgres` for reiniciado THEN o sistema SHALL preservar exatamente uma linha de prova no volume `postgres_data`.
6. WHILE esta entrega estiver em uso, o sistema SHALL manter o estado funcional do CRM no `localStorage` sem depender do PostgreSQL.

**Independent Test**: Subir o Compose, consultar `current_database()` e `current_user`, criar uma linha de prova, reiniciar apenas o PostgreSQL e confirmar a mesma linha.

---

## Edge Cases

- WHEN o Compose for executado novamente com o volume existente THEN o sistema SHALL manter a inicialização idempotente e a linha de prova única.
- IF o PostgreSQL não atingir o estado saudável em 30 segundos THEN o gate SHALL falhar com uma mensagem de diagnóstico.
- WHEN `SMART_CRM_DB_PORT=55432` for usado na renderização do Compose THEN o sistema SHALL publicar somente `127.0.0.1:55432`.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| PGTEST-01 | P1: Serviço PostgreSQL | Execute | Verified |
| PGTEST-02 | P1: Persistência local | Execute | Verified |
| PGTEST-03 | P1: Configuração segura | Execute | Verified |

**Coverage:** 3 total, 3 mapped to the execution plan, 0 unmapped.

---

## Success Criteria

- [x] Os dois serviços aparecem saudáveis no Docker Compose.
- [x] A consulta retorna exatamente `smartcrm_test|smartcrm`.
- [x] A linha de prova permanece única depois do reinício do PostgreSQL.
- [x] A regressão existente do Smart CRM permanece verde.
- [x] A validação independente termina em PASS.
