# Orçamentos no Painel de Negócios Specification

## Problem Statement

O orçamento só pode ser iniciado pelos atalhos da Lista e do Kanban. O painel lateral do Negócio precisa reunir a edição e o histórico de orçamentos no mesmo lugar.

## Goals

- [x] Exibir a aba `Orçamentos` dentro do painel lateral de um Negócio.
- [x] Criar um orçamento para o Negócio aberto e atualizar a aba sem fechar o painel.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Armazenar ou renderizar o conteúdo binário do PDF | O protótipo guarda somente o nome do arquivo. |
| Editar ou excluir orçamento existente | Não foi solicitado nesta etapa. |

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Navegação do painel | Abas `Informações` e `Orçamentos` somente para Negócios | Mantém os outros cadastros simples. | yes |
| Atalhos existentes | Permanecem na Lista e no Kanban | O usuário pediu o botão dentro do card como opção adicional. | yes |

**Open questions:** none - all resolved or logged above.

## User Stories

### P1: Gerenciar orçamento no painel lateral ⭐ MVP

**User Story**: As a salesperson, I want to access quotes inside an open Deal so that I can work without returning to the list.

**Why P1**: É o fluxo solicitado para centralizar as ações do Negócio.

**Acceptance Criteria**:

1. WHEN a Deal drawer opens THEN the system SHALL show `Informações` and `Orçamentos` tabs.
2. WHEN the user selects `Orçamentos` THEN the system SHALL list each existing quote with description, total, state, and PDF file name or `Sem anexo`.
3. WHEN the user selects `Novo orçamento` in the drawer THEN the system SHALL open the existing quote form bound to the open Deal ID.
4. WHEN a valid quote is saved from the drawer THEN the system SHALL keep the Deal drawer open on `Orçamentos` and display the newly saved quote.
5. The system SHALL keep an `Orçamento` shortcut for every Deal in List and Kanban views.

**Independent Test**: Abrir um Negócio com orçamento, conferir a lista, adicionar outro orçamento e confirmar a atualização no painel ainda aberto.

## Edge Cases

- WHEN a Deal has no quotes THEN the system SHALL display `Nenhum orçamento cadastrado` and keep `Novo orçamento` available.

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| QUOTE-01 | P1: Gerenciar orçamento no painel lateral | Execute | Implementing |

**Coverage:** 1 total, 1 mapped to execution, 0 unmapped.

## Success Criteria

- [x] Um orçamento pode ser criado a partir do painel lateral sem perder o contexto do Negócio.
- [x] A suíte completa do protótipo passa sem regressões.
