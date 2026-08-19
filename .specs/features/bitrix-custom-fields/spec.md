# Campos Bitrix no formato Smart CRM

## Problem Statement

A importação atual preserva todas as colunas do Bitrix, mas exibe os dados extras em uma tabela bruta e não editável. O usuário precisa trabalhar com esses dados como campos nativos do Smart CRM, inclusive em pesquisa e filtros, sem reenviar os CSVs já importados.

## Goals

- [ ] Mapear campos conhecidos para o formulário padrão e transformar os demais em campos adicionais editáveis.
- [ ] Migrar automaticamente registros Bitrix já armazenados no navegador.
- [ ] Incluir os campos adicionais na pesquisa e nos filtros do respectivo módulo.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Inferência automática de data, moeda ou lista | Os campos adicionais serão texto nesta versão de teste. |
| Campos adicionais no filtro agregado da Visão Geral | O painel combina entidades diferentes; esta entrega cobre o filtro de cada módulo. |
| Persistência em servidor | O protótipo atual mantém os dados no armazenamento local do navegador. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Exibição dos extras | Aba `Campos adicionais` com o mesmo estilo dos campos padrão | Evita a tabela bruta e mantém o formulário legível. | y |
| Campos vazios | Ocultos inicialmente e disponíveis em `Adicionar campo` | Preserva o esquema sem criar centenas de entradas vazias. | y |
| Cabeçalhos repetidos | Sufixo ordinal, como `Cargo (2)` | Mantém valores distintos e rótulos compreensíveis. | y |
| Reimportação do mesmo ID | Atualiza os valores do CSV e preserva a visibilidade escolhida pelo usuário | Mantém a deduplicação já aprovada. | y |
| Dados de origem | `bitrixFields` permanece interno e não aparece na interface | Garante rastreabilidade sem expor a tabela rejeitada. | y |
| Tipo dos campos adicionais | Texto | É o comportamento mais previsível para CSVs heterogêneos. | y |

**Open questions:** none - all resolved or logged above.

---

## User Stories

### P1: Converter colunas extras em campos Smart CRM ⭐ MVP

**User Story**: Como administrador, quero que cada coluna não usada pelo formulário padrão vire um campo adicional para aproveitar todos os dados exportados do Bitrix.

**Why P1**: Sem essa conversão, a importação não atende ao formato de trabalho esperado.

**Acceptance Criteria**:

1. WHEN uma linha CSV válida for importada THEN o sistema SHALL manter os campos conhecidos no formulário padrão e criar campos adicionais ordenados para todas as colunas restantes.
2. WHEN duas colunas extras tiverem o mesmo cabeçalho `Cargo` THEN o sistema SHALL preservá-las separadamente com os rótulos `Cargo` e `Cargo (2)`.
3. WHEN uma coluna extra não tiver cabeçalho THEN o sistema SHALL usar o rótulo `Campo sem nome`, com sufixo ordinal quando repetida.
4. WHEN um campo adicional tiver valor não vazio THEN o sistema SHALL marcá-lo para exibição inicial.
5. WHEN um campo adicional tiver valor vazio THEN o sistema SHALL preservá-lo e mantê-lo oculto até ser escolhido em `Adicionar campo`.
6. WHEN um registro legado tiver `bitrixFields` e não tiver `customFields` THEN o sistema SHALL criar os campos adicionais durante a próxima carga sem exigir nova importação.
7. WHEN o mesmo tipo e ID Bitrix forem reimportados THEN o sistema SHALL atualizar os campos adicionais sem criar outro cadastro e preservar os campos vazios já adicionados pelo usuário.

**Independent Test**: Importar um CSV com campos conhecidos, extras duplicados, campo sem nome e valor vazio; inspecionar o registro persistido e recarregar a página.

---

### P1: Editar campos adicionais no painel lateral ⭐ MVP

**User Story**: Como usuário comercial, quero editar os dados importados no mesmo padrão visual do Smart CRM para manter o cadastro sem lidar com uma tabela técnica.

**Why P1**: Esta é a correção visual e funcional solicitada pelo usuário.

**Acceptance Criteria**:

1. WHEN um registro importado for aberto THEN o sistema SHALL ocultar a tabela `Campos do Bitrix` e exibir a aba `Campos adicionais` ao lado de `Informações`.
2. WHILE a aba `Campos adicionais` estiver ativa, o sistema SHALL exibir cada campo visível como controle editável com seu rótulo e valor.
3. WHEN o usuário alterar um campo adicional e salvar THEN o sistema SHALL persistir o novo valor após fechar e reabrir o painel.
4. WHEN o usuário escolher um campo vazio em `Adicionar campo` THEN o sistema SHALL inserir um controle vazio no formulário e persistir sua visibilidade ao salvar.
5. WHEN um Negócio importado for aberto THEN o sistema SHALL exibir as abas `Informações`, `Campos adicionais` e `Orçamentos`.

**Independent Test**: Abrir um Negócio importado, editar um extra, adicionar um extra vazio, salvar e reabrir o painel.

---

### P1: Pesquisar e filtrar campos adicionais ⭐ MVP

**User Story**: Como usuário comercial, quero localizar registros pelos campos importados para usar os dados do Bitrix na operação diária.

**Why P1**: Campos editáveis que não podem ser encontrados continuam isolados do fluxo principal do CRM.

**Acceptance Criteria**:

1. WHEN a busca do módulo corresponder ao valor de um campo adicional THEN o sistema SHALL manter o registro correspondente visível e excluir registros sem correspondência.
2. WHEN o painel de filtros do módulo for aberto THEN o sistema SHALL listar cada definição adicional uma vez em `Adicionar campo`.
3. WHEN filtros de campos adicionais e campos padrão forem aplicados simultaneamente THEN o sistema SHALL combinar todos os critérios com conjunção lógica AND.
4. WHEN um filtro adicional usar `Contém` ou `É exatamente` THEN o sistema SHALL comparar o valor como texto sem diferenciar letras maiúsculas de minúsculas.

**Independent Test**: Buscar por um valor extra e aplicar um filtro adicional junto com o filtro padrão de nome.

---

## Edge Cases

- IF um valor adicional contiver HTML THEN o sistema SHALL exibi-lo como texto sem executar marcação.
- IF um registro não tiver campos adicionais THEN o sistema SHALL manter o formulário padrão sem uma aba adicional vazia.
- WHEN um campo adicional vazio receber um valor THEN o sistema SHALL incluí-lo nas buscas seguintes.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| BCF-01 | P1: Converter colunas extras | Execute | Implementing |
| BCF-02 | P1: Editar campos adicionais | Execute | Implementing |
| BCF-03 | P1: Pesquisar e filtrar | Execute | Pending |
| BCF-04 | Edge cases | Execute | Pending |

**Coverage:** 4 total, 4 mapped to the execution plan, 0 unmapped.

---

## Success Criteria

- [ ] Um registro já importado passa a exibir campos adicionais após uma recarga, sem reenviar o CSV.
- [ ] Todos os valores extras não vazios podem ser vistos e editados como campos Smart CRM.
- [ ] Campos extras vazios podem ser adicionados ao formulário.
- [ ] Busca e filtros do módulo encontram valores adicionais.
- [ ] A suíte completa e a validação independente terminam sem lacunas.
