# Ocultação global pelo card - Contexto

**Gathered:** 2026-08-25
**Spec:** `.specs/features/global-drawer-hide-action/spec.md`
**Status:** Ready for implementation

---

## Feature Boundary

O `×` exibido junto a um campo personalizado passa a ocultar esse campo em todos os cards do módulo atual. A ação não exclui dados e pode ser revertida no gerenciador de campos.

---

## Implementation Decisions

### Alcance

- O clique altera `hiddenCustomFieldKeys` do módulo, não `visibleCustomFieldKeys` do registro.
- O efeito é imediato e não depende de salvar o cadastro aberto.

### Segurança e reversão

- Apenas Administradores recebem o controle e podem executar a função.
- `Gerenciar campos` continua sendo o ponto de reativação.

### Integridade dos dados

- Valores e escolhas individuais de todos os registros permanecem intactos.
- Ao reativar, cada registro volta ao estado individual que tinha antes.

### Agent's Discretion

- Mensagem curta de sucesso e atualização imediata das abas do drawer.

### Declined / Undiscussed Gray Areas → Assumptions

- Sem diálogo de confirmação, pois a ação é reversível e não destrutiva.

---

## Specific References

- O usuário pediu explicitamente que o `×` oculte o campo para todos os cards.

---

## Deferred Ideas

None - discussion stayed within feature scope.
