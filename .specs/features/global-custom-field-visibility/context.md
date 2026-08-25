# Ocultação geral de campos adicionais — Contexto

**Gathered:** 2026-08-25
**Spec:** `.specs/features/global-custom-field-visibility/spec.md`
**Status:** Implemented and verified

---

## Feature Boundary

Adicionar ocultação geral de campos adicionais por módulo sem remover a ocultação individual existente nem apagar dados.

---

## Implementation Decisions

### Composição das duas visibilidades

- A configuração geral funciona como uma camada sobre a escolha de cada cadastro.
- Ocultar globalmente não altera `visibleCustomFieldKeys` nem valores.
- Ao reexibir globalmente, um campo individualmente oculto continua oculto naquele cadastro.

### Interface administrativa

- `Gerenciar campos` mostra checkboxes separados para campos padrão e campos adicionais.
- A mesma ação `Salvar visualização` persiste as duas listas.
- Somente Administradores podem alterar a preferência geral.

### Persistência local

- Cada módulo recebe `hiddenCustomFieldKeys`, normalizado como `[]` em estados antigos.
- Busca e filtros permanecem fora desta mudança para manter o mesmo escopo da ocultação global dos campos padrão.

---

## Deferred Ideas

- Configuração compartilhada pelo backend entre usuários e navegadores.
- Política separada para remover campos ocultos de busca e filtros.
