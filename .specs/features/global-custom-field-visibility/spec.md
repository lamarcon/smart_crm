# Ocultação geral de campos adicionais

## Problem Statement

Campos padrão podem ser ocultados para todo um módulo, mas campos adicionais só podem ser ocultados separadamente em cada cadastro. O Administrador precisa da mesma opção geral para organizar todos os cards sem perder valores nem remover a escolha individual.

## Goals

- [x] Permitir ocultar e reexibir um campo adicional em todos os cadastros de um módulo.
- [x] Preservar valores e escolhas individuais durante a ocultação geral.
- [x] Migrar estados locais existentes sem alterar a visibilidade atual.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Excluir campos ou valores | Ocultação deve ser reversível e não destrutiva. |
| Alterar busca e filtros | Esta entrega controla a apresentação dos cards, como a ocultação geral de campos padrão existente. |
| Compartilhar configuração entre navegadores | O protótipo ainda persiste preferências no `localStorage`. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Relação entre ocultação geral e individual | A geral prevalece enquanto ativa; ao reexibir, a escolha individual anterior volta a valer | Preserva layouts individuais sem copiar configuração para cada registro. | y |
| Local da ação geral | `Gerenciar campos` do módulo, disponível ao Administrador | Mantém a mesma fronteira dos campos padrão e criação de esquema. | y |
| Efeito sobre valores | Nenhum valor ou `visibleCustomFieldKeys` do cadastro é alterado | Garante reversibilidade sem perda de dados. | y |

**Open questions:** none - all resolved or logged above.

---

## User Stories

### P1: Controlar campos adicionais para todo o módulo ⭐ MVP

**User Story**: Como Administrador, quero ocultar um campo adicional para todos os cadastros de um módulo e poder reexibi-lo depois.

**Why P1**: A configuração atual exige repetir a ocultação em cada cadastro.

**Acceptance Criteria**:

1. WHEN o Administrador abrir `Gerenciar campos` THEN o sistema SHALL listar cada campo adicional do módulo com seu estado geral visível ou oculto.
2. WHEN o Administrador desmarcar um campo adicional e salvar THEN o sistema SHALL ocultá-lo de todos os cards e do seletor `Campo adicional para adicionar` do módulo.
3. WHILE um campo adicional estiver oculto de forma geral, o sistema SHALL preservar seus valores e as listas individuais `visibleCustomFieldKeys` sem alteração.
4. WHEN o Administrador reexibir um campo adicional THEN o sistema SHALL mostrá-lo apenas nos cadastros em que sua escolha individual estiver visível.
5. WHEN um usuário ocultar um campo somente em um cadastro THEN o sistema SHALL manter o campo visível nos demais cadastros e manter a configuração geral inalterada.
6. WHEN um estado legado não tiver `hiddenCustomFieldKeys` THEN o sistema SHALL normalizá-lo como uma lista vazia sem alterar registros.

**Independent Test**: Ocultar globalmente um campo com valores em dois Negócios, confirmar ausência em ambos, reexibir e confirmar que um Negócio individualmente oculto continua oculto enquanto o outro recupera o valor.

---

## Edge Cases

- WHEN um módulo não tiver campos adicionais THEN o sistema SHALL exibir `Nenhum campo personalizado criado.` no gerenciador.
- WHEN todos os campos adicionais de um cadastro estiverem ocultos de forma geral THEN o sistema SHALL ocultar a aba `Campos adicionais`, exceto quando outro campo disponível exigir a aba.
- IF um usuário sem perfil `Administrador` tentar abrir diretamente o gerenciador THEN o sistema SHALL rejeitar a ação sem alterar a configuração.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| FIELDVIS-01 | P1: Gerenciar visibilidade geral | Execute | Verified |
| FIELDVIS-02 | P1: Compor visibilidade geral e individual | Execute | Verified |
| FIELDVIS-03 | P1: Compatibilidade de estado | Execute | Verified |

**Coverage:** 3 total, 3 mapped to the implicit execution steps, 0 unmapped.

---

## Success Criteria

- [x] Um Administrador oculta e reexibe um campo adicional para todos os cards do módulo.
- [x] Valores e escolhas individuais permanecem idênticos durante o ciclo.
- [x] Estado legado e regressão completa permanecem verdes.
- [x] A validação independente termina em PASS.
