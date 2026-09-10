# CRM Relationship Cards Specification

## Problem Statement

O botão para criar Empresa gera uma entidade inválida e não abre o cadastro. As listagens de Negócios, Contatos e Empresas também não apresentam os vínculos comerciais com detalhes suficientes para identificar rapidamente as pessoas e organizações relacionadas.

## Goals

- [x] Permitir criar uma Empresa pela tela de Empresas e persistir o novo registro.
- [x] Exibir os vínculos entre Negócios, Contatos e Empresas nas listagens e no Kanban de Negócios.

## Out of Scope

| Feature | Reason |
| --- | --- |
| Migração para chaves estrangeiras | O workspace atual relaciona registros por nome e esta correção deve ser compatível com os dados existentes. |
| Alteração automática dos vínculos ao renomear registros | Exige uma política de integridade separada. |
| Deploy no servidor | Esta etapa altera e valida apenas o código local. |

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Forma de relacionar registros | Comparação de nomes sem diferenciar maiúsculas e espaços externos | Mantém compatibilidade com o estado persistido atual sem alterar o banco. | y |
| Densidade da informação | Resumo textual compacto dentro da tabela e do card Kanban | Mostra as informações pedidas sem criar uma nova navegação. | y |
| Vínculo ausente | Mostrar `Não informado`, `Cadastro não localizado` ou `Nenhum contato` conforme o contexto | Evita tela vazia e deixa a ausência explícita. | y |
| Navegação entre entidades | Os resumos não serão clicáveis nesta entrega | O pedido exige visibilidade; navegação cruzada fica fora do escopo. | y |
| Demais dimensões implícitas | N/A para autenticação, concorrência, dependências externas e ciclo de vida | A entrega só renderiza estado já carregado e reutiliza a persistência existente. | y |

**Open questions:** none - all resolved or logged above.

## User Stories

### P1: Criar Empresa

**User Story**: Como usuário do CRM, quero abrir e concluir o cadastro de Empresa para registrar uma nova organização.

**Why P1**: O fluxo principal está quebrado.

**Acceptance Criteria**:

1. WHEN o usuário acionar `Novo Empresa` na página Empresas THEN the system SHALL abrir o formulário `Novo Empresa` com os campos de Empresa.
2. WHEN o usuário preencher os campos obrigatórios e salvar THEN the system SHALL persistir uma Empresa com identificador `E-*` e exibi-la na listagem.

**Independent Test**: Criar uma Empresa pela interface, confirmar o novo registro na tabela e recarregar o workspace.

### P1: Visualizar vínculos comerciais

**User Story**: Como usuário do CRM, quero ver Empresa e Contato nos registros relacionados para reconhecer o contexto comercial sem abrir vários cadastros.

**Why P1**: Os vínculos são essenciais para entender cada oportunidade e organização.

**Acceptance Criteria**:

1. WHILE um Negócio tiver Empresa e Contato cadastrados, the system SHALL mostrar os nomes da Empresa e do Contato, o e-mail e telefone do Contato e a cidade e telefone da Empresa na listagem de Negócios.
2. WHILE um Negócio tiver Empresa e Contato cadastrados, the system SHALL mostrar os nomes da Empresa e do Contato no card do Kanban de Negócios.
3. WHILE um Contato tiver Empresa informada, the system SHALL mostrar o nome dessa Empresa na listagem de Contatos.
4. WHILE uma Empresa tiver Contatos associados, the system SHALL mostrar a quantidade e os nomes desses Contatos na listagem de Empresas.
5. IF um Negócio referenciar um Contato ou uma Empresa sem cadastro correspondente THEN the system SHALL manter os nomes informados e mostrar `Cadastro não localizado` para os detalhes ausentes.
6. IF uma Empresa não tiver Contatos associados THEN the system SHALL mostrar `Nenhum contato` na listagem de Empresas.

**Independent Test**: Conferir um Negócio vinculado e um vínculo sem cadastro na Lista/Kanban, depois conferir as relações nas páginas Contatos e Empresas.

## Edge Cases

- IF um nome relacionado contiver diferenças de maiúsculas ou espaços externos THEN the system SHALL localizar o cadastro correspondente.
- IF o nome da Empresa ou do Contato estiver vazio THEN the system SHALL mostrar `Não informado`.

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| CRREL-01 | P1: Criar Empresa | Execute | Verified |
| CRREL-02 | P1: Criar Empresa | Execute | Verified |
| CRREL-03 | P1: Visualizar vínculos | Execute | Verified |
| CRREL-04 | P1: Visualizar vínculos | Execute | Verified |
| CRREL-05 | P1: Visualizar vínculos | Execute | Verified |
| CRREL-06 | P1: Visualizar vínculos | Execute | Verified |
| CRREL-07 | P1: Visualizar vínculos | Execute | Verified |
| CRREL-08 | P1: Visualizar vínculos | Execute | Verified |

**Coverage:** 8 total, 8 mapped to inline execution steps, 0 unmapped.

## Success Criteria

- [x] Uma Empresa pode ser criada e continua presente após recarregar o workspace.
- [x] Lista e Kanban de Negócios exibem o contexto de Empresa e Contato sem erro para vínculos ausentes.
- [x] Listagens de Contatos e Empresas exibem suas relações cruzadas.
