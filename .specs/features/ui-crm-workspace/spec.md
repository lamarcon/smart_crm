# Evolução da Área de Trabalho do CRM — Especificação

## Problem Statement

O protótipo atual exige botões pequenos para editar registros, oferece busca limitada e usa um seletor simples para etapas. Gestores e usuários comerciais precisam abrir registros com menos esforço, combinar filtros detalhados, alternar entre Lista e Kanban e analisar resultados por funcionário, período e etapa sem sair da área de trabalho.

## Goals

- [ ] Abrir e editar os quatro cadastros centrais por um painel lateral acionado pelo nome do registro.
- [ ] Permitir filtros configuráveis e reutilizáveis que cubram todos os campos demonstrativos compatíveis.
- [ ] Disponibilizar Lista e Kanban para Leads e Negócios com transições de etapa seguras.
- [ ] Recalcular o Dashboard por responsável, equipe, período, etapa e outros critérios aplicáveis.
- [ ] Preservar as permissões simuladas, o estado local e a usabilidade móvel já validados.

## Out of Scope

| Item | Motivo |
| --- | --- |
| PostgreSQL, API produtiva e filtros executados no servidor | Esta entrega continua sendo uma evolução do protótipo local. |
| Compartilhamento de filtros entre usuários | O protótipo não possui contas ou persistência multiusuário reais. |
| Construtor lógico com grupos aninhados de `E` e `OU` | Critérios diferentes usarão `E`; múltiplos valores do mesmo campo usarão `OU`. |
| Kanban para Contatos e Empresas | Esses cadastros não possuem Pipeline no escopo aprovado. |
| Edição em massa, exportação e relatórios agendados | Não foram solicitados nesta evolução visual. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Entrada de edição | Nome principal clicável abre painel lateral para Leads, Contatos, Empresas e Negócios | Mantém a interação consistente nos quatro módulos centrais. | y |
| Salvamento no painel | Botões explícitos `Salvar` e `Cancelar` | Evita gravação acidental durante a exploração do protótipo. | n |
| Alterações não salvas | Pedir confirmação antes de fechar o painel | Evita perda silenciosa de dados digitados. | n |
| Combinação entre campos | Todos os critérios ativos usam `E` | Produz resultados previsíveis e semelhantes aos filtros estruturados do Bitrix24. | n |
| Seleção múltipla no mesmo campo | Valores do mesmo campo usam `OU` | Permite selecionar vários responsáveis ou etapas sem um construtor lógico complexo. | n |
| Persistência de filtros salvos | Por usuário demonstrativo e módulo no `localStorage` | Evita misturar configurações incompatíveis e mantém o comportamento após recarregar. | n |
| Escopo do Dashboard | `Todos`, `Leads` ou `Negócios` | Separa filtros comuns dos campos específicos de cada módulo. | n |
| Mudança comum de etapa | Aplicar imediatamente e oferecer `Desfazer` | Mantém o Kanban ágil sem impedir correção rápida. | y |
| Transição com efeito relevante | Pedir confirmação antes de executar | O usuário confirmou proteção para Faturando, encerramentos, descarte e conversão. | y |
| Estado inicial das visualizações | Lista, preservando a última escolha por módulo | Mantém familiaridade e respeita a preferência após a primeira troca. | n |

**Open questions:** none - all unresolved choices are logged as assumptions above.

---

## User Stories

### P1: Edição por painel lateral ⭐ MVP

**User Story**: Como usuário autorizado, quero abrir um registro clicando em seu nome para consultar e modificar os dados sem perder o contexto da lista.

**Why P1**: A edição é uma ação recorrente e o botão de lápis atual reduz a área clicável e interrompe a leitura da tabela.

**Acceptance Criteria**:

1. [DRAWER-01] WHEN o usuário clicar no nome principal de um Lead, Contato, Empresa ou Negócio THEN o protótipo SHALL abrir um painel pelo lado direito com os dados atuais do registro.
2. [DRAWER-02] WHILE o painel estiver aberto o protótipo SHALL manter a lista de origem visível em desktop e identificar o registro em edição.
3. [DRAWER-03] WHEN o usuário salvar dados válidos no painel THEN o protótipo SHALL atualizar o registro, fechar o painel e refletir a alteração na visualização ativa.
4. [DRAWER-04] WHEN o usuário cancelar um painel sem alterações THEN o protótipo SHALL fechá-lo sem modificar o estado local.
5. [DRAWER-05] IF o usuário tentar fechar um painel com alterações não salvas THEN o protótipo SHALL pedir confirmação antes de descartar as alterações.
6. [DRAWER-06] WHERE a interface tiver largura de 390 pixels THEN o protótipo SHALL exibir o painel em tela inteira com as ações de salvar e cancelar acessíveis.

**Independent Test**: abrir e editar cada cadastro pelo nome, cancelar uma edição, tentar fechar dados alterados e repetir o fluxo em 390×844.

### P1: Filtros configuráveis e reutilizáveis ⭐ MVP

**User Story**: Como usuário comercial, quero montar filtros com qualquer combinação de campos disponíveis para localizar exatamente os registros necessários.

**Why P1**: Busca textual e filtro único por etapa não atendem análises por responsável, período, valores e demais atributos do CRM.

**Acceptance Criteria**:

1. [FILTER-01] WHEN o usuário abrir os filtros de um módulo THEN o protótipo SHALL exibir um painel com os campos padrão, filtros salvos e a ação `Adicionar campo`.
2. [FILTER-02] WHEN o usuário adicionar ou remover um campo THEN o protótipo SHALL atualizar o formulário de filtros sem alterar os registros armazenados.
3. [FILTER-03] WHEN o usuário pesquisar texto livre THEN o protótipo SHALL comparar o termo com todos os valores textuais pesquisáveis do módulo, incluindo nome, identificador, responsável e vínculos exibidos.
4. [FILTER-04] WHEN o usuário aplicar critérios em campos diferentes THEN o protótipo SHALL exibir somente registros que satisfaçam todos os critérios ativos.
5. [FILTER-05] WHEN o usuário selecionar vários valores no mesmo campo THEN o protótipo SHALL aceitar registros que correspondam a qualquer valor selecionado nesse campo.
6. [FILTER-06] WHERE o campo filtrado for uma data THEN o protótipo SHALL oferecer data exata, antes, depois, intervalo e qualquer data.
7. [FILTER-07] WHERE o campo filtrado for numérico ou monetário THEN o protótipo SHALL oferecer valor exato, maior que, menor que e intervalo.
8. [FILTER-08] WHEN o usuário selecionar simultaneamente responsável, intervalo de datas e etapa THEN o protótipo SHALL aplicar os três critérios e atualizar a contagem visível sem recarregar a página.
9. [FILTER-09] WHEN o usuário salvar um filtro com nome inédito THEN o protótipo SHALL persistir sua configuração para o usuário demonstrativo e o módulo atuais.
10. [FILTER-10] WHEN o usuário reabrir ou excluir um filtro salvo THEN o protótipo SHALL restaurar sua configuração ou removê-lo da lista de filtros, respectivamente.
11. [FILTER-11] WHEN o usuário redefinir os filtros THEN o protótipo SHALL limpar valores e restaurar os campos padrão do módulo.
12. [FILTER-12] WHILE filtros estiverem ativos o protótipo SHALL respeitar a visibilidade permitida pelo perfil demonstrativo antes de calcular os resultados.

**Independent Test**: combinar texto, responsável, etapa, datas e valores; validar `E` entre campos e `OU` dentro do campo; salvar, reabrir, excluir e redefinir o filtro.

### P1: Lista e Kanban com transições de etapa ⭐ MVP

**User Story**: Como Vendedor ou Gestor, quero alternar entre Lista e Kanban e mudar etapas visualmente para acompanhar o trabalho comercial.

**Why P1**: A Pipeline precisa ser compreendida rapidamente e a troca atual por seletor não representa a experiência desejada.

**Acceptance Criteria**:

1. [BOARD-01] The protótipo SHALL oferecer alternância entre Lista e Kanban nas páginas de Leads e Negócios.
2. [BOARD-02] WHILE a visualização em Lista estiver ativa o protótipo SHALL representar cada etapa com uma barra segmentada, o progresso visual e o rótulo da etapa atual.
3. [BOARD-03] WHILE a visualização em Kanban estiver ativa o protótipo SHALL agrupar os cards nas etapas fixas e exibir a contagem de registros por coluna.
4. [BOARD-04] WHEN o usuário mover um Negócio para uma etapa comum THEN o protótipo SHALL atualizar a etapa imediatamente e oferecer a ação `Desfazer`.
5. [BOARD-05] WHEN o usuário confirmar a ação `Desfazer` THEN o protótipo SHALL restaurar a etapa e os dados anteriores à última transição.
6. [BOARD-06] IF uma transição entrar em `Faturando` ou encerrar um Negócio THEN o protótipo SHALL pedir confirmação antes de executar a transição e suas automações.
7. [BOARD-07] IF um Lead for movido para `Lead descartado` THEN o protótipo SHALL exigir o motivo antes de concluir a transição.
8. [BOARD-08] IF um Lead for movido para `Lead convertido` THEN o protótipo SHALL executar o fluxo de conversão e criar o Negócio correspondente em `Em Contato`.
9. [BOARD-09] WHEN o usuário alternar entre Lista e Kanban THEN o protótipo SHALL preservar os filtros ativos e a última visualização escolhida para o módulo.
10. [BOARD-10] WHILE a interface tiver largura reduzida o protótipo SHALL permitir rolagem horizontal do Kanban sem ocultar as ações principais dos cards.

**Independent Test**: filtrar Leads e Negócios, alternar as visualizações, percorrer etapas comuns, desfazer, confirmar Faturando e executar descarte e conversão pelo Kanban.

### P1: Dashboard filtrável por operação comercial ⭐ MVP

**User Story**: Como Gestor, quero filtrar o Dashboard por funcionário, equipe, período e etapa para avaliar desempenho e vendas em qualquer recorte necessário.

**Why P1**: Indicadores fixos não permitem acompanhar um funcionário ou comparar resultados de um mês específico.

**Acceptance Criteria**:

1. [DASH-01] WHEN o usuário abrir os filtros do Dashboard THEN o protótipo SHALL oferecer os escopos `Todos`, `Leads` e `Negócios`.
2. [DASH-02] WHILE o escopo `Todos` estiver ativo o protótipo SHALL permitir filtros comuns por responsável, equipe e período.
3. [DASH-03] WHILE o escopo `Leads` estiver ativo o protótipo SHALL permitir adicionar os campos disponíveis de Leads, incluindo etapa, origem, segmento e data de criação.
4. [DASH-04] WHILE o escopo `Negócios` estiver ativo o protótipo SHALL permitir adicionar os campos disponíveis de Negócios, incluindo etapa, responsável, contato, empresa, valor, data de criação, data da mudança de etapa e data de ganho.
5. [DASH-05] WHEN o usuário aplicar um ou mais filtros THEN o protótipo SHALL recalcular os indicadores, o gráfico da Pipeline e as movimentações recentes com os registros correspondentes.
6. [DASH-06] WHEN o usuário combinar funcionário, período e etapa THEN o protótipo SHALL manter os três critérios ativos e exibir o recorte combinado.
7. [DASH-07] WHEN o usuário redefinir o filtro do Dashboard THEN o protótipo SHALL restaurar os indicadores do conjunto visível ao perfil atual.
8. [DASH-08] WHILE um perfil Gestor estiver ativo o protótipo SHALL limitar indicadores e opções de responsável aos membros da sua equipe.

**Independent Test**: selecionar um funcionário, um mês e uma etapa simultaneamente; conferir contagens e valores; trocar o escopo e redefinir o Dashboard.

## Edge Cases

- IF uma combinação de filtros não encontrar registros THEN o protótipo SHALL exibir estado vazio, contagem zero e manter os critérios editáveis.
- IF um filtro salvo contiver um campo que deixou de existir na massa restaurada THEN o protótipo SHALL ignorar o campo incompatível e informar que o filtro foi ajustado.
- IF um registro deixar de ser visível após troca de perfil THEN o protótipo SHALL removê-lo da Lista, do Kanban e dos indicadores sem apagar o dado local.
- IF uma transição confirmada executar automação de Faturamento THEN o protótipo SHALL incluir a troca de responsável no estado restaurável pelo `Desfazer`.
- WHEN a demonstração for restaurada THEN o protótipo SHALL restaurar dados, filtros padrão e visualizações padrão sem preservar filtros salvos incompatíveis.

## Implicit Requirement Dimensions

| Dimension | Resolution |
| --- | --- |
| Input validation & bounds | Nomes de filtros não podem ser vazios; intervalos exigem início menor ou igual ao fim; operadores devem corresponder ao tipo do campo. |
| Failure / partial-failure states | Fechamento com edição pendente exige confirmação; filtros incompatíveis são ajustados com aviso; transições confirmadas são atômicas no estado local. |
| Idempotency / retry / duplicate handling | Salvar novamente o mesmo filtro atualiza sua configuração; `Desfazer` afeta somente a última transição ainda disponível. |
| Auth boundaries & rate limits | Permissões simuladas são aplicadas antes dos filtros; rate limit é N/A porque não há API nesta feature. |
| Concurrency / ordering | N/A porque o protótipo é local e de usuário único; a última ação confirmada define o estado. |
| Data lifecycle / expiry | Filtros e preferências persistem no `localStorage` até exclusão ou restauração da demonstração. |
| Observability | Confirmações, ajustes de filtro e transições exibem avisos visuais; logging de servidor é N/A porque a lógica permanece no navegador. |
| External-dependency failure | N/A porque a feature não chama serviços externos. |
| State-transition integrity | Descarte, conversão, Faturando e encerramentos usam guardas explícitas; transições comuns oferecem reversão completa. |

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| DRAWER-01 | P1: Painel lateral | T3 | In Tasks |
| DRAWER-02 | P1: Painel lateral | T3 | In Tasks |
| DRAWER-03 | P1: Painel lateral | T3 | In Tasks |
| DRAWER-04 | P1: Painel lateral | T3 | In Tasks |
| DRAWER-05 | P1: Painel lateral | T3 | In Tasks |
| DRAWER-06 | P1: Painel lateral | T3 | In Tasks |
| FILTER-01 | P1: Filtros configuráveis | T4 | In Tasks |
| FILTER-02 | P1: Filtros configuráveis | T4 | In Tasks |
| FILTER-03 | P1: Filtros configuráveis | T2, T4 | In Tasks |
| FILTER-04 | P1: Filtros configuráveis | T4 | In Tasks |
| FILTER-05 | P1: Filtros configuráveis | T4 | In Tasks |
| FILTER-06 | P1: Filtros configuráveis | T4 | In Tasks |
| FILTER-07 | P1: Filtros configuráveis | T4 | In Tasks |
| FILTER-08 | P1: Filtros configuráveis | T4 | In Tasks |
| FILTER-09 | P1: Filtros configuráveis | T4 | In Tasks |
| FILTER-10 | P1: Filtros configuráveis | T4 | In Tasks |
| FILTER-11 | P1: Filtros configuráveis | T4 | In Tasks |
| FILTER-12 | P1: Filtros configuráveis | T2, T4 | In Tasks |
| BOARD-01 | P1: Lista e Kanban | T5 | In Tasks |
| BOARD-02 | P1: Lista e Kanban | T5 | In Tasks |
| BOARD-03 | P1: Lista e Kanban | T5 | In Tasks |
| BOARD-04 | P1: Lista e Kanban | T5 | In Tasks |
| BOARD-05 | P1: Lista e Kanban | T2, T5 | In Tasks |
| BOARD-06 | P1: Lista e Kanban | T5 | In Tasks |
| BOARD-07 | P1: Lista e Kanban | T5 | In Tasks |
| BOARD-08 | P1: Lista e Kanban | T5 | In Tasks |
| BOARD-09 | P1: Lista e Kanban | T5 | In Tasks |
| BOARD-10 | P1: Lista e Kanban | T5 | In Tasks |
| DASH-01 | P1: Dashboard filtrável | T6 | In Tasks |
| DASH-02 | P1: Dashboard filtrável | T6 | In Tasks |
| DASH-03 | P1: Dashboard filtrável | T6 | In Tasks |
| DASH-04 | P1: Dashboard filtrável | T2, T6 | In Tasks |
| DASH-05 | P1: Dashboard filtrável | T6 | In Tasks |
| DASH-06 | P1: Dashboard filtrável | T6 | In Tasks |
| DASH-07 | P1: Dashboard filtrável | T6 | In Tasks |
| DASH-08 | P1: Dashboard filtrável | T6 | In Tasks |

**Coverage:** 36 requirements, 36 mapped to tasks, 0 unmapped.

## Success Criteria

- [ ] Um usuário abre e edita qualquer cadastro central pelo nome sem usar o ícone de lápis.
- [ ] Um usuário combina responsável, período e etapa e obtém somente registros que atendam aos três critérios.
- [ ] Filtros nomeados permanecem disponíveis após recarregar a página.
- [ ] Leads e Negócios mantêm filtros ao alternar entre Lista e Kanban.
- [ ] Transições comuns podem ser desfeitas e transições com efeitos relevantes exigem confirmação.
- [ ] O Dashboard recalcula contagens e valores para um funcionário e período escolhidos.
- [ ] As novas interações permanecem utilizáveis em desktop e 390×844.
