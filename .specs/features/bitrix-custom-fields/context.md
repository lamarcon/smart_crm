# Campos Bitrix no formato Smart CRM - Contexto

**Gathered:** 2026-08-19
**Spec:** `.specs/features/bitrix-custom-fields/spec.md`
**Status:** Ready for implementation

---

## Feature Boundary

Esta entrega transforma colunas extras dos CSVs Bitrix em campos adicionais nativos, editáveis, pesquisáveis e filtráveis dentro de cada módulo do Smart CRM. Registros já importados são migrados durante a carga. O armazenamento continua local ao navegador.

---

## Implementation Decisions

### Mapeamento e preservação

- O primeiro campo efetivamente usado por cada propriedade padrão é removido da lista adicional.
- Outros aliases e ocorrências permanecem como campos adicionais para nenhum dado ser perdido.
- A chave adicional é estável por cabeçalho normalizado e ocorrência.
- `bitrixFields` continua como cópia interna e fiel do CSV.

### Interface

- A tabela técnica `Campos do Bitrix` deixa de ser renderizada.
- Registros com campos adicionais ganham a aba `Campos adicionais`.
- Negócios importados mantêm também a aba `Orçamentos`.
- Campos não vazios aparecem inicialmente. Campos vazios entram por `Adicionar campo`.

### Estado e reimportação

- Registros legados são convertidos apenas quando ainda não possuem `customFields`, para não sobrescrever edições manuais a cada recarga.
- Reimportar o mesmo tipo e ID atualiza os valores originados no CSV.
- A lista de campos vazios tornados visíveis pelo usuário é preservada durante reimportações.

### Busca e filtros

- A busca livre inclui todos os valores adicionais, inclusive os ainda não visíveis no formulário.
- O filtro de cada módulo agrega definições adicionais únicas e oferece os operadores textuais existentes.
- O painel agregado da Visão Geral não recebe campos adicionais nesta entrega.

### Agent's Discretion

- Mensagem de estado vazio da aba e pequenos ajustes de espaçamento que sigam o sistema visual existente.

### Declined / Undiscussed Gray Areas → Assumptions

- Inferência de tipos não foi solicitada. Todos os campos adicionais usam texto nesta versão.
- Persistência em servidor permanece fora do protótipo atual.

---

## Specific References

- O usuário rejeitou a tabela `Campos do Bitrix` mostrada no painel lateral.
- O usuário pediu que todos os dados adotem o formato visual dos campos do Smart CRM.

---

## Deferred Ideas

- Inferir tipos de data, moeda, telefone, lista e área de texto.
- Disponibilizar campos adicionais no filtro agregado da Visão Geral.
- Criar um editor administrativo de esquema de campos.
