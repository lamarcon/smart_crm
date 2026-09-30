# Funil de Negócios Personalizável V1 — Specification

## Problem Statement

O Smart CRM possui nove etapas de Negócio fixadas no HTML e usa o nome visível da etapa como identidade, regra de automação e chave de relatório. Cada empresa precisa adaptar seu processo comercial sem quebrar negócios existentes, histórico, indicadores, permissões ou isolamento multiempresa.

## Goals

- [ ] Permitir que o Administrador de cada empresa crie, renomeie, reordene, recolora e arquive etapas de um único funil de Negócios.
- [ ] Separar a identidade imutável da etapa de seu nome visível e manter os tipos semânticos internos `open`, `won` e `lost`.
- [ ] Transferir atomicamente todos os negócios antes de arquivar uma etapa ocupada.
- [ ] Registrar cada mudança de configuração em histórico administrativo imutável pela API.
- [ ] Migrar as nove etapas atuais e todos os vínculos sem perda de dados ou alteração de comportamento.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Mais de um funil por empresa | A V1 expõe somente um funil; o schema será preparado para expansão posterior. |
| Probabilidade por etapa | Decisão explícita para uma versão futura. |
| Funil de Leads personalizável | O recorte atual é apenas o funil de Negócios. |
| Configuração de automações por etapa | A automação existente de Faturamento será preservada por chave interna, sem editor nesta versão. |
| Exclusão física de etapas ou auditoria | Arquivamento preserva referências e histórico. |
| Templates de funil e cópia entre empresas | Exigem fluxo de catálogo e importação próprio. |
| Deploy, push ou alteração de servidor | Exigem autorização explícita separada após a implementação e validação locais. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Quantidade de funis | Um funil padrão de Negócios por workspace na V1 | Escolha explícita do usuário; modelo mantém `pipeline_id` para o futuro. | y |
| Identidade de etapa | UUID imutável separado do nome visível | Renomear não pode quebrar negócios, filtros, histórico ou automações. | y |
| Tipos semânticos | `open`, `won` e `lost`; escolhido na criação e imutável depois | Mantém indicadores e transições estáveis mesmo após renomear. | y |
| Etapa inicial | Exatamente uma etapa `open` ativa é marcada como inicial | Novos Negócios precisam de destino determinístico. | y |
| Mínimos semânticos | Ao menos uma etapa ativa de cada tipo `open`, `won` e `lost` | Impede um funil incapaz de representar andamento, ganho ou perda. | y |
| Remoção | “Remover” arquiva; se houver qualquer Negócio, inclusive excluído logicamente, o Administrador escolhe uma etapa ativa diferente e todos são transferidos | Preserva restauração, integridade referencial e histórico. | y |
| Tipo da etapa de destino | Pode ser qualquer tipo semântico, desde que a confirmação mostre o efeito | Permite reabrir ou encerrar em massa de forma intencional. | y |
| Efeito semântico da transferência | Destino `won` define `wonAt`; destino `open` ou `lost` limpa `wonAt`; toda transferência registra mudança de etapa | Mantém os indicadores coerentes com o destino escolhido. | y |
| Automação de Faturamento | A etapa atual Faturando recebe uma `system_key` imutável; renomeá-la não muda a automação | Remove a dependência frágil do texto visível sem ampliar o editor de automações. | y |
| Nomes | 1 a 80 caracteres após trim, únicos entre etapas ativas sem diferenciar maiúsculas/minúsculas | Evita colunas indistinguíveis e limites sem controle. | y |
| Cores | Formato hexadecimal `#RRGGBB` | É simples, validável e compatível com a interface existente. | y |
| Limite | No máximo 50 etapas ativas | Evita payload e Kanban ilimitados sem limitar histórico arquivado. | y |
| Reordenação | Arrastar e soltar com botões subir/descer como alternativa acessível | Mantém uso semelhante ao Bitrix24 sem depender apenas de ponteiro. | y |
| Concorrência | Versão otimista do funil; configuração desatualizada recebe HTTP 409 e deve recarregar | Impede que dois administradores sobrescrevam alterações. | y |
| Retry | Repetição com versão já consumida recebe HTTP 409 sem nova transferência ou auditoria | A operação permanece segura e não duplica efeitos. | y |
| Auditoria | Uma entrada por gravação, com ator, instante, versão, ações, antes/depois e resumo das transferências; 50 itens por página | Mantém histórico útil e paginado sem registrar dados comerciais completos. | y |
| Migração legada | As nove etapas conhecidas são mapeadas exatamente; etapa legada desconhecida interrompe a migração antes de publicar a nova revisão | Evita classificar silenciosamente uma etapa real com semântica errada. | y |
| Rate limiting específico | Não adicionar; autenticação, sessão, origem e autorização administrativas existentes continuam obrigatórias | Endpoint interno autenticado e volume baixo; limites de login já existem. | y |

**Open questions:** none — as recomendações foram aprovadas pelo usuário.

---

## User Stories

### P1: Consultar um funil canônico por empresa

**User Story**: Como usuário autenticado, quero que o CRM carregue as etapas configuradas da minha empresa para usar os nomes, cores, ordem e significados corretos em todo o sistema.

**Why P1**: Sem uma fonte canônica por tenant, cada tela continuaria dependendo das nove strings fixas.

**Acceptance Criteria**:

1. WHEN um usuário autenticado carregar o workspace THEN the system SHALL retornar somente o funil padrão do tenant derivado de sua sessão.
2. The system SHALL identificar cada etapa por UUID imutável e expor nome, cor, posição, tipo semântico, estado ativo e indicação de etapa inicial.
3. WHILE uma etapa estiver ativa, the system SHALL exibi-la na mesma ordem em listas, Kanban, filtros, formulários, indicadores e barra de progresso.
4. IF o funil canônico não puder ser carregado THEN the system SHALL bloquear operações de Negócio dependentes de etapa e exibir erro sem usar as nove etapas fixas como fallback.
5. IF o navegador enviar tenant, workspace ou pipeline alternativo THEN the system SHALL ignorar esses valores para roteamento e usar somente a sessão autenticada.

**Independent Test**: Autenticar em dois tenants com configurações diferentes e comprovar que cada sessão recebe e renderiza somente seu próprio funil.

### P1: Personalizar etapas como Administrador

**User Story**: Como Administrador da empresa, quero criar, renomear, reordenar, recolorir e escolher a etapa inicial para adaptar o funil ao processo comercial.

**Why P1**: É o valor principal da primeira versão personalizável.

**Acceptance Criteria**:

1. WHILE o usuário autenticado for Administrador, the system SHALL permitir abrir a página Funil de negócios e editar somente o funil de seu tenant.
2. WHEN o Administrador criar uma etapa válida THEN the system SHALL atribuir um novo UUID, o tipo semântico escolhido e uma posição no funil.
3. WHEN o Administrador renomear ou recolorir uma etapa THEN the system SHALL preservar seu UUID, tipo semântico, vínculos, histórico e `system_key`.
4. WHEN o Administrador reordenar etapas THEN the system SHALL persistir posições inteiras, únicas e contínuas de zero até `n-1`.
5. WHEN o Administrador escolher uma etapa inicial THEN the system SHALL aceitar somente uma etapa ativa do tipo `open`.
6. IF um nome estiver vazio, exceder 80 caracteres ou duplicar outro nome ativo sem diferenciar caixa THEN the system SHALL responder HTTP 422 e manter a configuração anterior.
7. IF uma cor não corresponder a `#[0-9A-Fa-f]{6}` THEN the system SHALL responder HTTP 422 e manter a configuração anterior.
8. IF a alteração produzir mais de 50 etapas ativas THEN the system SHALL responder HTTP 422 e manter a configuração anterior.
9. IF um usuário não Administrador tentar alterar o funil THEN the system SHALL responder HTTP 403 e manter banco e auditoria inalterados.

**Independent Test**: Editar todas as propriedades permitidas como Administrador e repetir as chamadas com dados inválidos e com cada perfil não administrativo.

### P1: Arquivar com transferência atômica

**User Story**: Como Administrador, quero arquivar uma etapa ocupada somente depois de escolher o destino para não deixar negócios órfãos.

**Why P1**: É a regra de integridade escolhida pelo usuário para retirada de etapas.

**Acceptance Criteria**:

1. WHEN o Administrador solicitar o arquivamento de uma etapa sem Negócios THEN the system SHALL arquivá-la sem exigir destino e sem apagá-la fisicamente.
2. WHEN o Administrador solicitar o arquivamento de uma etapa com Negócios THEN the system SHALL exigir uma etapa de destino ativa, diferente e pertencente ao mesmo funil.
3. WHEN uma transferência for confirmada THEN the system SHALL mover todos os Negócios vinculados, inclusive excluídos logicamente, e arquivar a origem na mesma transação PostgreSQL.
4. WHEN um Negócio for transferido em massa THEN the system SHALL acrescentar uma entrada ao histórico de etapa com os IDs e nomes de origem/destino, ator e instante.
5. WHEN o destino tiver tipo `won` THEN the system SHALL definir `wonAt` para o instante da transferência nos Negócios que ainda não possuírem esse valor.
6. WHEN o destino tiver tipo `open` ou `lost` THEN the system SHALL limpar `wonAt` dos Negócios transferidos.
7. IF o destino estiver ausente, arquivado, for a própria origem ou pertencer a outro funil THEN the system SHALL responder HTTP 422 sem mover Negócios, arquivar etapa ou gravar auditoria.
8. IF o arquivamento remover a última etapa ativa de qualquer tipo semântico THEN the system SHALL responder HTTP 422 e manter a transação inalterada.
9. IF qualquer escrita da transferência ou auditoria falhar THEN the system SHALL reverter toda a operação.

**Independent Test**: Arquivar etapas vazias e ocupadas para destinos dos três tipos, injetar falha intermediária e comparar etapa, negócios, histórico e auditoria antes/depois.

### P1: Preservar regras e relatórios após renomear

**User Story**: Como usuário comercial, quero que Kanban, filtros, indicadores e automações continuem corretos depois que os nomes mudarem.

**Why P1**: O código atual usa nomes visíveis para decidir comportamento, e uma simples renomeação quebraria o CRM.

**Acceptance Criteria**:

1. WHEN um Negócio entrar em etapa do tipo `won` THEN the system SHALL tratá-lo como ganho independentemente do nome visível.
2. WHILE um Negócio estiver em etapa do tipo `open`, the system SHALL incluí-lo nos indicadores de negócios abertos independentemente do nome visível.
3. WHILE um Negócio estiver em etapa do tipo `lost`, the system SHALL tratá-lo como encerrado e não ganho independentemente do nome visível.
4. WHEN um Negócio entrar na etapa com `system_key=billing` THEN the system SHALL executar a automação de Faturamento independentemente do nome visível.
5. WHEN um novo Negócio for criado THEN the system SHALL usar a etapa inicial ativa configurada no funil.
6. WHEN uma etapa for renomeada THEN the system SHALL preservar nos históricos anteriores o nome exibido no momento de cada transição.
7. IF uma gravação de workspace referenciar etapa inexistente ou arquivada THEN the system SHALL rejeitar a gravação com HTTP 409 e preservar a versão canônica.

**Independent Test**: Renomear as etapas equivalentes a Em Contato, Faturando, Ganho e perda e repetir criação, movimentação, filtros, dashboard e automação.

### P1: Registrar histórico administrativo

**User Story**: Como Administrador, quero consultar quem alterou o funil e o que mudou para auditar a configuração da empresa.

**Why P1**: O usuário pediu histórico e operações de transferência têm impacto comercial amplo.

**Acceptance Criteria**:

1. WHEN uma configuração for gravada com sucesso THEN the system SHALL criar uma entrada com tenant/workspace, pipeline, versão resultante, ator, instante, ações, estado anterior e estado posterior.
2. WHEN houver transferência THEN the system SHALL registrar IDs de origem/destino e quantidade de Negócios transferidos sem copiar payloads comerciais completos.
3. IF a operação for rejeitada ou revertida THEN the system SHALL não criar entrada de histórico administrativo.
4. WHILE o usuário autenticado for Administrador, the system SHALL permitir consultar o histórico em páginas de 50 itens ordenadas do mais recente para o mais antigo.
5. IF um usuário não Administrador consultar o histórico THEN the system SHALL responder HTTP 403 sem retornar metadados.
6. The system SHALL manter inexistente qualquer endpoint para editar ou excluir entradas do histórico administrativo.

**Independent Test**: Executar cada tipo de alteração, conferir os campos do evento e provar ausência de evento em falhas e ausência de acesso para outros perfis.

### P1: Impedir sobrescrita concorrente

**User Story**: Como Administrador, quero ser avisado se outro administrador salvar primeiro para não perder alterações silenciosamente.

**Why P1**: A edição do funil pode mover muitos negócios e não pode usar last-write-wins.

**Acceptance Criteria**:

1. WHEN o Administrador salvar uma versão atual do funil THEN the system SHALL incrementar a versão exatamente uma vez.
2. IF a versão enviada não corresponder à versão canônica THEN the system SHALL responder HTTP 409 com código `pipeline_version_conflict` e não executar nenhuma escrita.
3. WHEN uma transferência alterar Negócios THEN the system SHALL incrementar também a versão do workspace para invalidar snapshots comerciais concorrentes.
4. IF a mesma requisição for repetida após a primeira confirmação THEN the system SHALL responder HTTP 409 sem repetir transferência, incremento ou auditoria.

**Independent Test**: Abrir duas versões iguais, salvar a primeira e demonstrar que a segunda e o retry não modificam nenhuma tabela.

### P1: Migrar e operar sem perda

**User Story**: Como operador, quero atualizar cada banco tenant de forma verificável e reversível para preservar o ambiente multiempresa já em produção.

**Why P1**: A alteração atinge schema tenant, pacote Windows e revisão esperada no plano de controle.

**Acceptance Criteria**:

1. WHEN a migração for aplicada ao banco existente THEN the system SHALL criar um funil padrão com as nove etapas atuais na mesma ordem, cores e semânticas definidas no plano de migração.
2. WHEN a migração for aplicada THEN the system SHALL vincular cada Negócio e cada histórico de etapa conhecido aos novos IDs sem alterar contagens, valores ou vínculos comerciais.
3. IF uma etapa legada não estiver no mapeamento aprovado THEN the system SHALL abortar a migração antes de publicar a nova revisão Alembic.
4. The system SHALL manter as colunas de nome legadas sincronizadas durante esta versão para permitir rollback para a release anterior.
5. WHEN a nova revisão tenant for preparada THEN the system SHALL atualizar de forma explícita e verificável a revisão esperada do tenant selecionado no plano de controle.
6. IF backup, identidade, revisão anterior ou seleção explícita do tenant não forem confirmados THEN the system SHALL bloquear a migração operacional.
7. The system SHALL manter `DW_CMS`, `DW_PRODUTOS`, listener PostgreSQL e regras de acesso fora do escopo da migração tenant.

**Independent Test**: Migrar uma cópia com dados representativos, comparar fingerprints e contagens, testar etapa desconhecida, executar a suíte PostgreSQL 11 e validar rollback da aplicação sobre o schema aditivo.

---

## Edge Cases

- IF duas etapas ativas diferirem somente por espaços externos ou caixa THEN the system SHALL rejeitar a configuração como nome duplicado.
- IF a etapa inicial for arquivada sem outra etapa inicial `open` na mesma gravação THEN the system SHALL responder HTTP 422 e manter a configuração anterior.
- IF um Negócio excluído logicamente estiver na etapa arquivada THEN the system SHALL transferi-lo para que uma restauração futura use etapa ativa.
- IF a etapa `system_key=billing` for arquivada THEN the system SHALL permitir a operação somente após transferência e SHALL manter a chave no registro arquivado sem atribuí-la automaticamente a outra etapa.
- IF o banco do tenant falhar durante uma alteração THEN the system SHALL responder indisponibilidade sem usar outro tenant ou cache como fallback.
- IF uma sessão apontar para outro tenant por rota manipulada THEN the system SHALL rejeitar a rota sem revelar a configuração do tenant solicitado.

---

## Implicit-Requirement Dimensions

| Dimension | Resolution |
| --------- | ---------- |
| Input validation & bounds | Nomes, cores, tipos, posições, etapa inicial e limite de 50 etapas são critérios explícitos. |
| Failure / partial-failure states | Configuração, transferências e auditoria usam uma transação com rollback total. |
| Idempotency / retry / duplicate handling | Versão consumida retorna 409 e não duplica efeitos. |
| Auth boundaries & rate limits | Somente Administrador altera/consulta auditoria; leitura operacional requer sessão. Rate limit específico é N/A pelo baixo volume interno e proteções de sessão/origem existentes. |
| Concurrency / ordering | Versões de pipeline e workspace impedem sobrescritas e posições são contínuas. |
| Data lifecycle / expiry | Etapas e auditorias não expiram nem são excluídas na V1; arquivamento preserva referências. |
| Observability | Histórico administrativo registra ator, instante, diff e resumo de transferências. |
| External-dependency failure | N/A porque a operação depende apenas do PostgreSQL tenant já selecionado; indisponibilidade falha fechada. |
| State-transition integrity | Tipos mínimos, destino válido, `wonAt`, histórico e automação interna têm guardas explícitas. |

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| PIPE-01 | Consultar um funil canônico por empresa | Execute | In Progress — T1-T3,T6,T8 complete |
| PIPE-02 | Personalizar etapas como Administrador | Execute | In Progress — T1,T4,T6 complete |
| PIPE-03 | Arquivar com transferência atômica | Execute | In Progress — T3,T5,T7 complete |
| PIPE-04 | Preservar regras e relatórios após renomear | Execute | In Progress — T2,T5,T7,T8 complete |
| PIPE-05 | Registrar histórico administrativo | Execute | In Progress — T1,T3-T6 complete |
| PIPE-06 | Impedir sobrescrita concorrente | Execute | In Progress — T4-T7 complete |
| PIPE-07 | Migrar e operar sem perda | Execute | In Progress — T2,T7 complete |

**Coverage:** 7 requirements, 7 mapped to tasks, 0 unmapped.

---

## Success Criteria

- [ ] Um Administrador configura o funil e consulta o histórico sem editar código ou banco manualmente.
- [ ] Renomear qualquer etapa não altera seus Negócios, tipo semântico, automação ou histórico anterior.
- [ ] Arquivar uma etapa ocupada transfere 100% dos Negócios ou 0%, nunca parcialmente.
- [ ] Perfis não administrativos não conseguem alterar configuração nem consultar auditoria por UI ou chamada direta.
- [ ] A migração preserva contagens e fingerprints comerciais e passa nos gates PostgreSQL 11, backend e navegador.
