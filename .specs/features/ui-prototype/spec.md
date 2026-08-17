# Especificação — Protótipo Local do Smart CRM

## Problem Statement

O cliente precisa visualizar rapidamente como o Smart CRM poderá funcionar antes da implementação com PostgreSQL, integrações e dados reais. É necessário um ambiente demonstrativo descartável que apresente o layout e permita experimentar os fluxos essenciais sem depender de infraestrutura externa.

## Goals

- [ ] Disponibilizar uma demonstração navegável por Docker Compose.
- [ ] Representar os módulos e Pipelines já aprovados com dados fictícios.
- [ ] Permitir experimentar ações locais sem banco de dados.
- [ ] Comunicar claramente que o ambiente é demonstrativo e não produtivo.

## Out of Scope

| Item | Motivo |
| --- | --- |
| PostgreSQL e persistência no servidor | O objetivo atual é validar layout e interação. |
| Segurança e permissões de produção | O seletor de perfil apenas simula a experiência. |
| WordPress e Bitrix24 reais | Integrações serão implementadas no MVP de produção. |
| Armazenamento de PDFs | O protótipo registra somente o nome do arquivo selecionado. |

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Persistência demonstrativa | `localStorage` do navegador | Mantém as alterações após recarregar sem introduzir banco. | y |
| Porta local | 8080 | Evita exigir privilégios administrativos e é comum em ambientes locais. | n |
| Massa de dados | Registros totalmente fictícios | Impede uso acidental de dados pessoais nesta fase visual. | y |
| Perfis | Administrador, Gestor, Vendedor e Assistente selecionáveis na interface | Demonstra a regra aprovada sem prometer segurança de backend. | y |

**Open questions:** none - a porta poderá ser sobrescrita pelo usuário no Compose se necessário.

## User Stories

### P1: Inicialização local ⭐ MVP

**User Story**: Como avaliador, quero iniciar o protótipo com um comando para acessar a demonstração sem preparar banco ou serviços externos.

**Acceptance Criteria**:

1. [DEMO-01] WHEN o usuário executar `docker compose up --build` THEN o protótipo SHALL ficar acessível por HTTP em `localhost:8080`.
2. [DEMO-02] WHILE o protótipo estiver em execução o sistema SHALL responder uma verificação de saúde sem depender de PostgreSQL ou serviço externo.
3. [DEMO-03] WHEN o navegador for aberto pela primeira vez THEN o sistema SHALL carregar dados fictícios suficientes para demonstrar todos os módulos incluídos.

**Independent Test**: iniciar o Compose em uma máquina sem banco configurado, consultar a rota de saúde e abrir a interface.

### P1: Navegação e cadastros demonstrativos ⭐ MVP

**User Story**: Como avaliador, quero navegar pelos módulos e manipular dados fictícios para compreender o comportamento esperado do CRM.

**Acceptance Criteria**:

1. [DEMO-04] The prototype SHALL disponibilizar Dashboard, Leads, Contatos, Empresas, Negócios e Notificações por uma navegação lateral.
2. [DEMO-05] WHEN o usuário pesquisar ou filtrar uma lista THEN o protótipo SHALL atualizar os registros visíveis sem recarregar a página.
3. [DEMO-06] WHEN o usuário criar, editar ou excluir um registro demonstrativo THEN o protótipo SHALL refletir a alteração na lista e nos indicadores relacionados.
4. [DEMO-07] WHEN o usuário recarregar a página THEN o protótipo SHALL restaurar o estado local previamente manipulado no mesmo navegador.
5. [DEMO-08] WHEN o usuário solicitar a restauração da demonstração THEN o protótipo SHALL substituir o estado local pelos dados fictícios originais.

**Independent Test**: navegar por todos os módulos, pesquisar, filtrar, cadastrar, editar, excluir, recarregar e restaurar os dados.

### P1: Pipelines e orçamentos demonstrativos ⭐ MVP

**User Story**: Como avaliador, quero experimentar os principais fluxos comerciais para validar o formato proposto para Leads e Negócios.

**Acceptance Criteria**:

1. [DEMO-09] The prototype SHALL representar os estados Em contato, Lead descartado e Lead convertido sem a etapa ornamental “Nome”.
2. [DEMO-10] WHEN o usuário converter um Lead THEN o protótipo SHALL encerrar o Lead como convertido e criar um novo Negócio demonstrativo em Em Contato.
3. [DEMO-11] The prototype SHALL representar as nove etapas funcionais aprovadas para a Pipeline de Negócios.
4. [DEMO-12] WHEN um Negócio entrar em Faturando THEN o protótipo SHALL simular a alteração do responsável para um integrante do grupo Faturamento e gerar uma notificação.
5. [DEMO-13] WHEN o usuário preencher itens de um orçamento THEN o protótipo SHALL recalcular o total e aceitar a seleção opcional de um PDF.

**Independent Test**: converter um Lead, percorrer etapas de um Negócio, entrar em Faturando e criar um orçamento com e sem PDF.

### P1: Simulação de acesso e comunicação de escopo ⭐ MVP

**User Story**: Como avaliador, quero alternar perfis para compreender a visibilidade planejada e distinguir a demonstração do produto final.

**Acceptance Criteria**:

1. [DEMO-14] WHEN o usuário alternar o perfil demonstrativo THEN o protótipo SHALL filtrar Leads e Negócios conforme responsabilidade, equipe ou participação como Assistente.
2. [DEMO-15] WHILE o protótipo estiver aberto o sistema SHALL exibir um aviso persistente de que os dados são fictícios e locais.
3. [DEMO-16] WHERE a interface for exibida em largura reduzida o protótipo SHALL manter navegação e ações principais utilizáveis.

**Independent Test**: alternar entre os quatro perfis e validar a interface em viewport desktop e móvel.

## Requirement Traceability

| Requirement | Task | Status |
| --- | --- | --- |
| DEMO-01 | T4, T5 | Pending |
| DEMO-02 | T1, T3, T4 | In Progress (T1 complete) |
| DEMO-03 | T2 | Complete |
| DEMO-04 | T2 | Complete |
| DEMO-05 | T2 | Complete |
| DEMO-06 | T2 | Complete |
| DEMO-07 | T2 | Complete |
| DEMO-08 | T2 | Complete |
| DEMO-09 | T2 | Complete |
| DEMO-10 | T2 | Complete |
| DEMO-11 | T2 | Complete |
| DEMO-12 | T2 | Complete |
| DEMO-13 | T2 | Complete |
| DEMO-14 | T2 | Complete |
| DEMO-15 | T2, T5 | In Progress (T2 complete) |
| DEMO-16 | T2 | Complete |

## Success Criteria

- [ ] O ambiente sobe com Docker Compose sem banco configurado.
- [ ] Todos os módulos demonstrativos são navegáveis.
- [ ] Os fluxos de Lead, Negócio, orçamento e notificação podem ser experimentados.
- [ ] O seletor de perfil altera a visibilidade percebida.
- [ ] O protótipo permanece utilizável em desktop e dispositivo móvel.
