# Histórico Operacional de Negócios e Empresas V1 — Specification

## Problem Statement

O Smart CRM registra tecnicamente mudanças de etapa, mas o usuário não possui uma linha do tempo operacional dentro do card para entender o que ocorreu, quais automações foram executadas e quais observações foram deixadas. A ficha da Empresa também não resume o volume e o resultado de seus Negócios nem mantém um histórico próprio. Isso obriga o usuário a navegar por várias telas e impede uma leitura comercial semelhante à oferecida pelo Bitrix24 e pelo RD Station.

## Goals

- [ ] Exibir dentro do Negócio uma linha do tempo confiável de movimentações, automações e observações.
- [ ] Permitir observações manuais imutáveis com autor e instante definidos pelo servidor.
- [ ] Ampliar o painel do Negócio para uma experiência de duas colunas em desktop.
- [ ] Mostrar na Empresa totais, quantidades, valores e lista dos Negócios vinculados.
- [ ] Manter na Empresa um histórico próprio de alterações cadastrais e observações.
- [ ] Preservar isolamento multiempresa, autorização e consistência transacional.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Tarefas e subtarefas | O usuário decidiu não alterar tarefas nesta versão. |
| Agenda, lembretes e calendário | Dependem de um domínio de tarefas futuro. |
| Ticket médio e tempo médio de venda | Foram adiados para manter o primeiro painel objetivo. |
| Editor de automações | A V1 apenas registra a execução das automações existentes/futuras. |
| Mensagens, WhatsApp, e-mail e chat | Exigem integrações e regras de entrega separadas. |
| Anexos, menções e respostas em observações | Não são necessários para o histórico inicial. |
| Edição ou exclusão de eventos | Contraria a decisão de histórico permanente. |
| Duplicar no histórico da Empresa cada evento de Negócio | Produziria ruído e duplicidade; o detalhe permanece no Negócio. |
| Deploy, push ou alteração do servidor | Exigem autorização explícita separada após implementação e validação locais. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Conteúdo do Negócio | Movimentações, automações e observações | Recorte explicitamente solicitado pelo usuário. | y |
| Tarefas | Ausentes da V1 | Decisão explícita do usuário. | y |
| Observações | Imutáveis após o envio | Mantém o histórico confiável; correções entram como nova observação. | y |
| Layout do Negócio | Painel amplo, duas colunas em desktop | O usuário aprovou cobrir grande parte da aba, como o Bitrix24. | y |
| Empresa | Abas Informações, Negócios e Histórico | Experiência solicitada com referência ao RD Station. | y |
| Indicadores da Empresa | Total, quantidade e valor de abertos, ganhos e perdidos | Atende a leitura comercial sem incluir métricas adiadas. | y |
| Semântica de resultado | Tipo imutável `open`, `won` ou `lost` da etapa | Renomear a etapa não pode mudar os números. | y |
| Valores | Soma exata do valor dos Negócios ativos vinculados em cada tipo semântico | Evita snapshots derivados divergentes. | y |
| Exclusão lógica | Negócios excluídos não entram nos indicadores/lista operacional | Mantém coerência com as telas comerciais ativas. | y |
| Ordem do histórico | Mais recente primeiro, com paginação por cursor | Escala sem depender de offset mutável. | y |
| Visibilidade | Acompanha a permissão de leitura da entidade | Não cria um canal paralelo de acesso. | y |
| Publicação de observação | Exige permissão de alteração da entidade | Reutiliza a fronteira de autorização comercial. | y |
| Automação | Evento registra regra, resultado e resumo das ações, sem segredos | Torna a execução compreensível e segura. | y |

**Open questions:** none — as decisões de produto e recomendações acima foram aprovadas pelo usuário.

---

## User Stories

### P1: Consultar a linha do tempo do Negócio

**User Story**: Como usuário comercial, quero ver no próprio card tudo que ocorreu com o Negócio para compreender rapidamente seu andamento.

**Why P1**: Esta é a principal experiência solicitada e concentra o contexto que hoje está disperso.

**Acceptance Criteria**:

1. WHEN um usuário autorizado abrir um Negócio THEN the system SHALL carregar sua linha do tempo em ordem do evento mais recente para o mais antigo.
2. The system SHALL retornar para cada evento um identificador imutável, categoria, descrição, ator e timestamp canônico com fuso exibido em `America/Sao_Paulo`.
3. WHEN uma etapa mudar THEN the system SHALL exibir os nomes e IDs da etapa anterior e posterior preservados no momento da transição.
4. WHEN a movimentação ocorrer por transferência administrativa de etapa THEN the system SHALL identificá-la como movimentação e manter o ator administrativo.
5. WHEN o usuário escolher um filtro THEN the system SHALL limitar a lista a `Movimentações`, `Automações` ou `Observações` sem alterar os eventos persistidos.
6. WHEN houver mais de 50 eventos THEN the system SHALL retornar a primeira página e permitir carregar a continuação por cursor estável.
7. IF o Negócio não existir, estiver fora do tenant da sessão ou não for visível ao usuário THEN the system SHALL responder como recurso não encontrado sem revelar metadados.

**Independent Test**: Criar eventos das três categorias para dois tenants, consultar e filtrar a linha do tempo, paginar mais de 50 itens e provar que uma sessão nunca recebe eventos do outro tenant.

### P1: Registrar movimentações e automações atomicamente

**User Story**: Como usuário comercial, quero confiar que toda movimentação e automação exibida corresponde ao que realmente aconteceu.

**Why P1**: Um histórico divergente da operação comercial perde valor de auditoria.

**Acceptance Criteria**:

1. WHEN uma mudança de etapa for confirmada THEN the system SHALL persistir a transição e seu evento na mesma transação PostgreSQL.
2. WHEN uma automação for executada THEN the system SHALL registrar nome/chave da regra, resultado `success` ou `failure` e resumo seguro das ações tentadas.
3. WHEN a automação de Faturamento alterar o responsável e emitir notificação THEN the system SHALL produzir um único evento de automação que resuma esses efeitos.
4. IF a mutação comercial for revertida THEN the system SHALL não deixar evento de sucesso persistido.
5. IF uma automação falhar após ter sido iniciada THEN the system SHALL registrar falha sem expor senha, DSN, token, stack trace ou payload confidencial.
6. IF a mesma execução idempotente for repetida THEN the system SHALL manter um único evento para o mesmo identificador de execução.
7. The system SHALL preservar os eventos anteriores quando uma etapa ou automação for renomeada posteriormente.

**Independent Test**: Movimentar um Negócio, executar Faturamento, injetar falhas e retries e comparar estado comercial, notificação e eventos antes/depois.

### P1: Publicar observações manuais imutáveis

**User Story**: Como usuário autorizado, quero registrar uma observação no Negócio ou na Empresa para preservar contexto comercial relevante.

**Why P1**: O contexto humano complementa eventos gerados pelo sistema.

**Acceptance Criteria**:

1. WHEN um usuário com permissão de alteração enviar uma observação entre 1 e 4.000 caracteres após trim THEN the system SHALL persistir exatamente um evento associado à entidade.
2. The system SHALL derivar ator, tenant, workspace e timestamp exclusivamente da sessão e do servidor.
3. IF o texto estiver vazio ou exceder 4.000 caracteres THEN the system SHALL responder HTTP 422 sem criar evento.
4. IF o usuário puder visualizar mas não alterar a entidade THEN the system SHALL responder HTTP 403 ao envio sem criar evento.
5. The system SHALL não disponibilizar endpoint ou controle de interface para editar ou excluir uma observação persistida.
6. WHEN uma correção for necessária THEN the system SHALL permitir uma nova observação sem modificar a anterior.
7. IF houver clique duplo ou retry com a mesma chave de idempotência THEN the system SHALL devolver o evento original sem duplicar a observação.

**Independent Test**: Enviar observações válidas, vazias, excessivas, sem permissão e repetidas; recarregar a página e comprovar imutabilidade e autoria.

### P1: Usar um painel amplo e responsivo no Negócio

**User Story**: Como usuário comercial, quero trabalhar com os dados e o histórico simultaneamente sem perder espaço útil.

**Why P1**: O drawer atual é estreito demais para a experiência semelhante ao Bitrix24 aprovada pelo usuário.

**Acceptance Criteria**:

1. WHEN a viewport tiver largura de desktop THEN the system SHALL abrir o Negócio em um painel que ocupe a maior parte da área útil e mostre dados à esquerda e atividade à direita.
2. WHILE o painel estiver aberto, the system SHALL manter acessíveis informações, campos adicionais e orçamentos existentes sem regressão funcional.
3. WHILE a linha do tempo estiver carregando, vazia ou com falha THEN the system SHALL mostrar estados distintos e manter os dados do Negócio utilizáveis.
4. WHEN a viewport for estreita THEN the system SHALL reorganizar o conteúdo em uma coluna ou abas sem rolagem horizontal da página.
5. The system SHALL permitir navegação por teclado, foco visível, nomes acessíveis e fechamento por `Escape` conforme o comportamento atual do painel.
6. WHEN uma observação for enviada com sucesso THEN the system SHALL inseri-la no topo da linha do tempo sem exigir recarregamento integral da página.

**Independent Test**: Executar o fluxo completo em viewports de desktop e móvel, por mouse e teclado, cobrindo loading, vazio, erro, filtros e inclusão de observação.

### P1: Resumir os Negócios vinculados na Empresa

**User Story**: Como usuário comercial, quero saber quantos Negócios uma Empresa possui e quantos estão em andamento, ganhos ou perdidos.

**Why P1**: Esta é a leitura comercial de Empresa solicitada com referência ao RD Station.

**Acceptance Criteria**:

1. WHEN um usuário autorizado abrir a aba `Negócios` de uma Empresa THEN the system SHALL calcular somente os Negócios ativos vinculados àquela Empresa no workspace da sessão.
2. The system SHALL mostrar total geral e, para cada tipo `open`, `won` e `lost`, a quantidade e a soma exata dos valores.
3. WHEN uma etapa for renomeada THEN the system SHALL manter os mesmos agrupamentos porque o cálculo usa o tipo semântico imutável.
4. WHEN um Negócio mudar de Empresa, valor ou tipo semântico de etapa THEN the system SHALL refletir o novo resultado após a confirmação da mutação.
5. The system SHALL listar cada Negócio vinculado com título, etapa, tipo semântico apresentado em português, responsável e valor.
6. WHEN o usuário selecionar um Negócio da lista THEN the system SHALL abrir seu painel detalhado sem perder a referência à Empresa de origem.
7. IF não houver Negócios vinculados THEN the system SHALL mostrar contadores e valores zerados e um estado vazio, sem erro.
8. IF um Negócio estiver excluído logicamente ou vinculado a outra Empresa/tenant THEN the system SHALL não incluí-lo em nenhum total ou item da lista.

**Independent Test**: Vincular Negócios dos três tipos, com valores e tenants distintos, renomear etapas, mover e excluir registros e comparar contagens, somas e lista.

### P1: Manter histórico próprio da Empresa

**User Story**: Como usuário comercial, quero consultar alterações e observações da Empresa separadamente dos Negócios.

**Why P1**: A ficha da Empresa precisa preservar contexto próprio sem repetir toda a atividade de seus Negócios.

**Acceptance Criteria**:

1. WHEN uma Empresa for criada THEN the system SHALL registrar um evento de criação com ator e timestamp.
2. WHEN nome, proprietário, cidade, segmento, telefone ou campo adicional da Empresa mudar THEN the system SHALL registrar os campos alterados com valores anterior e posterior adequados para exibição.
3. WHEN uma observação for publicada na Empresa THEN the system SHALL exibi-la em seu histórico nas mesmas condições de imutabilidade.
4. The system SHALL não copiar para o histórico da Empresa cada movimentação ou automação dos Negócios vinculados.
5. IF nenhum valor persistido mudar em uma gravação THEN the system SHALL não criar evento de alteração vazio.
6. IF um valor confidencial for alterado no futuro THEN the system SHALL permitir marcar o campo como redigido para que seu conteúdo não entre no histórico.
7. WHEN houver mais de 50 eventos THEN the system SHALL paginar por cursor estável e manter a ordem mais recente primeiro.

**Independent Test**: Criar e alterar uma Empresa, realizar no-op, publicar observação, movimentar um Negócio vinculado e comprovar que apenas os eventos próprios aparecem.

### P1: Preservar isolamento e operação segura

**User Story**: Como administrador da plataforma, quero que os novos eventos e indicadores mantenham as garantias multiempresa e operacionais existentes.

**Why P1**: Históricos concentram informação sensível e não podem criar vazamento entre bancos ou sessões.

**Acceptance Criteria**:

1. The system SHALL persistir eventos somente no banco tenant selecionado pela sessão e com o `workspace_id` transacional vigente.
2. IF o cliente enviar tenant, workspace, ator ou timestamp alternativo THEN the system SHALL ignorar esses valores de roteamento/autoria ou rejeitar o payload.
3. The system SHALL habilitar e forçar RLS nas novas tabelas tenant e negar operação sem contexto de workspace.
4. WHEN uma entidade for excluída logicamente THEN the system SHALL preservar seus eventos para restauração/auditoria, sem exibi-los em consultas operacionais comuns.
5. The system SHALL usar migração aditiva e não alterar `DW_CMS`, `DW_PRODUTOS`, `smartcrm_control`, listener ou regras globais do PostgreSQL.
6. IF a fonte de indicadores ou eventos estiver indisponível THEN the system SHALL falhar fechada, sem usar dados de outro tenant ou totais armazenados no navegador.
7. WHEN a nova revisão tenant for preparada para deploy futuro THEN the system SHALL preservar o fluxo de migração de frota e a revisão esperada do plano de controle.

**Independent Test**: Exercitar APIs e repositórios em dois bancos tenant, tentar forjar escopo, remover contexto RLS e executar upgrade/downgrade em banco PostgreSQL isolado.

---

## Edge Cases

- IF duas movimentações tiverem o mesmo timestamp THEN the system SHALL desempatar deterministicamente pelo identificador do evento.
- IF o ator original tiver sido desativado THEN the system SHALL preservar seu identificador e nome de exibição histórico sem reativá-lo.
- IF uma etapa histórica estiver arquivada ou renomeada THEN the system SHALL exibir o snapshot do nome registrado no evento.
- IF o valor de um Negócio for nulo THEN the system SHALL tratá-lo como zero apenas para soma, sem alterar o registro original.
- IF uma Empresa possuir Negócios em todas as categorias com soma zero THEN the system SHALL manter as quantidades corretas e valores monetários zerados.
- IF uma observação contiver HTML ou script THEN the system SHALL armazenar texto e escapar a renderização, sem executar marcação.
- IF uma observação for enviada enquanto a entidade for alterada por outro usuário THEN the system SHALL anexar o evento sem sobrescrever os dados da entidade.
- IF uma automação gerar uma notificação para vários usuários THEN the system SHALL registrar um evento de execução, não um evento por destinatário.
- IF a lista de Negócios da Empresa mudar enquanto uma página estiver aberta THEN the system SHALL recalcular a partir do estado canônico no próximo carregamento, sem confiar em totais locais obsoletos.

---

## Implicit-Requirement Dimensions

| Dimension | Resolution |
| --------- | ---------- |
| Input validation & bounds | Observações usam trim, limite de 4.000 caracteres e texto escapado; filtros/cursor são enumerados e validados. |
| Failure / partial-failure states | Mutação e evento relacionado são atômicos; automação registra resultado seguro. |
| Idempotency / retry / duplicate handling | Observações e automações usam chave de idempotência; transições mantêm uma entrada por operação. |
| Auth boundaries & rate limits | Leitura acompanha visibilidade; escrita acompanha permissão de alteração; proteções existentes de sessão/origem permanecem. Rate limit específico é N/A para uso interno autenticado. |
| Concurrency / ordering | Ordem usa timestamp e ID; paginação por cursor; observação não substitui snapshot comercial. |
| Data lifecycle / expiry | Eventos não expiram e não são excluídos na V1; exclusão lógica da entidade apenas os oculta da operação comum. |
| Observability | Falhas de automação possuem resultado e resumo seguro; erros de API preservam correlation ID sem expor segredos. |
| External-dependency failure | N/A na V1: o fluxo depende somente do banco tenant selecionado; futuras integrações deverão registrar falha de forma segura. |
| State-transition integrity | Categorias e snapshots de etapa são imutáveis; indicadores usam semântica canônica e não nomes visíveis. |

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| HIST-01 | Consultar a linha do tempo do Negócio | Execute | In progress (T1-T4 complete) |
| HIST-02 | Registrar movimentações e automações atomicamente | Execute | In progress (T1,T4 complete) |
| HIST-03 | Publicar observações manuais imutáveis | Execute | In progress (T1-T2,T4 complete) |
| HIST-04 | Usar um painel amplo e responsivo no Negócio | Specify | Planned |
| HIST-05 | Resumir os Negócios vinculados na Empresa | Execute | In progress (T2 complete) |
| HIST-06 | Manter histórico próprio da Empresa | Execute | In progress (T1-T4 complete) |
| HIST-07 | Preservar isolamento e operação segura | Execute | In progress (T1,T3-T4 complete) |

**Coverage:** 7 requirements mapped to approved tasks; T1-T4 complete, T5-T18 pending.

---

## Success Criteria

- [ ] O usuário consulta movimentações, automações e observações sem sair do Negócio.
- [ ] Uma observação permanece após recarregar e não pode ser editada ou excluída.
- [ ] A Empresa mostra contagens e valores exatos para total, andamento, ganho e perdido.
- [ ] Renomear uma etapa não altera classificação, indicadores nem descrição histórica anterior.
- [ ] O histórico da Empresa não duplica a linha do tempo detalhada dos Negócios.
- [ ] Nenhuma sessão, API ou consulta recebe eventos ou indicadores de outro tenant/workspace.
- [ ] A interface passa nos fluxos de desktop amplo, responsivo, teclado, vazio, loading e erro sem regressão das abas existentes.
