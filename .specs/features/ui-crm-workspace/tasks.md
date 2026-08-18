# Evolução da Área de Trabalho do CRM — Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user - do not proceed without it.**

---

**Design**: `.specs/features/ui-crm-workspace/design.md`  
**Status**: In Progress

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec. Guidelines found: `README.md`, `package.json`, `.specs/features/ui-prototype/tasks.md`; no separate contributor or coverage policy, so strong defaults apply.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| --- | --- | --- | --- | --- |
| Feature specifications and task structure | structural | Valid spec, dependency parity, Tests/Gate in every task and Conventional Commit messages | `.specs/features/ui-crm-workspace/*.md` | TLC validators |
| Browser state and domain behavior | e2e | All branches changed by the task; 1:1 evidence for mapped ACs and listed edge cases | `tests/ui-prototype.spec.cjs` | `pnpm test` |
| UI renderers and interactions | e2e | Desktop and 390×844 happy paths, protected transitions, empty and invalid states | `tests/ui-prototype.spec.cjs` | `pnpm test` |
| Python static server | self-test | Existing route, path-safety and static-file behavior remain green | `app/server.py --self-test` | `python app/server.py --self-test` |
| Compose/runtime integration | integration | Image builds, sole service becomes healthy, `/health` payload and root marker remain exact | `scripts/verify_demo.py` | `python scripts/verify_demo.py` |
| Documentation | none | Commands and feature description match the validated runtime | `README.md` | Build gate only |

## Gate Check Commands

> Generated from the existing repository commands. Commands on the same row run sequentially.

| Gate Level | When to Use | Command |
| --- | --- | --- |
| Quick | Planning or server-only checks | `python app/server.py --self-test` |
| Full | Any browser state, behavior or UI change | `python app/server.py --self-test`; `pnpm test` |
| Build | Final documentation and integration | `python scripts/verify_demo.py`; `pnpm test` |

## Execution Plan

### Phase 1: Workspace evolution

```text
T1 → T2 → T3 → T4 → T5 → T6 → T7
```

## Task Breakdown

### T1: Registrar o plano aprovado

**Status**: Complete — validadores estruturais e self-test aprovados em 2026-08-18.

**What**: Consolidar contexto, especificação, design, tarefas e rastreabilidade aprovados para a evolução do workspace.
**Where**: `.specs/features/ui-crm-workspace/`
**Depends on**: None
**Reuses**: `.specs/features/ui-prototype/`
**Requirement**: DRAWER-01–DASH-08

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] `validate_spec.py` termina com zero erros e zero avisos.
- [x] `validate_tasks.py` termina com zero erros.
- [x] O design e o contexto constam como aprovados.
- [x] A rastreabilidade mapeia os 36 requisitos.

**Tests**: structural
**Gate**: quick
**Commit**: `docs(spec): plan CRM workspace evolution`

### T2: Preparar o estado e os metadados do workspace

**What**: Adicionar registry de campos, datas ISO, histórico mínimo e preferências normalizadas sem invalidar estados locais existentes.
**Where**: `app/static/index.html`
**Depends on**: T1
**Reuses**: `seedState`, `loadState`, `saveState`, `canSee`
**Requirement**: FILTER-03, FILTER-12, BOARD-05, DASH-04

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Estados novos e antigos recebem `state.ui` e datas ISO determinísticas.
- [ ] O registry descreve os campos pesquisáveis e filtráveis dos quatro módulos.
- [ ] O carregamento corrompido continua restaurando a massa inicial.
- [ ] Testes de navegador cobrem normalização e preservação após recarga.
- [ ] O gate Full passa com pelo menos 16 casos de navegador.

**Tests**: e2e
**Gate**: full
**Commit**: `feat(demo): prepare workspace state metadata`

### T3: Editar registros no painel lateral

**What**: Substituir a edição pelo lápis por um painel lateral acionado pelo nome nos quatro módulos.
**Where**: `app/static/index.html`
**Depends on**: T2
**Reuses**: `entityFields`, `fieldHTML`, `saveEntity`
**Requirement**: DRAWER-01–DRAWER-06

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Nomes de Leads, Contatos, Empresas e Negócios abrem o drawer correto.
- [ ] Salvar atualiza a visualização ativa e Cancelar não altera o registro.
- [ ] Fechar dados alterados exige confirmação.
- [ ] O drawer ocupa a tela inteira em 390×844.
- [ ] O caso CRUD antigo usa o nome clicável e preserva suas asserções de resultado.
- [ ] O gate Full passa com pelo menos 19 casos de navegador.

**Tests**: e2e
**Gate**: full
**Commit**: `feat(demo): edit records in side drawer`

### T4: Adicionar filtros configuráveis

**What**: Implementar motor tipado, painel configurável, combinações `E`/`OU` e filtros nomeados para os módulos de cadastro.
**Where**: `app/static/index.html`
**Depends on**: T3
**Reuses**: `listShell`, funções de visibilidade e `localStorage`
**Requirement**: FILTER-01–FILTER-12

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Busca livre cobre todos os valores textuais definidos no registry.
- [ ] Campos podem ser adicionados, removidos e redefinidos.
- [ ] Texto, seleção múltipla, datas e números aplicam os operadores especificados.
- [ ] Responsável, período e etapa funcionam simultaneamente sem furar permissões.
- [ ] Filtros nomeados podem ser salvos, reabertos e excluídos por usuário/módulo.
- [ ] Combinação vazia e filtro incompatível exibem os estados previstos.
- [ ] O gate Full passa com pelo menos 24 casos de navegador.

**Tests**: e2e
**Gate**: full
**Commit**: `feat(demo): add configurable record filters`

### T5: Adicionar Pipeline visual e Kanban

**What**: Criar barra segmentada, Lista/Kanban e controlador transacional de etapas para Leads e Negócios.
**Where**: `app/static/index.html`
**Depends on**: T4
**Reuses**: `changeDealStage`, `convertLead`, `discardLead`, Pipelines fixas
**Requirement**: BOARD-01–BOARD-10

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Lista e Kanban preservam filtros e a última escolha do módulo.
- [ ] A barra segmentada expõe exatamente as etapas aprovadas.
- [ ] O Kanban agrupa cards e permite mudança de etapa por drag-and-drop ou controle acessível.
- [ ] Transições comuns oferecem `Desfazer` atômico.
- [ ] Faturando, encerramentos, descarte e conversão exigem a guarda especificada.
- [ ] O Kanban mantém rolagem e ações em 390×844.
- [ ] O gate Full passa com pelo menos 29 casos de navegador.

**Tests**: e2e
**Gate**: full
**Commit**: `feat(demo): add pipeline list and kanban views`

### T6: Filtrar o Dashboard comercial

**What**: Reutilizar o motor de filtros no Dashboard com escopos Todos, Leads e Negócios e indicadores recalculados.
**Where**: `app/static/index.html`
**Depends on**: T5
**Reuses**: `renderDashboard`, motor de filtros e `canSee`
**Requirement**: DASH-01–DASH-08

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Os três escopos expõem somente campos aplicáveis.
- [ ] Responsável, equipe, período e etapa recalculam cards, Pipeline e movimentações.
- [ ] Gestor vê somente membros e resultados da própria equipe.
- [ ] Redefinir restaura o conjunto permitido ao perfil atual.
- [ ] O gate Full passa com pelo menos 32 casos de navegador.

**Tests**: e2e
**Gate**: full
**Commit**: `feat(demo): add analytical dashboard filters`

### T7: Documentar e validar o workspace evoluído

**What**: Atualizar a documentação de uso, conferir regressão completa e executar o gate de Compose sobre a versão final.
**Where**: `README.md`
**Depends on**: T6
**Reuses**: comandos e limitações já documentados
**Requirement**: DRAWER-01–DASH-08

**Tools**:

- MCP: Docker Compose CLI
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] README descreve drawer, filtros, Lista/Kanban e Dashboard filtrável.
- [ ] O Compose sobe somente o serviço `crm` e fica saudável.
- [ ] O payload de `/health` permanece exato.
- [ ] Todos os casos antigos e novos passam sem skips.
- [ ] O gate Build passa com pelo menos 32 casos de navegador e 7 checks de integração.

**Tests**: integration
**Gate**: build
**Commit**: `docs: explain enhanced CRM workspace`

## Phase Execution Map

```text
Phase 1: T1 → T2 → T3 → T4 → T5 → T6 → T7
```

## Task Granularity Check

| Task | Scope | Status |
| --- | --- | --- |
| T1 | um pacote de planejamento da feature | ✅ Coeso |
| T2 | uma fundação de estado e metadados | ✅ Coeso |
| T3 | um componente de edição | ✅ Granular |
| T4 | um componente de filtros e seu motor inseparável | ✅ Coeso |
| T5 | um componente de Pipeline com controlador de transição | ✅ Coeso |
| T6 | uma integração do motor existente ao Dashboard | ✅ Granular |
| T7 | um documento de uso com gate de entrega | ✅ Granular |

## Diagram-Definition Cross-Check

| Task | Depends On | Diagram Shows | Status |
| --- | --- | --- | --- |
| T1 | None | início | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 | ✅ Match |
| T4 | T3 | T3 → T4 | ✅ Match |
| T5 | T4 | T4 → T5 | ✅ Match |
| T6 | T5 | T5 → T6 | ✅ Match |
| T7 | T6 | T6 → T7 | ✅ Match |

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| --- | --- | --- | --- | --- |
| T1 | specs/tasks | structural | structural | ✅ OK |
| T2 | browser state/domain | e2e | e2e | ✅ OK |
| T3 | browser UI/domain | e2e | e2e | ✅ OK |
| T4 | browser UI/domain | e2e | e2e | ✅ OK |
| T5 | browser UI/domain | e2e | e2e | ✅ OK |
| T6 | browser UI/domain | e2e | e2e | ✅ OK |
| T7 | docs/runtime | integration | integration | ✅ OK |
