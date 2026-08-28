# Persistência do Smart CRM no PostgreSQL - Validation

**Result**: PASS ✅
**Date**: 2026-08-28
**Spec**: .specs/features/postgres-crm-persistence/spec.md
**Diff range**: 23c42c0..917fe7d
**Verified HEAD**: 917fe7d2cbad490f9e9ac163032cbc2fdb89d624
**Verifier**: independent sub-agent (author ≠ verifier)

---

## Summary

A implementação atende os 23 critérios de aceitação e os 6 edge cases. Os cinco gaps anteriores foram fechados: status/head migrado, ordem temporal de confirmação/cache, reidratação por reload/contexto independente/sessão real, saves simultâneos e whitespace.

**Spec-anchored check**: 23/23 ACs com o resultado exato da spec; 0 gaps; 0 spec-precision gaps.
**Edge cases**: 6/6 comprovados.
**Gate**: 82 backend + 65 UI + 47 Compose = 194 checks aprovados; 0 falhas; 0 skips.
**Sensor outcome**: 3/3 mutantes mortos; 0 sobreviventes; isolamento confirmado.

---

## Task Completion

| Task | Status | Notes |
| --- | --- | --- |
| T1 | ✅ Done | Runtime e compile gate. |
| T2 | ✅ Done | Sessão, rollback e health. |
| T3 | ✅ Done | Modelo normalizado e constraints. |
| T4 | ✅ Done | Migração do zero, ciclo, idempotência e probe. |
| T5 | ✅ Done | Contrato, referências e contagens. |
| T6 | ✅ Done | Round-trip, reconciliação e soft delete. |
| T7 | ✅ Done | Serviço versionado e concorrência. |
| T8 | ✅ Done | HTTP, limite, 503 e errorId. |
| T9 | ✅ Done | Bootstrap, DB-wins e fallback. |
| T10 | ✅ Done | Mutações duráveis, rollback e recovery. |
| T11 | ✅ Done | Imagem aceita no Compose. |
| T12 | ✅ Done | Compose válido e volume preservado. |
| T13 | ✅ Done | 47 checks Compose. |
| T14 | ✅ Done | Workflow documentado. |
| T15 | ✅ Done | Status/head/round-trip real. |
| T16 | ✅ Done | Ordem versão/cache/toast. |
| T17 | ✅ Done | Reload/contexto/sessão real. |
| T18 | ✅ Done | Dois saves simultâneos. |
| T19 | ✅ Done | git diff --check verde. |

---

## Spec-Anchored Acceptance Criteria

| AC | Spec-defined outcome | file:line + assertion expression | Status |
| --- | --- | --- | --- |
| DBP-01 | Migrações versionadas criam todas as tabelas e workspace no head atual. | tests/backend/test_models.py:33 — assert set(Base.metadata.tables) == EXPECTED_TABLES; tests/backend/test_migrations.py:55-57 — tabelas presentes, workspace == ("default", 0, None), head == "9f7a2c31d5e8". | ✅ PASS |
| DBP-02 | Bootstrap confirmado valida e persiste atomicamente no banco vazio. | tests/backend/test_workspace_service.py:83-85 — versão 1, contagens e estado exatos; :230-231 — referência inválida mantém initialized is False; tests/ui-prototype.spec.cjs:265-280 — Admin gate e api.version == 1. | ✅ PASS |
| DBP-03 | Bootstrap retorna 201 e oito contagens exatas. | tests/backend/test_api.py:187-188 — status_code == 201 e JSON exato; tests/ui-prototype.spec.cjs:281 — deepEqual das oito contagens. | ✅ PASS |
| DBP-04 | Registro/vínculo/campo inválido retorna 422 sem dados parciais. | tests/backend/test_api.py:215-217 — 422, path e mensagem exatos; tests/backend/test_workspace_service.py:230-231 — mesmo path e workspace não inicializado. | ✅ PASS |
| DBP-05 | Segundo bootstrap retorna 409 sem alterar dados. | tests/backend/test_api.py:199-201 — 409/currentVersion 7; tests/backend/test_workspace_service.py:93-94 — conflito na versão 1 e load.version == 1. | ✅ PASS |
| DBP-06 | Corpo acima de 25 MB retorna 413 antes da transação. | tests/backend/test_api.py:229-231 e :243-245 — 413, payload_too_large e service.calls == [] para Content-Length e stream. | ✅ PASS |
| DBP-07 | UI carrega estado/versão da API antes de liberar alterações. | tests/ui-prototype.spec.cjs:265-266 — writable false antes; :291-292 — valor canônico e writable true depois. | ✅ PASS |
| DBP-08 | Save válido é atômico e incrementa exatamente um. | tests/backend/test_workspace_service.py:119 — (version, name) == (2, "Alterado"); :146-152 — um save, versão final 2 e estado inteiro do vencedor; :249 — falha mantém (1, "Empresa"). | ✅ PASS |
| DBP-09 | Confirmação visual/cache somente após nova versão persistida. | tests/ui-prototype.spec.cjs:353-355 — com PUT retido: versão igual, toast count 0 e cache anterior; :357-363 — após resposta: toast, versão/cache +1 e Lead na API. | ✅ PASS |
| DBP-10 | Versão antiga retorna 409/currentVersion sem alterar banco. | tests/backend/test_workspace_service.py:163-164 — current_version == 2 e nome permanece Lead; tests/backend/test_api.py:271-272 — 409/currentVersion 8; tests/ui-prototype.spec.cjs:400-401 — canônico presente e candidato ausente. | ✅ PASS |
| DBP-11 | Falha parcial reverte e retorna errorId sem dados parciais. | tests/backend/test_workspace_service.py:246-249 — exceção forçada e (version, company) == (1, "Empresa"); tests/backend/test_api.py:403-406 — 500/persistence_error/UUID v4/mesmo ID no log. | ✅ PASS |
| DBP-12 | Exclusão preenche deleted_at, oculta ativo e preserva vínculos. | tests/backend/test_repository.py:148-149 — deleted_at is not None e lista ativa; :170-171 — filhos preservados; tests/ui-prototype.spec.cjs:412-413 — versão +1 e assistente preservada no excluído. | ✅ PASS |
| DBP-13 | Restore limpa deleted_at e recupera vínculos. | tests/backend/test_repository.py:160 — deleted_at is None; tests/backend/test_workspace_service.py:193-194 — versão 3 e ("L-1", ["u-2"]); tests/ui-prototype.spec.cjs:421-422 — versão +2 e assistente restaurada. | ✅ PASS |
| DBP-14 | Migração/recarga preserva todos os módulos, valores, status e vínculos. | tests/backend/test_repository.py:88 — agregado deep-equal; :108-113 — Ativo/Pendente/Inativo/Cancelado exatos; :233 — nova sessão rehydrated == original; tests/backend/test_schemas.py:104-106 — vazios/Bitrix/settings exatos. | ✅ PASS |
| DBP-15 | Presets, Lista/Kanban e configuração de campos persistem no escopo correto. | tests/backend/test_repository.py:200-201 — settings/ui deep-equal; tests/ui-prototype.spec.cjs:788-796 — preset user/scope/filtro/data + reidratação; :853-858 — Kanban após reload/contexto. | ✅ PASS |
| DBP-16 | Navegador mantém apenas cache confirmado e estado transitório. | tests/ui-prototype.spec.cjs:373-377 — versão igual, perfil/filtro locais, currentUserId e filtersByUser ausentes da API; :302-304 — cache read-only e aviso exato. | ✅ PASS |
| DBP-17 | Todos os fluxos listados sobrevivem a reload e contexto independente. | tests/ui-prototype.spec.cjs:160 e :191 — helper exige deepEqual após reload e em contexto independente; chamadas após criar/editar :552, converter :1139, etapa/undo :916, orçamento :1193, CSV :1359, campos :1811, preferências :796/:858, notificações :1164 e usuários :1895; tests/backend/test_repository.py:228-233 — nova sessão PostgreSQL. | ✅ PASS |
| DBP-18 | Recriação da app/restart do PostgreSQL preservam contagens e valores. | scripts/verify_demo.py:430-435 — versão/marcador após recriar CRM; :439-446 — probe/versão após restart; :469-478 — versão/marcador/probe após recuperação. | ✅ PASS |
| DBP-19 | /health com DB retorna 200 e ok/ok. | tests/backend/test_api.py:137-138 — 200 e JSON exato; scripts/verify_demo.py:363-364 — mesmos valores no Compose. | ✅ PASS |
| DBP-20 | /health sem DB retorna 503 e degraded/unavailable. | tests/backend/test_api.py:150-151 — 503 e JSON exato; scripts/verify_demo.py:449-455 — payload exato com PostgreSQL parado. | ✅ PASS |
| DBP-21 | Carga falha com cache válido: read-only e aviso exato. | tests/ui-prototype.spec.cjs:302-306 — valor do cache, banner exato, writable false e modal fechado; :311-314 — seed read-only sem cache. | ✅ PASS |
| DBP-22 | Gravação falha: restaura último confirmado e mostra mensagem exata. | tests/ui-prototype.spec.cjs:385-390 — espera "Não foi possível salvar no banco.", estado deep-equal, versão e cache inalterados. | ✅ PASS |
| DBP-23 | Erro de persistência registra/devolve o mesmo errorId. | tests/backend/test_api.py:385-388 — 503, UUID v4 e errorId in caplog.text; scripts/verify_demo.py:456-460 — ID na resposta e nos logs Compose. | ✅ PASS |

**Coverage status**: ✅ 23/23 ACs matched; 0 gaps; 0 spec-precision gaps.

---

## Edge Cases

| Edge case | Evidence | Status |
| --- | --- | --- |
| Banco vazio sem local válido oferece seed para confirmação. | tests/ui-prototype.spec.cjs:265-281 — diálogo/bloqueio, Admin confirma, versão 1 e contagens exatas. | ✅ PASS |
| Dois navegadores salvam a mesma versão; um vence, outro conflita. | tests/backend/test_workspace_service.py:146-152 — outcomes conflict/saved, versão 2 e estado completo do vencedor. | ✅ PASS |
| Campo oculto global preserva valores sem reaparecer. | tests/ui-prototype.spec.cjs:1589-1602 — chave oculta, valores/visibilidade deep-equal e campo/opção ausentes. | ✅ PASS |
| Bitrix adicional vazio preserva definição e valor. | tests/backend/test_schemas.py:104-106 — ["", False, []], Bitrix/settings exatos; tests/ui-prototype.spec.cjs:1353-1358 — valor vazio e visibility key preservados. | ✅ PASS |
| Referência inexistente retorna 422 com path. | tests/backend/test_api.py:215-217 — 422, path leads[0].responsibleId e mensagem exata. | ✅ PASS |
| Restaurar demo substitui massa, versão +1 e preserva schema. | tests/backend/test_workspace_service.py:173-174 — versão 2/estado substituído; tests/backend/test_migrations.py:55-57 — tabelas/head; tests/ui-prototype.spec.cjs:1107-1116 — massa restaurada. | ✅ PASS |

---

## Gate Check

- **Commands**: python -m compileall -q app; docker compose config --quiet; python -m pytest tests/backend -q; SMART_CRM_TEST_URL=http://127.0.0.1:8090/ pnpm test; python scripts/verify_demo.py.
- **Compile**: PASS.
- **Compose config**: PASS.
- **Backend**: 82 passed, 0 failed, 0 skipped; 1 warning Pydantic.
- **UI**: 65 passed, 0 failed; API interceptada; servidor 127.0.0.1:8090 encerrado.
- **Compose acceptance**: 47 passed, 0 failed; head 9f7a2c31d5e8; volume/probe preservados; serviços healthy.
- **Aggregate**: 194 passed, 0 failed, 0 skipped.
- **Before/after**: 55 UI + 0 backend → 65 UI + 82 backend = +92 testes; nenhum arquivo removido.
- **Whitespace**: git diff --check 23c42c0..HEAD PASS.
- **Environment**: binários Python/Node do runtime Codex; pytest com basetemp fora do worktree.

---

## Discrimination Sensor

Worktree destacado em test-results/postgres-mutant; nunca git stash. Scratch removido. Porcelain real vazio antes e depois.

| Mutation | Scratch file:line | Fault | Discriminating assertion | Status |
| --- | --- | --- | --- | --- |
| M1 | migrations/versions/9f7a2c31d5e8_align_crm_user_statuses.py:25 | Removeu Cancelado do head Alembic. | tests/backend/test_migrations.py:65-68 exigiu os quatro status e falhou. | ✅ Killed |
| M2 | app/services/workspace.py:122 | Incremento += 1 → += 2. | tests/backend/test_workspace_service.py:147 esperava [2, 2], recebeu [3, 3]. | ✅ Killed |
| M3 | app/static/index.html:901 | Flush de toast antes de aguardar PUT. | tests/ui-prototype.spec.cjs:354 esperava count 0, recebeu 1. | ✅ Killed |

**Sensor depth**: lightweight, 3 mutações comportamentais de alto risco.
**Sensor outcome**: 3/3 killed; 0 survived; PASS ✅.
**Isolation**: git status --porcelain=v1 --untracked-files=all vazio antes/depois; somente o worktree real permanece.

---

## Code Quality

| Principle | Status | Evidence |
| --- | --- | --- |
| Minimum code / no unnecessary flexibility | ✅ | Agregado versionado aprovado; correções T15–T19 focadas. |
| Surgical changes / no scope creep | ✅ | Status, testes de ordem/rehidratação/concorrência, whitespace e artefatos TLC. |
| Matches patterns | ✅ | Alembic, SQLAlchemy, pytest e Playwright seguem padrões existentes. |
| Spec-anchored outcomes | ✅ | 23/23 ACs citam asserts dos valores/estados definidos. |
| Per-layer coverage | ✅ | Schema/migration, repository/service, HTTP, browser e Compose exercitados. |
| Every test claimed | ✅ | Testes novos mapeiam ACs e edge concorrente; regressão preservada. |
| Test integrity | ✅ | 55 → 65 UI; 0 → 82 backend; sem remoção, skip ou disable. |
| Whitespace/style | ✅ | git diff --check sem saída. |
| Guidelines | ✅ | README.md, tasks.md e coding-principles.md aplicados. |

---

## Prior Gap Closure

| Prior gap | Evidence | Status |
| --- | --- | --- |
| Status domain and migration head | tests/backend/test_models.py:107-110; test_migrations.py:57-68; test_repository.py:108-113. | ✅ Closed |
| Temporal confirmation/cache order | tests/ui-prototype.spec.cjs:343-363; M3 morto. | ✅ Closed |
| Reload + independent context + real session | tests/ui-prototype.spec.cjs:155-193 e chamadas em todos os fluxos; test_repository.py:228-233. | ✅ Closed |
| Simultaneous saves | tests/backend/test_workspace_service.py:122-152; M2 morto. | ✅ Closed |
| Whitespace | git diff --check 23c42c0..HEAD exit 0. | ✅ Closed |

---

## Requirement Traceability

| Requirements | Verified state |
| --- | --- |
| DBP-01–DBP-23 | ✅ Verified |

O verifier não alterou spec.md; a tabela registra somente o resultado independente.

---

## Final Assessment

**Overall**: ✅ Ready.
**Gaps**: none.
**Lessons**: clean PASS sem sinal; nenhuma lição registrada.