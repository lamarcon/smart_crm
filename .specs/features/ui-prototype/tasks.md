# Protótipo Local do Smart CRM — Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `tlc-spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user - do not proceed without it.**

---

**Design**: `.specs/features/ui-prototype/design.md`  
**Status**: In Progress — remediation after independent validation

## Test Coverage Matrix

| Code layer | Required test | Evidence |
| --- | --- | --- |
| Python HTTP server | self-test | `server.py --self-test` |
| Static UI and browser state | Playwright browser regression + visual smoke | checked-in assertions and visual walkthrough |
| Container image | build + health | `docker build` and `/health` |
| Compose wiring | configuration + runtime | `docker compose config` and HTTP checks |
| Documentation | command verification | commands copied from README run successfully |

## Gate Check Commands

- **Quick**: `python app/server.py --self-test`
- **Full**: `python app/server.py --self-test` followed by `pnpm test`
- **Build**: `python scripts/verify_demo.py` followed by `pnpm test`

## Execution Plan

### Phase 1: Application

```text
T1 → T2
```

### Phase 2: Container

```text
T2 → T3 → T4
```

### Phase 3: Handoff

```text
T4 → T5
```

### Phase 4: Validation remediation

```text
T5 → T6 → T7 → T8
```

## Task Breakdown

### T1: Criar servidor local sem dependências ✅

**Status**: Complete — self-test e compilação Python aprovados em 2026-08-17.

**What**: Implementar o servidor HTTP, a rota de saúde, a entrega segura de arquivos e seu autoteste.
**Where**: `app/server.py`
**Depends on**: None
**Reuses**: biblioteca padrão do Python
**Requirement**: DEMO-02

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] `/health` retorna JSON saudável.
- [x] `/` resolve o documento do protótipo.
- [x] Caminhos fora do diretório estático são rejeitados.
- [x] O gate Quick termina com código zero.

**Tests**: self-test
**Gate**: quick
**Commit**: `feat(demo): add dependency-free web server`

### T2: Implementar a interface demonstrativa ✅

**Status**: Complete — gate Full, fluxo desktop e viewport móvel aprovados em 2026-08-17, sem erros no console.

**What**: Criar a aplicação autocontida com layout responsivo, dados fictícios e fluxos locais aprovados.
**Where**: `app/static/index.html`
**Depends on**: T1
**Reuses**: Pipelines e regras documentadas em `.specs/features/crm-mvp/spec.md`
**Requirement**: DEMO-03–DEMO-16

**Tools**:

- MCP: browser automation
- Skill: `tlc-spec-driven`, `browser:control-in-app-browser`

**Done when**:

- [x] Os seis destinos da navegação estão funcionais.
- [x] Busca, filtros, CRUD local e restauração atualizam a interface.
- [x] Conversão de Lead, etapas de Negócio, Faturando, orçamento e notificações funcionam.
- [x] O seletor dos quatro perfis altera a visibilidade de Leads e Negócios.
- [x] O aviso de ambiente demonstrativo é persistente.
- [x] O gate Full termina com código zero.

**Tests**: structural + browser smoke
**Gate**: full
**Commit**: `feat(demo): build interactive CRM interface`

### T3: Empacotar a aplicação ✅

**Status**: Complete — imagem construída, processo não privilegiado e healthcheck `healthy` em 2026-08-17.

**What**: Definir uma imagem pequena e não privilegiada para executar o servidor do protótipo.
**Where**: `Dockerfile`
**Depends on**: T2
**Reuses**: imagem oficial Python slim
**Requirement**: DEMO-01, DEMO-02

**Tools**:

- MCP: Docker CLI
- Skill: `tlc-spec-driven`

**Done when**:

- [x] A imagem copia apenas os arquivos necessários.
- [x] O processo executa como usuário não privilegiado.
- [x] A imagem declara healthcheck para `/health`.
- [x] A construção termina com código zero.

**Tests**: build + health
**Gate**: build
**Commit**: `build(demo): add application container`

### T4: Configurar a execução local ✅

**Status**: Complete — Compose válido, serviço `healthy` e respostas HTTP 200 em `localhost:8080` em 2026-08-17.

**What**: Publicar o container em `localhost:8080` sem banco ou dependências externas.
**Where**: `compose.yaml`
**Depends on**: T3
**Reuses**: `Dockerfile`
**Requirement**: DEMO-01, DEMO-02

**Tools**:

- MCP: Docker Compose CLI
- Skill: `tlc-spec-driven`

**Done when**:

- [x] `docker compose config` é válido.
- [x] O serviço sobe em segundo plano.
- [x] `/health` e `/` respondem em `localhost:8080`.
- [x] O gate Build termina com código zero.

**Tests**: configuration + runtime
**Gate**: build
**Commit**: `build(demo): add local compose service`

### T5: Documentar uso e limitações ✅

**Status**: Complete — comandos do README conferidos contra o container saudável em 2026-08-17.

**What**: Explicar como iniciar, acessar, restaurar e encerrar o protótipo e distinguir a demonstração do MVP de produção.
**Where**: `README.md`
**Depends on**: T4
**Reuses**: comandos validados no gate Build
**Requirement**: DEMO-01, DEMO-15

**Tools**:

- MCP: NONE
- Skill: `tlc-spec-driven`

**Done when**:

- [x] Os comandos de início, logs e encerramento estão documentados.
- [x] A URL local e a restauração dos dados estão explicadas.
- [x] As limitações sem banco, integrações e segurança estão explícitas.
- [x] O gate Build permanece verde.

**Tests**: command verification
**Gate**: build
**Commit**: `docs: explain local CRM prototype`

### T6: Preparar a suíte de navegador

**What**: Declarar o Playwright, o comando de testes e as exclusões de artefatos locais necessárias para uma suíte reproduzível.
**Where**: `package.json`
**Depends on**: T5
**Reuses**: Chrome instalado no ambiente local
**Requirement**: DEMO-03–DEMO-16

**Tools**:

- MCP: package manager
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] A dependência de desenvolvimento e o script `test` estão declarados.
- [ ] O lockfile está versionável e `node_modules`/caches estão ignorados.
- [ ] O Playwright pode abrir o Chrome local em modo headless.

**Tests**: toolchain smoke
**Gate**: quick
**Commit**: `test(demo): add browser test toolchain`

### T7: Corrigir e testar os fluxos interativos

**What**: Restringir o Gestor à sua equipe e persistir asserções de navegador para todos os comportamentos DEMO-03 a DEMO-16.
**Where**: `app/static/index.html`
**Depends on**: T6
**Reuses**: massa fictícia, fluxos e seletores acessíveis já implementados
**Requirement**: DEMO-03–DEMO-16

**Tools**:

- MCP: Playwright
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Administrador vê tudo e Gestor não vê o registro fora da equipe Vendas CMS.
- [ ] A suíte cobre navegação, busca, CRUD, recarga, restauração, Pipelines, conversão, Faturando, orçamento, perfis, aviso e viewport móvel.
- [ ] As conjunções de conversão, Faturando e orçamento validam o payload completo.
- [ ] O gate Full termina com código zero.

**Tests**: browser regression
**Gate**: full
**Commit**: `test(demo): cover interactive CRM flows`

### T8: Automatizar o gate do Compose

**What**: Criar um verificador que constrói e sobe o Compose, aguarda saúde e afirma porta, payload e documento raiz.
**Where**: `scripts/verify_demo.py`
**Depends on**: T7
**Reuses**: `compose.yaml` e `/health`
**Requirement**: DEMO-01, DEMO-02

**Tools**:

- MCP: Docker Compose CLI
- Skill: `tlc-spec-driven`

**Done when**:

- [ ] Configuração, build e startup retornam sucesso.
- [ ] A rota de saúde possui o payload exato esperado.
- [ ] A raiz responde HTTP 200 e contém o marcador do Smart CRM.
- [ ] O gate Build termina com código zero.

**Tests**: integration gate
**Gate**: build
**Commit**: `test(demo): automate compose acceptance gate`

## Phase Execution Map

```text
Phase 1: T1 → T2
Phase 2:      T2 → T3 → T4
Phase 3:                T4 → T5
Phase 4:                     T5 → T6 → T7 → T8
```

## Task Granularity Check

| Task | Scope | Status |
| --- | --- | --- |
| T1 | um servidor Python | Granular |
| T2 | um documento de aplicação autocontido | Coeso para o protótipo |
| T3 | uma definição de imagem | Granular |
| T4 | uma definição Compose | Granular |
| T5 | um documento de uso | Granular |
| T6 | uma configuração de ferramenta de teste | Coeso |
| T7 | uma correção de permissão com sua suíte de regressão | Coeso por dependência de teste |
| T8 | um verificador de integração | Granular |

## Diagram-Definition Cross-Check

| Task | Depends on | Diagram | Status |
| --- | --- | --- | --- |
| T1 | None | início | Match |
| T2 | T1 | T1 → T2 | Match |
| T3 | T2 | T2 → T3 | Match |
| T4 | T3 | T3 → T4 | Match |
| T5 | T4 | T4 → T5 | Match |
| T6 | T5 | T5 → T6 | Match |
| T7 | T6 | T6 → T7 | Match |
| T8 | T7 | T7 → T8 | Match |

## Test Co-location Validation

| Task | Layer | Matrix requires | Task says | Status |
| --- | --- | --- | --- | --- |
| T1 | servidor | self-test | self-test | OK |
| T2 | interface | structural + browser smoke | structural + browser smoke | OK |
| T3 | imagem | build + health | build + health | OK |
| T4 | Compose | configuration + runtime | configuration + runtime | OK |
| T5 | documentação | command verification | command verification | OK |
| T6 | test toolchain | toolchain smoke | toolchain smoke | OK |
| T7 | interface | browser regression | browser regression | OK |
| T8 | Compose | integration gate | integration gate | OK |
