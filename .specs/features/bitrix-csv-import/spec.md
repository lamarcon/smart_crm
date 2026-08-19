# Importação CSV do Bitrix Specification

## Problem Statement

O ambiente de teste ainda não demonstra que um registro exportado do Bitrix pode entrar no Smart CRM sem perder campos. Também não mostra o que acontece quando o mesmo arquivo é importado novamente.

## Goals

- [x] Importar uma amostra de um registro por arquivo CSV selecionado.
- [x] Preservar todos os cabeçalhos e valores da linha importada, inclusive cabeçalhos repetidos.
- [x] Demonstrar uma segunda importação sem criar duplicatas.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Importar todos os milhares de registros | O objetivo atual é validar o fluxo com uma amostra controlada. |
| Resolver vínculos ambíguos entre Contatos e Empresas | Exige regra de negócio ou API do Bitrix. |
| Sincronização automática com a API do Bitrix | O teste usa somente arquivos CSV locais. |
| Persistência em servidor ou produção | O protótipo mantém dados apenas no `localStorage` do navegador. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Chave de duplicidade | Tipo da entidade + coluna `ID` do Bitrix | O usuário pediu tratamento previsível de duplicatas e o ID externo é estável. | yes |
| Quantidade importada | Primeira linha de dados de cada arquivo selecionado | Prova o fluxo sem sobrecarregar o ambiente de teste. | yes |
| Campos desconhecidos ou repetidos | Guardar todos como lista ordenada `{nome, ocorrência, valor}` | Um objeto por nome perderia cabeçalhos duplicados. | yes |
| CSV sem ID | Não importar e informar o arquivo no resultado | Não existe chave segura para demonstrar deduplicação. | yes |
| Arquivos aceitos | CSV UTF-8 com separador `;` ou `,` | Cobre os exports reais recebidos e um formato comum. | yes |
| Falha parcial | Importar arquivos válidos e listar arquivos rejeitados | Um arquivo inválido não deve apagar registros já válidos. | yes |

**Open questions:** none - all resolved or logged above.

---

## User Stories

### P1: Importar uma amostra completa ⭐ MVP

**User Story**: As an administrator, I want to select Bitrix CSV exports so that I can prove the Smart CRM preserves their data.

**Why P1**: Esta é a prova principal solicitada para o ambiente de teste.

**Acceptance Criteria**:

1. WHEN the administrator opens the Bitrix importer THEN the system SHALL offer separate CSV inputs for Deals, Contacts, Companies, and Leads.
2. WHEN a valid selected CSV contains at least one row with an `ID` THEN the system SHALL import exactly the first data row for that entity type.
3. WHEN a row is imported THEN the system SHALL persist every header and corresponding value in original column order, including duplicate and blank headers, with a one-based occurrence number.
4. WHEN a row is imported THEN the system SHALL map these primary fields: Deal (`ID`, title, company, contact, amount, stage, responsible), Contact (`ID`, name, company, email, phone, role), Company (`ID`, name, city/region, segment, phone, owner), and Lead (`ID`, name, company, email, phone, segment, source, stage, responsible).
5. WHEN an imported record is opened THEN the system SHALL display a `Campos do Bitrix` section containing the persisted raw field list.
6. WHEN the import finishes THEN the system SHALL display exact created, updated, and rejected counts.

**Independent Test**: Selecionar CSVs sintéticos, importar e conferir no estado e no painel lateral o registro e sua lista integral de campos.

### P1: Reimportar sem duplicar ⭐ MVP

**User Story**: As an administrator, I want repeated imports to update the existing Bitrix record so that retries remain safe.

**Why P1**: O comportamento de duplicatas faz parte da prova solicitada.

**Acceptance Criteria**:

1. WHEN a row is reimported with the same entity type and Bitrix `ID` THEN the system SHALL update the existing imported record instead of appending another record.
2. WHEN an unchanged row is reimported THEN the system SHALL report zero created, one updated, and zero rejected for that file.
3. IF a selected CSV has no data row or its first data row has no Bitrix `ID` THEN the system SHALL reject that file without changing the matching collection.

**Independent Test**: Importar o mesmo arquivo duas vezes e confirmar que a coleção cresce uma única vez e que o segundo resumo informa uma atualização.

## Edge Cases

- IF a quoted CSV value contains the selected delimiter or a line break THEN the system SHALL preserve that value as one field.
- IF a selected file is not a `.csv` file THEN the system SHALL reject that file without changing any collection.
- IF no file is selected THEN the system SHALL keep the import action disabled.

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| BITRIX-01 | P1: Importar uma amostra completa | Execute | Verified |
| BITRIX-02 | P1: Reimportar sem duplicar | Execute | Verified |

**Coverage:** 2 total, 2 mapped to execution, 0 unmapped.

## Success Criteria

- [x] Uma amostra realista aparece na coleção correta com todos os campos brutos preservados.
- [x] Repetir a importação mantém uma única cópia por tipo e ID do Bitrix.
- [x] A suíte completa do protótipo passa sem regressões.
