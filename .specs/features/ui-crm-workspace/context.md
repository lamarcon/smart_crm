# Evolução da Área de Trabalho do CRM — Contexto

**Coletado:** 2026-08-18  
**Spec:** `.specs/features/ui-crm-workspace/spec.md`  
**Status:** Approved

---

## Limite da entrega

Esta evolução preserva o protótipo local existente e melhora a experiência de consulta, edição e análise. Ela entrega edição em painel lateral, filtros configuráveis, Lista/Kanban para Leads e Negócios, transição visual de etapas inspirada no Bitrix24 e filtros analíticos no Dashboard. A entrega continua demonstrativa, com dados fictícios no `localStorage`.

---

## Decisões de implementação

### Edição em painel lateral

- Clicar no nome principal de um Lead, Contato, Empresa ou Negócio abre um painel lateral direito com os dados do registro.
- O ícone de lápis deixa de ser a entrada principal de edição.
- O painel usa ações explícitas `Salvar` e `Cancelar`.
- O fechamento com alterações não salvas pede confirmação.
- Em largura reduzida, o painel ocupa a tela inteira.

### Filtros configuráveis

- O filtro segue a referência visual do Bitrix24: painel amplo, campos adicionáveis e filtros salvos em uma área lateral.
- Cada módulo oferece busca livre em todos os valores pesquisáveis e filtros estruturados próprios.
- O usuário pode adicionar, remover e redefinir campos do painel.
- Critérios de campos diferentes são combinados por `E`.
- Vários valores selecionados no mesmo campo são combinados por `OU`.
- Datas aceitam data exata, antes, depois, intervalo e qualquer data.
- Números e valores monetários aceitam exato, maior que, menor que e intervalo.
- Os filtros podem ser usados isoladamente ou simultaneamente.
- Filtros nomeados podem ser salvos, reabertos e excluídos no navegador atual.

### Lista, Kanban e etapas

- Leads e Negócios oferecem alternância entre visualização em Lista e Kanban.
- A Lista representa a etapa com barra segmentada e rótulo, inspirada na referência do Bitrix24.
- O Kanban agrupa cards pelas etapas fixas aprovadas.
- Mudanças comuns de etapa são imediatas e oferecem `Desfazer`.
- Entrar em `Faturando`, encerrar um Negócio, descartar um Lead ou converter um Lead exige confirmação ou o fluxo específico já definido.
- Descartar Lead continua exigindo motivo; converter Lead continua criando um Negócio.

### Dashboard analítico

- O Dashboard reutiliza o mesmo mecanismo configurável de filtros.
- O filtro pode ter escopo `Todos`, `Leads` ou `Negócios`.
- No escopo `Todos`, ficam disponíveis os campos comuns, como responsável, equipe e período.
- Nos escopos específicos, são liberados campos do módulo, como etapa, origem, datas e valores.
- Todos os indicadores, gráficos e atividades exibidos são recalculados com os filtros aplicáveis.

### Agent's Discretion

- Largura exata do painel lateral em desktop.
- Cores e animações da barra segmentada e do Kanban, mantendo a identidade atual do Smart CRM.
- Ordem inicial dos campos no construtor de filtros.
- Texto curto das confirmações e avisos em português do Brasil.

### Declined / Undiscussed Gray Areas → Assumptions

- Filtros diferentes usam `E`; múltiplos valores do mesmo filtro usam `OU`, por ser previsível sem exigir um construtor lógico avançado.
- Filtros salvos pertencem ao usuário demonstrativo e ao módulo, evitando misturar filtros incompatíveis.
- O Dashboard separa campos comuns e específicos por escopo para não aplicar uma etapa de Negócio aos indicadores de Leads.
- O histórico de etapa demonstrativo guardará data e responsável pela mudança para permitir filtros e indicadores coerentes.

---

## Referências específicas

- A primeira imagem do Bitrix24 mostra uma lista de Negócios com etapa representada por uma barra horizontal segmentada, rótulo da etapa, responsável, data de criação e data da mudança de etapa.
- A segunda imagem do Bitrix24 mostra um painel de filtros com filtros nomeados, campos configuráveis, operadores por tipo, adição de campos, pesquisa e redefinição.

---

## Ideias adiadas

- Compartilhamento de filtros entre usuários.
- Filtros públicos administrados pela organização.
- Relatórios exportáveis e agendados.
- Persistência multiusuário em PostgreSQL, que pertence ao MVP produtivo.
