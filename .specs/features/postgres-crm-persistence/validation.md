# Persistência do Smart CRM no PostgreSQL - Validation

**Result**: FAIL ❌
**Date**: 2026-08-28
**Spec**: `.specs/features/postgres-crm-persistence/spec.md`
**Diff range**: `23c42c0..23c664c`
**Verified HEAD**: `23c664cb6aa303f0ef5931e76612c8e4bbc24650`
**Verifier**: independent sub-agent (author ≠ verifier)

---

## Summary

O build gate e o sensor passaram, mas a feature não atende integralmente a spec. O modelo e a migração aceitam apenas `Ativo`, `Convidado` e `Inativo`, enquanto a interface grava `Pendente` e `Cancelado`. Esses fluxos passam no Playwright porque a suíte intercepta toda a API e não exerce a constraint PostgreSQL. DBP-09 e DBP-17 também não possuem a evidência temporal/cross-context exigida. O edge case de duas gravações simultâneas não foi testado.

**Spec-anchored check**: 20/23 ACs com resultado exato comprovado; 3 gaps; 0 spec-precision gaps.
**Edge cases**: 5/6 comprovados; 1 gap.
**Sensor**: 3/3 mutantes mortos.
**Gate**: 78 backend + 64 UI + 47 Compose = 189 checks aprovados; 0 falhas; 0 skips.

---

## Task Completion

| Task | Status | Notes |
| --- | --- | --- |
| T1 | ✅ Done | Runtime declarado; compile e gates executados. |
| T2 | ✅ Done | Boundary de sessão, rollback e health cobertos. |
| T3 | ⚠️ Partial | `app/models.py:80` define domínio de status incompatível com a interface. |
| T4 | ⚠️ Partial | `migrations/versions/be40ea4d21ad_create_normalized_crm_schema.py:118` materializa a constraint incompatível. |
| T5 | ✅ Done | Contrato e referências cobertos, mas não protegem o domínio de status do banco. |
| T6 | ⚠️ Partial | Round-trip geral passa somente com usuários `Ativo`; `Pendente`/`Cancelado` falham na constraint. |
| T7 | ✅ Done | Versão, conflito, rollback, reset e restore cobertos. |
| T8 | ✅ Done | Rotas, erros, limite e health cobertos. |
| T9 | ✅ Done | Bootstrap, DB-wins e fallback read-only cobertos. |
| T10 | ⚠️ Partial | Fluxo de usuários quebra no PostgreSQL; DBP-09/17 carecem de prova completa. |
| T11 | ✅ Done | Imagem construída e aceita pelo gate Compose. |
| T12 | ✅ Done | Compose válido; volume preservado; serviços saudáveis. |
| T13 | ✅ Done | Aceitação Compose terminou com 47 checks e preservou o volume. |
| T14 | ✅ Done | Workflow persistente documentado. |

---

## Spec-Anchored Acceptance Criteria

| AC | Spec-defined outcome | `file:line` + assertion expression | Result |
| --- | --- | --- | --- |
| DBP-01 | Migrações versionadas criam todas as tabelas normalizadas e workspace de controle. | `tests/backend/test_models.py:33` — `assert set(Base.metadata.tables) == EXPECTED_TABLES`; `tests/backend/test_migrations.py:55-57` — `assert set(Base.metadata.tables).issubset(tables)`, `assert tuple(workspace) == ("default", 0, None)`, `assert ... == "be40ea4d21ad"`. | ✅ PASS |
| DBP-02 | Bootstrap confirmado persiste o agregado validado atomicamente no banco vazio. | `tests/backend/test_workspace_service.py:82-84` — `assert result.version == 1`, `assert result.counts... == {...}`, `assert result.state... == state_data()`; `tests/ui-prototype.spec.cjs:218-234` — dialog/Admin/contagens e `assert.equal(api.version, 1)`. | ✅ PASS |
| DBP-03 | Bootstrap retorna 201 e contagens exatas dos oito grupos. | `tests/backend/test_api.py:187-189` — `assert response.status_code == 201`, `assert response.json() == {"version": 1, "counts": COUNTS, "state": STATE_DATA}`; `tests/backend/test_schemas.py:112` — igualdade exata das contagens. | ✅ PASS |
| DBP-04 | Referência inválida retorna 422 e não deixa dados parciais. | `tests/backend/test_api.py:215-217` — 422, path e mensagem exatos; `tests/backend/test_workspace_service.py:196-197` — `assert error.value.path == "leads[0].responsibleId"`, `assert workspace.load().initialized is False`. | ✅ PASS |
| DBP-05 | Segundo bootstrap retorna 409 e não altera o workspace. | `tests/backend/test_api.py:199-201` — 409 e `currentVersion == 7`; `tests/backend/test_workspace_service.py:92-93` — conflito na versão 1 e `assert workspace.load().version == 1`. | ✅ PASS |
| DBP-06 | Corpo acima de 25 MB retorna 413 antes da transação/serviço. | `tests/backend/test_api.py:229-231` e `:243-245` — `assert response.status_code == 413`, código `payload_too_large`, `assert service.calls == []`. | ✅ PASS |
| DBP-07 | Interface carrega estado/versão da API antes de liberar alterações. | `tests/ui-prototype.spec.cjs:243-245` — `assert.equal(loaded.leads[0].name, canonical.leads[0].name)` e writable `true`; `:219` comprova writable `false` antes do bootstrap. | ✅ PASS |
| DBP-08 | Save válido é atômico e incrementa a versão exatamente uma vez. | `tests/backend/test_workspace_service.py:118` — `assert (result.version, result.state.leads[0]["name"]) == (2, "Alterado")`; `:212-215` — exceção intermediária mantém `(version, company) == (1, "Empresa")`. | ✅ PASS |
| DBP-09 | Confirmação visual aparece somente após a nova versão persistida. | **No evidence.** O teste rotulado DBP-09 em `tests/ui-prototype.spec.cjs:270-277` só observa versão/estado depois de uma resposta imediata; não segura o PUT nem afirma ausência de toast antes da resposta. A implementação ordena versão/cache/render/toast em `app/static/index.html:901-912`, mas evidence-or-zero exige assert comportamental. | ❌ GAP |
| DBP-10 | Versão antiga retorna 409 com versão atual e não altera o banco. | `tests/backend/test_workspace_service.py:127-130` — conflito, `current_version == 2` e nome canônico `Lead`; `tests/backend/test_api.py:271-272` — 409 e `currentVersion == 8`. | ✅ PASS |
| DBP-11 | Falha parcial faz rollback e retorna errorId sem dados parciais. | `tests/backend/test_workspace_service.py:212-215` — falha forçada mantém versão 1 e empresa `Empresa`; `tests/backend/test_api.py:403-407` — 500, `persistence_error`, UUID v4 no log e segredo ausente da resposta. | ✅ PASS |
| DBP-12 | Exclusão preenche `deleted_at`, oculta ativo e preserva vínculos. | `tests/backend/test_repository.py:123-124` — `deleted_at is not None` e lista ativa `['L-1']`; `:145-146` — assistente e dois campos externos permanecem; `tests/ui-prototype.spec.cjs:342-343` — versão +1 e vínculo do assistente no excluído. | ✅ PASS |
| DBP-13 | Restore limpa exclusão e recupera vínculos. | `tests/backend/test_repository.py:135` — `deleted_at is None`; `tests/backend/test_workspace_service.py:159-160` — versão 3 e `("L-1", ["u-2"])`; `tests/ui-prototype.spec.cjs:351-352` — versão +2 e assistente restaurado. | ✅ PASS |
| DBP-14 | Migração/recarga preserva por valor todos os módulos, usuários e vínculos. | A evidência positiva `tests/backend/test_repository.py:88` (`assert ... == original`) usa apenas status `Ativo`. O domínio real contradiz o fluxo: `app/models.py:80` e `migrations/...py:118` aceitam somente `Ativo/Convidado/Inativo`, enquanto `tests/ui-prototype.spec.cjs:1742-1744` e `:1787-1788` exigem `Pendente` e `Cancelado`. O mock da UI não toca o banco. | ❌ FAIL |
| DBP-15 | Presets, Lista/Kanban e configurações de campos persistem no escopo correto. | `tests/backend/test_repository.py:175-176` — igualdade exata de `moduleFieldSettings` e `ui`; `tests/ui-prototype.spec.cjs:714-720` — nome/user/scope/filtro/data do preset; `:778` — preferência `deals == 'kanban'`. | ✅ PASS |
| DBP-16 | Browser mantém somente cache confirmado e estado transitório local. | `tests/ui-prototype.spec.cjs:303-307` — versão inalterada, perfil/filtro locais e ausência de `currentUserId`/`filtersByUser` na API; `:255-257` — cache confirmado read-only com aviso exato. | ✅ PASS |
| DBP-17 | Todos os fluxos listados sobrevivem a recarga e outro contexto. | **No complete evidence.** `tests/ui-prototype.spec.cjs:291-292` prova segundo contexto apenas para criação de Lead e `:1020-1024` prova recarga apenas desse fluxo. Conversão (`:1052-1058`), etapa (`:826-836`), orçamento (`:1095-1110`), CSV (`:1191-1244`) e campos (`:1687-1704`) não são reabertos em outro contexto após cada ação. | ❌ GAP |
| DBP-18 | Recriação da aplicação e restart do PostgreSQL preservam contagens/valores. | `scripts/verify_demo.py:429-435` — versão e marcador após recriar CRM; `:444-446` — versão após restart PostgreSQL; `:468-473` — versão e marcador após recuperação. Gate executado: 47/47. | ✅ PASS |
| DBP-19 | `/health` com banco retorna 200, `status: ok`, `database: ok`. | `tests/backend/test_api.py:137-138` — status 200 e JSON exato; `scripts/verify_demo.py:363-364` — os mesmos valores em Compose. | ✅ PASS |
| DBP-20 | `/health` sem banco retorna 503, `degraded/unavailable`. | `tests/backend/test_api.py:150-151` — status 503 e JSON exato; `scripts/verify_demo.py:449-455` — payload degradado em Compose com PostgreSQL parado. | ✅ PASS |
| DBP-21 | Falha de carga usa cache válido read-only e aviso exato. | `tests/ui-prototype.spec.cjs:255-259` — valor vem do cache, banner `Banco indisponível. Alterações bloqueadas.`, writable `false` e modal de criação não abre; `:264-267` cobre fallback seed sem cache. | ✅ PASS |
| DBP-22 | Falha de gravação restaura estado confirmado e mostra mensagem exata. | `tests/ui-prototype.spec.cjs:316-320` — mensagem exata, igualdade profunda com estado anterior, versão inalterada e cache na versão anterior. | ✅ PASS |
| DBP-23 | Erro de persistência registra e devolve o mesmo errorId. | `tests/backend/test_api.py:385-389` — 503, UUID v4 e `errorId in caplog.text`; `scripts/verify_demo.py:456-460` — errorId presente na resposta e nos logs Compose. | ✅ PASS |

**Status**: ❌ 20/23 ACs matched; 3 gaps; 0 spec-precision gaps.

---

## Edge Cases

| Edge case | Evidence | Result |
| --- | --- | --- |
| Banco vazio sem local válido oferece seed para confirmação. | `tests/ui-prototype.spec.cjs:210-234` — novo contexto, dialog visível, escrita bloqueada, Admin confirma e contagens exatas chegam à API. | ✅ PASS |
| Dois navegadores salvam a mesma versão simultaneamente; só um vence. | **No evidence.** `tests/backend/test_workspace_service.py:96-109` testa concorrência apenas de bootstrap. `:121-130` testa save obsoleto de forma sequencial, não duas gravações concorrentes. | ❌ GAP |
| Campo personalizado oculto globalmente preserva valor sem reaparecer. | `tests/ui-prototype.spec.cjs:1504-1523` — hidden key gravada, valores/visibilidade individuais idênticos e campo ausente do drawer. | ✅ PASS |
| Bitrix adicional vazio preserva definição e valor vazio. | `tests/backend/test_schemas.py:104-106` — `['', False, []]`, headers e settings exatos; `tests/ui-prototype.spec.cjs:1204-1227` — header `Campo vazio` e custom value `''`. | ✅ PASS |
| Referência inexistente retorna 422 com path inválido. | `tests/backend/test_api.py:215-217` — status, path e mensagem exatos. | ✅ PASS |
| Restaurar demo substitui massa em transação, versão +1 e preserva esquema. | `tests/backend/test_workspace_service.py:139-140` — versão 2 e estado substituído; `tests/ui-prototype.spec.cjs:1033-1035` — massa exatamente restaurada; `tests/backend/test_migrations.py:55-57` comprova esquema/head. | ✅ PASS |

---

## Discrimination Sensor

O sensor usou worktree destacado em `test-results/postgres-mutant`, nunca `git stash`. O scratch foi removido ao final. O porcelain real era vazio antes e permaneceu vazio depois.

| Mutation | Scratch file:line | Description | Discriminating assertion | Result |
| --- | --- | --- | --- | --- |
| M1 | `app/services/workspace.py:122` | `workspace.version += 1` → `+= 2`. | `tests/backend/test_workspace_service.py:118` esperava `(2, 'Alterado')`; `:139` esperava versão 2. | ✅ Killed (2 failed) |
| M2 | `app/repositories/workspace.py:219` | Inverteu soft delete: `id not in present` → `id in present`. | `tests/backend/test_repository.py:123` esperava `deleted_at is not None`. | ✅ Killed (1 failed, 1 passed) |
| M3 | `app/main.py:37` | Limite 25 MB → 26 MB. | `tests/backend/test_api.py:229` e `:243` esperavam 413; receberam 422. | ✅ Killed (2 failed) |

**Sensor depth**: lightweight, 3 mutações de alto risco.
**Sensor outcome**: 3/3 killed — PASS ✅.
**Isolation**: baseline real `git status --porcelain=v1 --untracked-files=all` = vazio; após cleanup = vazio.

---

## Gate Check

- **Build commands**: `python -m compileall -q app`; `docker compose config --quiet`; `python -m pytest tests/backend -q`; `SMART_CRM_TEST_URL=http://127.0.0.1:8090/ pnpm test`; `python scripts/verify_demo.py`.
- **Environment adaptation**: o runtime Windows não expunha `python`/`node` no PATH elevado. Os mesmos módulos/comandos foram executados com os binários já instalados do runtime Codex. Pytest usou `--basetemp` fora do worktree por permissão do `%TEMP%`.
- **Compile**: PASS.
- **Compose config**: PASS.
- **Backend**: 78 passed, 0 failed, 0 skipped; 1 warning Pydantic.
- **UI**: 64 passed, 0 failed, servidor temporário 8090 encerrado após o gate.
- **Compose acceptance**: 47 passed, 0 failed; volume preservado; serviços terminaram healthy.
- **Aggregate**: 189 passed, 0 failed, 0 skipped.
- **Test count before feature**: 55 UI, 0 backend = 55.
- **Test count after feature**: 64 UI + 78 backend = 142.
- **Delta**: +87 testes automatizados; o verifier Compose contém 47 checks adicionais.
- **Integrity**: nenhum teste removido; UI 55 → 64; nenhum skip/disable encontrado.
- **Initial harness retries**: descartadas da contagem final. Falharam antes de asserts por alias de Python/Node e permissão de `%TEMP%`; a execução canônica final passou.

---

## Code Quality

| Principle | Status | Evidence |
| --- | --- | --- |
| Minimum code / no unnecessary flexibility | ✅ | Componentes seguem o agregado versionado aprovado. |
| Surgical changes / no scope creep | ✅ | Diff limitado à persistência, testes, Compose e documentação da feature. |
| Matches patterns | ❌ | Domínio de status diverge entre UI (`Pendente`, `Cancelado`) e PostgreSQL (`Ativo`, `Convidado`, `Inativo`). |
| Spec-anchored asserted values | ❌ | DBP-09 e DBP-17 não possuem asserts completos do resultado temporal/cross-context. |
| Per-layer coverage expectation | ❌ | Playwright intercepta a API; nenhum teste real cobre os estados de usuário nem todos os fluxos em reload/segundo contexto. |
| Every test claimed | ✅ | Testes novos mapeiam ACs, edge cases ou Done-when; regressão legada mapeia preservação dos fluxos. |
| Test integrity | ✅ | Contagem aumentou; nenhum skip, deleção ou assert enfraquecido identificado. |
| Documented guidelines | ✅ | Gates de `README.md` e `tasks.md` executados. |
| Whitespace gate | ❌ | `git diff --check 23c42c0..23c664c` falha em `migrations/...py:4` (trailing whitespace) e `pyproject.toml:30` (blank line at EOF). |

---

## Fix Plans

### Fix 1: Alinhar o domínio de status de usuário

- **Root cause**: modelo/migração usam `Convidado`, enquanto a interface usa `Pendente` e `Cancelado`.
- **Fix task**: criar nova revisão Alembic que substitua a constraint pelos valores efetivamente emitidos; alinhar o model; adicionar round-trip real para `Ativo`, `Pendente`, `Inativo` e `Cancelado`.
- **Where**: `app/models.py:80`, nova revisão em `migrations/versions/`, testes de repositório/API.
- **Priority**: Major.

### Fix 2: Provar a ordem de confirmação DBP-09

- **Root cause**: mock responde imediatamente; o teste não observa o intervalo antes da resposta.
- **Fix task**: atrasar controladamente o PUT, afirmar ausência de toast/cache confirmado antes da liberação e afirmar nova versão + toast somente depois.
- **Where**: `tests/ui-prototype.spec.cjs`.
- **Priority**: Major.

### Fix 3: Completar a matriz de persistência DBP-17

- **Root cause**: somente criação de Lead é verificada em recarga e segundo contexto; os demais fluxos terminam no mesmo contexto e usam API mockada.
- **Fix task**: exercitar criação, edição, conversão, etapa, orçamento, CSV e campos contra API/PostgreSQL reais; reabrir cada resultado após reload e em segundo contexto.
- **Where**: testes e2e/integration de persistência.
- **Priority**: Major.

### Fix 4: Cobrir duas gravações simultâneas

- **Root cause**: existe concorrência de bootstrap e conflito sequencial, mas não save concorrente com a mesma versão.
- **Fix task**: disparar dois saves paralelos no mesmo schema e exigir um sucesso, um `WorkspaceConflict/currentVersion`, versão +1 e apenas o estado vencedor.
- **Where**: `tests/backend/test_workspace_service.py`.
- **Priority**: Major.

### Fix 5: Limpar whitespace do range

- **Root cause**: espaços finais no cabeçalho da migration e linha vazia final no `pyproject.toml`.
- **Fix task**: remover apenas os dois desvios e exigir `git diff --check` verde.
- **Priority**: Minor.

---

## Requirement Traceability Update

O verifier não alterou `spec.md`; esta tabela registra o estado recomendado.

| Requirement | Previous | Verified state |
| --- | --- | --- |
| DBP-01–08 | Complete | ✅ Verified |
| DBP-09 | Complete | ❌ Needs Fix |
| DBP-10–13 | Complete | ✅ Verified |
| DBP-14 | Complete | ❌ Needs Fix |
| DBP-15–16 | Complete | ✅ Verified |
| DBP-17 | Complete | ❌ Needs Fix |
| DBP-18–23 | Complete | ✅ Verified |

---

## Final Assessment

**Overall**: ❌ Not Ready.

**What works**: schema/migration base, transações, versão otimista sequencial, soft delete/restore, limite 25 MB, health/degraded, cache read-only, rollback visual, persistência em recreação/restart e errorId correlacionado.

**Blocking gaps**: domínio de status incompatível com o PostgreSQL; DBP-09 sem prova temporal; DBP-17 sem cobertura real completa; edge de save concorrente sem evidência.

**Next step**: implementar Fixes 1–4, limpar whitespace e repetir o Verifier completo. O sensor atual não possui mutantes sobreviventes.
