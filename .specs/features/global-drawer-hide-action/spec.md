# Ocultação global pelo card

## Problem Statement

O botão `×` ao lado de um campo personalizado atualmente oculta o campo somente no cadastro aberto. O Administrador precisa usar essa ação como um atalho para ocultar o campo em todos os cards do módulo, sem apagar valores.

## Goals

- [x] Fazer o `×` ocultar o campo personalizado no módulo inteiro imediatamente.
- [x] Preservar valores e escolhas individuais de visibilidade.
- [x] Restringir a ação global ao Administrador e permitir reversão em `Gerenciar campos`.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Excluir campos ou valores | A ação é reversível e apenas visual. |
| Alterar busca e filtros | Campos ocultos continuam pesquisáveis e filtráveis como hoje. |
| Remover compatibilidade com visibilidade individual existente | Estados já gravados devem continuar válidos ao reexibir o campo. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Momento da persistência | O clique no `×` salva a ocultação imediatamente | O usuário pediu que o próprio `×` oculte para todos os cards. | y |
| Fronteira de autorização | Apenas Administradores veem e executam o `×` | A ação muda a visualização de todo o módulo. | y |
| Reversão | O Administrador reativa o campo em `Gerenciar campos` | Reaproveita o controle geral já existente. | y |
| Confirmação adicional | Não exibir confirmação antes de ocultar | A ação é reversível e não destrói dados. | n |
| Aviso visual | Exibir `Campo <nome> ocultado em todos os cadastros.` | Torna explícito o alcance global da ação. | n |

**Open questions:** none - all resolved or logged above.

---

## User Stories

### P1: Ocultar um campo em todos os cards pelo `×` ⭐ MVP

**User Story**: Como Administrador, quero usar o `×` do campo personalizado para ocultá-lo em todos os cards do módulo sem perder dados.

**Why P1**: O comportamento atual parece global visualmente, mas altera apenas um cadastro.

**Acceptance Criteria**:

1. WHILE o usuário atual for Administrador, o sistema SHALL exibir no campo personalizado um `×` com nome acessível `Ocultar campo em todos os cadastros`.
2. WHEN o Administrador clicar no `×` de um campo personalizado THEN o sistema SHALL adicionar a chave exatamente uma vez a `hiddenCustomFieldKeys` do módulo e ocultar o campo imediatamente de todos os cards e do seletor de adição.
3. WHILE o campo estiver oculto globalmente, o sistema SHALL preservar os valores e as listas `visibleCustomFieldKeys` de todos os registros sem alteração.
4. WHEN o Administrador reativar o campo em `Gerenciar campos` THEN o sistema SHALL restaurá-lo conforme a visibilidade individual anterior de cada registro.
5. WHILE o usuário atual não for Administrador, o sistema SHALL omitir o `×` e rejeitar uma chamada direta sem alterar `hiddenCustomFieldKeys`.
6. WHEN a ocultação global for concluída THEN o sistema SHALL exibir `Campo <nome> ocultado em todos os cadastros.`.

**Independent Test**: Ocultar um campo pelo `×` em um Negócio, confirmar a ausência em outro Negócio e a preservação dos dois estados, reativá-lo no gerenciador e confirmar a restauração dos valores.

---

## Edge Cases

- WHEN o último campo personalizado disponível for ocultado pelo `×` THEN o sistema SHALL ocultar a aba `Campos adicionais` e ativar a aba `Informações`.
- IF a chave solicitada não existir no registro aberto THEN o sistema SHALL rejeitar a ação sem alterar a configuração.
- WHEN a mesma chave já estiver oculta globalmente THEN o sistema SHALL manter apenas uma ocorrência em `hiddenCustomFieldKeys`.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| XHIDE-01 | P1: Ocultação imediata e global | Execute | Verified |
| XHIDE-02 | P1: Preservação e reversão | Execute | Verified |
| XHIDE-03 | P1: Autorização e bordas | Execute | Verified |

**Coverage:** 3 total, 3 mapped to the implicit execution steps, 0 unmapped.

---

## Success Criteria

- [x] Um clique no `×` remove o campo de todos os cards do módulo sem salvar o cadastro.
- [x] Valores e visibilidades individuais permanecem idênticos.
- [x] Não Administradores não veem nem conseguem executar a ação.
- [x] A regressão completa e a validação independente terminam em PASS.
