# Always Visible Custom Fields Specification

## Problem Statement

A ficha esconde a aba Campos adicionais quando o registro não possui campos disponíveis, impedindo o usuário de acessar e compreender o estado vazio do módulo.

## Goals

- Manter a aba Campos adicionais visível em todas as fichas.
- Mostrar um estado vazio quando não houver campos adicionais disponíveis.

## Out of Scope

| Feature | Reason |
| --- | --- |
| Criar campos dentro da ficha | A criação continua na ação existente Gerenciar campos. |
| Alterar dados ou esquemas persistidos | A correção é somente de visibilidade e navegação. |

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Escopo | Lead, Contato, Empresa e Negócio | A aba pertence à ficha compartilhada pelos quatro cadastros. | y |
| Estado sem campos | Mostrar Nenhum campo adicional visível. | Reutiliza o estado vazio existente. | y |
| Último campo ocultado | Permanecer na aba e mostrar o estado vazio | Evita que a interface desloque o usuário para outra aba. | y |

**Open questions:** none - all resolved or logged above.

## User Stories

### P1: Acessar Campos adicionais

**User Story**: Como usuário do CRM, quero acessar a aba Campos adicionais em qualquer ficha para consultar os campos existentes ou entender que ainda não existem campos disponíveis.

**Acceptance Criteria**:

1. WHEN o usuário abrir uma ficha de Lead, Contato, Empresa ou Negócio THEN the system SHALL exibir a aba Campos adicionais.
2. WHEN o usuário abrir Campos adicionais sem campos visíveis THEN the system SHALL mostrar Nenhum campo adicional visível. e manter desabilitados o seletor e o botão de adição.
3. WHILE uma ficha de Negócio estiver aberta THEN the system SHALL exibir as abas Informações, Campos adicionais e Orçamentos.
4. WHEN o Administrador ocultar o último campo adicional pela ficha THEN the system SHALL manter Campos adicionais selecionada e mostrar o estado vazio.

## Edge Cases

- IF todos os campos do módulo estiverem ocultos globalmente THEN the system SHALL manter a aba Campos adicionais visível ao abrir outro registro.

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| AVCF-01 | P1: Acessar Campos adicionais | Execute | Implemented |
| AVCF-02 | P1: Acessar Campos adicionais | Execute | Implemented |
| AVCF-03 | P1: Acessar Campos adicionais | Execute | Implemented |
| AVCF-04 | P1: Acessar Campos adicionais | Execute | Implemented |
| AVCF-05 | Edge case: módulo sem campos | Execute | Implemented |

**Coverage:** 5 total, 5 mapped to inline execution, 0 unmapped.

## Success Criteria

- A aba Campos adicionais aparece nas quatro fichas.
- O estado vazio é acessível e não altera dados persistidos.
- Ocultar o último campo não fecha nem esconde a aba.