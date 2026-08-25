# Global Drawer Hide Action Validation — PASS

**Date**: 2026-08-25  
**Spec**: `.specs/features/global-drawer-hide-action/spec.md`  
**Diff range**: `74f0912..d40ceaa`  
**Verifier**: independent sub-agent (author ≠ verifier)

---

## Validation — PASS

Os 6 critérios de aceitação e os 3 casos de borda têm evidência spec-anchored. Todos os gates passaram e as duas mutações comportamentais foram mortas.

## Spec-Anchored Acceptance Criteria

| Critério | Resultado definido pela spec | `file:line` + expressão exata da asserção | Resultado |
| --- | --- | --- | --- |
| AC1 — Administrador vê o `×` com nome acessível exato | Um único controle visível, com `aria-label="Ocultar campo em todos os cadastros"` | `tests/ui-prototype.spec.cjs:1276` — `assert.equal(await globalHide.count(), 1)`; `tests/ui-prototype.spec.cjs:1277` — `assert.equal(await globalHide.getAttribute('aria-label'), 'Ocultar campo em todos os cadastros')` | ✅ PASS |
| AC2 — clique grava a chave uma vez e oculta globalmente de cards e seletor | `hiddenCustomFieldKeys === [schema.key]`; campo ausente do seletor e de outro card | `tests/ui-prototype.spec.cjs:1282` — `assert.deepEqual(saved.moduleFieldSettings.deals.hiddenCustomFieldKeys, [schema.key])`; `tests/ui-prototype.spec.cjs:1285` — `assert.equal(await drawer.locator('#drawerAddCustomField option[value="test:x-global"]').count(), 0)`; `tests/ui-prototype.spec.cjs:1295` — `assert.equal(await drawer.getByLabel('Campo global pelo x').count(), 0)` | ✅ PASS |
| AC3 — valores e visibilidade individual de todos os registros são preservados | Os vetores pós-clique são idênticos aos snapshots pré-clique | `tests/ui-prototype.spec.cjs:1283` — `assert.deepEqual(saved.deals.map(deal => deal.customFields[0].value), valuesBefore)`; `tests/ui-prototype.spec.cjs:1284` — `assert.deepEqual(saved.deals.map(deal => deal.visibleCustomFieldKeys), visibilityBefore)` | ✅ PASS |
| AC4 — reativação restaura a visibilidade individual anterior | Configuração global volta a `[]`; o primeiro registro recupera valor; o segundo continua individualmente oculto e disponível para adição | `tests/ui-prototype.spec.cjs:1303` — `assert.deepEqual((await stateFrom(page)).moduleFieldSettings.deals.hiddenCustomFieldKeys, [])`; `tests/ui-prototype.spec.cjs:1306` — `assert.equal(await drawer.getByLabel('Campo global pelo x').inputValue(), valuesBefore[0])`; `tests/ui-prototype.spec.cjs:1310` — `assert.equal(await drawer.getByLabel('Campo global pelo x').count(), 0)`; `tests/ui-prototype.spec.cjs:1311` — `assert.equal(await drawer.locator('#drawerAddCustomField option[value="test:x-global"]').count(), 1)` | ✅ PASS |
| AC5 — não Administrador não vê nem executa a ação direta | Nenhum controle; chamada retorna `false`; configuração permanece byte-equivalente | `tests/ui-prototype.spec.cjs:1332` — `assert.equal(await drawer.locator('[data-action="hide-custom-field"]').count(), 0)`; `tests/ui-prototype.spec.cjs:1334` — `assert.equal(await page.evaluate(key => hideDrawerCustomField(key), schema.key), false)`; `tests/ui-prototype.spec.cjs:1335` — `assert.equal(JSON.stringify((await stateFrom(page)).moduleFieldSettings.deals), settingsBefore)` | ✅ PASS |
| AC6 — conclusão mostra a mensagem exata | Toast exato `Campo <nome> ocultado em todos os cadastros.` fica visível | `tests/ui-prototype.spec.cjs:1279` — `await page.locator('#toastRegion').getByText('Campo Campo global pelo x ocultado em todos os cadastros.', { exact: true }).waitFor()` | ✅ PASS |

**Status**: 6/6 ACs cobertos; 0 lacunas de precisão da spec.

## Edge Cases

| Caso de borda | Resultado definido pela spec | `file:line` + expressão exata da asserção | Resultado |
| --- | --- | --- | --- |
| Último campo ocultado | Aba `Campos adicionais` oculta e aba `Informações` ativa | `tests/ui-prototype.spec.cjs:1286` — `assert.equal(await drawer.getByRole('tab', { name: 'Campos adicionais' }).isHidden(), true)`; `tests/ui-prototype.spec.cjs:1287` — `assert.equal(await drawer.getByRole('tab', { name: 'Informações' }).getAttribute('aria-selected'), 'true')` | ✅ PASS |
| Chave inexistente | Ação retorna `false` e configuração permanece `[schema.key]` | `tests/ui-prototype.spec.cjs:1289` — `assert.equal(await page.evaluate(() => hideDrawerCustomField('test:inexistente')), false)`; `tests/ui-prototype.spec.cjs:1290` — `assert.deepEqual((await stateFrom(page)).moduleFieldSettings.deals.hiddenCustomFieldKeys, [schema.key])` | ✅ PASS |
| Chave já oculta | Segunda ação retorna `false` e mantém uma única ocorrência | `tests/ui-prototype.spec.cjs:1288` — `assert.equal(await page.evaluate(key => hideDrawerCustomField(key), schema.key), false)`; `tests/ui-prototype.spec.cjs:1290` — `assert.deepEqual((await stateFrom(page)).moduleFieldSettings.deals.hiddenCustomFieldKeys, [schema.key])` | ✅ PASS |

## Gate Check

| Gate | Resultado |
| --- | --- |
| UI regression — bundled Node, `tests/ui-prototype.spec.cjs` contra `http://localhost:8080` | ✅ 55 passed, 0 failed, 0 skipped |
| `scripts/verify_demo.py` — bundled Python | ✅ 17 passed, 0 failed |
| `app/server.py --self-test` — bundled Python | ✅ `server self-test: ok` |
| `validate_spec.py .specs/features/global-drawer-hide-action/spec.md --root D:\Develop_CRM_Project` | ✅ 0 errors, 0 warnings |
| `git diff --check 74f0912..d40ceaa` | ✅ exit 0, sem saída |

- **Contagem antes da feature**: 53 cenários registrados no commit `74f0912`.
- **Contagem depois da feature**: 55 cenários executados em `d40ceaa`.
- **Delta**: +2 cenários; asserções reconhecidas passaram de 406 para 421 (+15).
- **Skips**: nenhum mecanismo de skip/disable encontrado no escopo.
- **Falhas**: nenhuma no baseline real.

## Discrimination Sensor

| Mutação | Local | Falha injetada | Evidência de morte | Resultado |
| --- | --- | --- | --- | --- |
| M1 — autorização | `app/static/index.html:1578` | `if (currentUser().role !== 'Administrador') return false;` → `if (false) return false;` | XHIDE-02 falhou em `tests/ui-prototype.spec.cjs:1334`, `true !== false`; suíte mutante: 54 passed, 1 failed | ✅ Killed |
| M2 — persistência | `app/static/index.html:1588` | `settings.hiddenCustomFieldKeys = [...new Set([...hidden, key])]` → `settings.hiddenCustomFieldKeys = [...hidden]` | XHIDE-01 falhou em `tests/ui-prototype.spec.cjs:1282`, `[]` ≠ `[schema.key]`; suíte mutante: 54 passed, 1 failed | ✅ Killed |

**Sensor depth**: lightweight, 2 mutações comportamentais em worktrees temporárias destacadas em `d40ceaa`.  
**Isolamento**: nenhum `git stash`; worktrees removidas; portas temporárias 18081 e 18082 fechadas; porcelain real antes e depois idêntico (`""`).  
**Resultado**: 2/2 mutações mortas — PASS.

## Code Quality

| Princípio | Resultado | Evidência |
| --- | --- | --- |
| Código mínimo e sem abstração prematura | ✅ | Mudança localizada em `customFieldHTML` e `hideDrawerCustomField`; reutiliza `saveState`, `renderDrawerCustomFields`, `setDrawerTab` e `toast` existentes. |
| Alteração cirúrgica e sem scope creep | ✅ | Superfície funcional limitada a `app/static/index.html`; testes limitados a `tests/ui-prototype.spec.cjs`; demais arquivos do diff são a spec e seu contexto. |
| Padrões e estilo existentes | ✅ | Mantém funções locais, estado em `localStorage`, guard de papel e renderização imperativa já usados no protótipo. |
| Payload/conjunções assertados por valor | ✅ | Chave persistida, vetores preservados, texto exato, `aria-label`, visibilidade e estado de abas são comparados por valor. |
| Cobertura happy + edge + error | ✅ | XHIDE-01 cobre fluxo global e reversão; XHIDE-02 cobre negação; os três casos de borda têm asserções específicas. |
| Cada teste em escopo é reclamado pela spec | ✅ | XHIDE-01 mapeia AC1–AC4, AC6 e bordas; XHIDE-02 mapeia AC5. |
| Ausência de enfraquecimento injustificado | ✅ | O bloco removido de ADM-02 exercitava a ocultação individual substituída pela nova decisão global. A cobertura foi realocada para XHIDE-01/XHIDE-02, com +2 cenários e +15 asserções líquidas. |
| `SPEC_DEVIATION` e skips | ✅ | Nenhuma ocorrência no escopo. |
| Diretrizes do projeto | ✅ | `README.md:83`–`README.md:89` define regressão UI e `verify_demo.py`; `coding-principles.md` aplicado como gate independente. |

## Requirement Traceability

| Requirement | Evidência | Resultado |
| --- | --- | --- |
| XHIDE-01 — ocultação imediata e global | AC1, AC2, AC6 e bordas acima | ✅ Verified |
| XHIDE-02 — preservação e reversão | AC3 e AC4 acima | ✅ Verified |
| XHIDE-03 — autorização e bordas | AC5 e três bordas acima | ✅ Verified |

A spec permanece sem alteração no worktree real, conforme o escopo do Verifier.

## Summary

**Overall**: ✅ Ready  
**Spec-anchored check**: 6/6 ACs e 3/3 edge cases correspondem ao resultado definido  
**Sensor**: 2/2 mutações mortas  
**Gate**: 5/5 comandos passaram  
**Issues found**: nenhum  
**Lessons**: nenhuma registrada; PASS limpo não produz lição.
