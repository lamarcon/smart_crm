# Validation: GitHub Release Deployment - PASS ✅

**Verdict**: PASS ✅
**Date**: 2026-10-22
**Spec**: `.specs/features/github-release-deployment/spec.md`
**Diff range**: `23ab7b0^..HEAD` (`23ab7b0..0f72680`)
**Verifier**: independent sub-agent (author != verifier)

O Build passou, os 16 critérios têm assertions alinhadas ao outcome da spec e as três mutações foram mortas.

---

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| T1 | ✅ Done | Builder aceita versão segura e preserva fallback para SHA. |
| T2 | ✅ Done | Workflow versiona, testa, constrói e publica dois assets. |
| T3 | ✅ Done | Stager valida metadados, digest, manifesto e promoção lado a lado. |
| T4 | ✅ Done | Runbook documenta publicação, staging e fronteira de cutover. |
| T5 | ✅ Done | Gaps independentes foram fechados com testes de falha, saída e concorrência. |

Todas as tarefas estão marcadas como concluídas. Nenhuma está bloqueada ou parcial.

---

## Spec-Anchored Acceptance Criteria

| Criterion | Spec-defined outcome | `file:line` + assertion expression | Result |
| --------- | -------------------- | ---------------------------------- | ------ |
| Publish AC1 / GRD-01 | Tag é exatamente `v` + `APP_VERSION` antes dos artefatos. | `tests/backend/test_github_release_delivery.py:245` - `assert "from app.version import APP_VERSION" in workflow`; `:246-249` - tag esperada, comparação e ordem antes dos testes | ✅ PASS |
| Publish AC2 / GRD-02 | Todos os testes backend e UI antecedem publicação. | `tests/backend/test_github_release_delivery.py:232-239` - release depende de quality e testes Windows precedem build; `:260-262` - backend/UI/build precedem publish | ✅ PASS |
| Publish AC3 / GRD-03 | ZIP e SHA-256 usam nomes exatos e digest dos bytes. | `tests/backend/test_github_release_delivery.py:168-170` - nomes exatos e conteúdo do digest igual a `sha256(archive)` + nome | ✅ PASS |
| Publish AC4 / GRD-04 | Falha em validação, teste ou build impede publicação. | `tests/backend/test_github_release_delivery.py:248-250` - validação antecede teste; `:260-262` - testes e build antecedem publish; `:270` - upload alternativo ausente | ✅ PASS |
| Publish AC5 / GRD-05 | Release da tag existente recebe exatamente ZIP e SHA-256. | `tests/backend/test_github_release_delivery.py:265-270` - paths exatos, dois assets, `--verify-tag`, sem clobber/upload; `:276-278` - release existente é recusada antes de create | ✅ PASS |
| Stage AC1 / GRD-06 | Consulta somente release pública da tag em `lamarcon/smart_crm`, sem token. | `tests/backend/test_github_release_delivery.py:620-622` - endpoint e repositório exatos; ausência de `Authorization` | ✅ PASS |
| Stage AC2 / GRD-07 | Draft, prerelease, tag divergente e assets ambíguos falham antes da extração. | `tests/backend/test_github_release_delivery.py:299-325` - matriz dos metadados inválidos e `assert result.returncode != 0` na função de validação | ✅ PASS |
| Stage AC3 / GRD-08 | Nome e SHA-256 externos correspondem exatamente ao arquivo de digest. | `tests/backend/test_github_release_delivery.py:340-341` - sucesso e SHA real; `:344-365` - formato, nome e hash divergentes retornam não zero | ✅ PASS |
| Stage AC4 / GRD-09 | Extrai em staging, valida manifesto e só então promove. | `tests/backend/test_github_release_delivery.py:380-384` - final, payload e ausência de staging; `:422-426` - manifesto adulterado não cria final, preserva estado e remove staging | ✅ PASS |
| Stage AC5 / GRD-10 | Pasta final preexistente bloqueia sem alteração. | `tests/backend/test_github_release_delivery.py:400-402` - retorno não zero, marcador intacto e nenhuma staging | ✅ PASS |
| Stage AC6 / GRD-11 | Falhas de download, hash, extração ou manifesto limpam temporários e preservam configuração/releases; tarefa e bancos não são mutados. | `tests/backend/test_github_release_delivery.py:153-157` - helper afirma final ausente, release e `server.env` intactos e ausência de resíduos; `:474-478`, `:501-504`, `:529-532`, `:422-426` aplicam os outcomes a download, hash, extração e manifesto; `:623-632` proíbe comandos de tarefa, banco e escrita de configuração | ✅ PASS |
| Stage AC7 / GRD-12 | Sucesso informa tag, hash e caminho final sem segredo. | `tests/backend/test_github_release_delivery.py:553-560` - retorno zero, dicionário exato de `Tag`, `Sha256`, `ReleaseRoot` e sentinel secreto ausente; `:562` - `RELEASE_STAGED=PASS` exigido | ✅ PASS |
| Edge AC1 / GRD-13 | Tag inválida/path-like é rejeitada antes de caminhos/URLs. | `tests/backend/test_github_release_delivery.py:281-286` - matriz inválida, retorno não zero e mensagem `formato vX.Y.Z` | ✅ PASS |
| Edge AC2 / GRD-14 | GitHub indisponível/release inexistente falha antes da pasta final. | `tests/backend/test_github_release_delivery.py:442-447` - erro de API, mensagem esperada, final ausente e download root não criado | ✅ PASS |
| Edge AC3 / GRD-15 | Digest malformado, divergente ou de outro nome falha antes da extração. | `tests/backend/test_github_release_delivery.py:344-365` - três digests inválidos e `assert result.returncode != 0` | ✅ PASS |
| Edge AC4 / GRD-16 | Duas execuções concorrentes produzem exatamente um vencedor sem overwrite/resíduo. | `tests/backend/test_github_release_delivery.py:599-614` - barreira sincroniza dois processos; assertions exigem um sucesso, uma falha, payload íntegro e nenhuma staging | ✅ PASS |

**Status**: ✅ 16/16 critérios cobertos; 0 gaps e 0 spec-precision gaps. A tabela de rastreabilidade possui 16 IDs one-to-one em `.specs/features/github-release-deployment/spec.md:91-110`.

---

## Discrimination Sensor

As mutações foram aplicadas somente em `.verifier-sensor-scratch`, uma extração isolada de `HEAD`. O scratch foi removido após os testes.

| Mutation | File:line | Description | Relevant assertion | Killed? |
| -------- | --------- | ----------- | ------------------ | ------- |
| 1 | `deploy/manual-windows-pg11/stage-github-release.ps1:222` | Removeu o cleanup do diretório temporário de download. | `tests/backend/test_github_release_delivery.py:157` exige ausência de `release-*` após falha. | ✅ Killed: 1 failed |
| 2 | `deploy/manual-windows-pg11/stage-github-release.ps1:216` | Alterou a tag final de `v0.3.0` para `v9.9.9`. | `tests/backend/test_github_release_delivery.py:555-559` exige payload exato. | ✅ Killed: 1 failed |
| 3 | `deploy/manual-windows-pg11/stage-github-release.ps1:180` | Substituiu promoção atômica por cópia com overwrite, permitindo dois vencedores. | `tests/backend/test_github_release_delivery.py:610-611` exige exatamente um sucesso e uma falha. | ✅ Killed: 1 failed |

**Sensor depth**: lightweight, 3 mutações focadas nos fixes de maior risco.
**Sensor outcome**: 3/3 killed - PASS ✅.
**Isolation**: `git status --porcelain` após cleanup corresponde exatamente ao baseline anterior. O baseline já continha mudanças/untracked de outros trabalhos; nenhuma foi alterada.

---

## Interactive UAT

Não executado. Esta feature é infraestrutura/backend; checks automatizados são suficientes.

---

## Code Quality

| Principle | Status | Evidence |
| --------- | ------ | -------- |
| Minimum code | ✅ | O fix adiciona fixtures locais e seis testes dirigidos aos gaps, sem alterar o stager. |
| Surgical changes | ✅ | `0f72680` modifica somente spec, tasks e o arquivo de testes da feature. |
| No scope creep | ✅ | Nenhuma ativação, migração, segredo, commit remoto ou deploy foi adicionado. |
| Matches patterns | ✅ | Reusa subprocessos PowerShell 5.1, fixtures locais e promoção lado a lado. |
| Spec-anchored outcome check | ✅ | 16/16 outcomes têm assertion do valor/estado exigido. |
| Payload/conjunction rule | ✅ | GRD-11 cobre quatro classes de falha e preservação; GRD-12 afirma todos os campos e ausência do sentinel. |
| Per-layer Coverage Expectation | ✅ | Builder/workflow têm contratos estáticos; stager cobre happy, metadata, digest, API, download, extração, manifesto, duplicidade e concorrência. |
| Every test maps to spec/edge/done-when | ✅ | Os 41 casos novos mapeiam aos 16 ACs ou ao fallback SHA do Done-when de T1. |
| Test integrity | ✅ | Nenhum teste anterior foi removido ou enfraquecido; o arquivo novo coleta 41 casos. |
| Documented guidelines | ✅ | `pyproject.toml`, `package.json`, `README.md` e `.specs/features/github-release-deployment/tasks.md:16-35`; sem `AGENTS.md`. |

Observação de hygiene: `git diff --check 23ab7b0^..HEAD` ainda sinaliza os quatro EOFs porque o range termina no commit `HEAD` e não inclui a limpeza ainda não commitada. A checagem da base até o working tree, `git diff --check 23ab7b0^`, retorna 0. Quando a limpeza entrar em `HEAD`, o range original também ficará limpo.

---

## Edge Cases

- [x] Tag com separador ou fora de `vX.Y.Z` é rejeitada.
- [x] GitHub indisponível falha antes de qualquer pasta final/temporária.
- [x] Digest com formato, hash ou nome divergente é rejeitado.
- [x] Download, hash, extração e manifesto falhos preservam release/configuração e removem resíduos.
- [x] Duas execuções concorrentes produzem exatamente um vencedor.
- [x] Release final preexistente é preservada.

---

## Gate Check

- **Gate command**: `& .\.venv\Scripts\python.exe -m pytest -q --basetemp test-results/github-release-pytest; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; pnpm test`
- **Result**: 951 passed, 0 failed, 0 skipped; exit code 0.
- **Backend**: 829 passed, 0 failed, 0 skipped; 6 warnings; 205.60 s.
- **UI**: 122 passed, 0 failed.
- **Test count before feature**: 788 backend + 122 UI = 910.
- **Test count after feature**: 829 backend + 122 UI = 951.
- **Delta**: +41 backend tests.
- **Skipped tests**: none.
- **Failures**: none no run válido.
- **Environmental retry**: a primeira tentativa escalada foi inválida porque o parent de `--basetemp` não existia; houve `672 passed, 157 FileNotFoundError`. Após criar somente `test-results`, o comando idêntico passou. A pasta temporária foi removida antes da comparação final.

---

## Fix Plans

Nenhum. Os quatro gaps funcionais e a inconsistência de rastreabilidade do relatório anterior foram fechados em `0f72680`.

---

## Requirement Traceability Update

| Requirement | Previous Status | New Status |
| ----------- | --------------- | ---------- |
| GRD-01..GRD-16 | Verified | ✅ Verified |

---

## Summary

**Overall**: ✅ Ready

**Spec-anchored check**: 16/16 ACs matched spec outcome; 0 spec-precision gaps.
**Sensor**: 3/3 mutations killed.
**Gate**: 951 passed, 0 failed, 0 skipped.

**What works**: publicação versionada e fail-closed; dois assets exatos; staging pública sem token; validação de metadata/digest/manifesto; cleanup completo; output sem segredos; promoção concorrente com um vencedor; cutover permanece separado.

**Issues found**: none.

**Next steps**: feature pronta para o fluxo de revisão/entrega autorizado. Este veredito não autoriza commit, push, tag ou deploy.

---

## Post-publication CI correction (2026-10-23)

The first public tag, `v0.3.0`, correctly stopped before release publication because the backend quality gate failed on a fresh PostgreSQL service. No GitHub Release asset and no production-server change occurred.

**Root cause**: `test_session_scope_rolls_back_and_closes_on_exception` and `test_upgrade_current_database_preserves_existing_probe` assumed that `_smartcrm_test_probe` had already been created by the local Compose verification script. A clean CI database does not contain that table.

**Correction**: `tests/backend/conftest.py` now provisions and restores the technical probe only for tests that request it. The two affected tests explicitly request the fixture, and the migration assertion preserves any pre-existing row count instead of assuming exactly one row.

**Fresh-database reproduction before the correction**: 764 passed, 2 failed. Both failures were `UndefinedTable` for `_smartcrm_test_probe`.

**Fresh-database verification after the correction**:

- Linux / Python 3.11 / PostgreSQL 17: 766 passed, 0 failed, 0 skipped; 6 warnings; 115.94 s.
- Focused Windows database + release/deployment gate: 82 passed, 0 failed, 0 skipped; 33.68 s.

**Publication state**: locally corrected and verified as application version `0.3.1`. Because published tags are immutable, `v0.3.0` is not moved; publishing tag `v0.3.1` requires a new explicit authorization. Production remains unchanged.
