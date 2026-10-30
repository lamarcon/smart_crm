# Deployment Hardening v0.3.4 Validation

**Date**: 2026-10-30
**Spec**: `.specs/features/deployment-hardening-v034/spec.md`
**Diff range**: `9485586..f21a964`
**Verifier**: independent sub-agent (author != verifier)
**Verdict**: PASS

---

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| T1 | PASS | Migração de reparo validada em PostgreSQL real com FORCE RLS. |
| T2 | PASS | Criação e retomada do administrador persistem payload canônico e somente hash Argon2id. |
| T3 | PASS | CLI e `FleetService` exigem seleção/ack/confirmação e mantêm revisão/perfil coerentes. |
| T4 | PASS | Helpers PowerShell 5.1 cobrem parser literal, stderr, porta, tarefa, health e versão. |
| T5 | PASS | Runner sob conta de serviço produz evidência atômica e redigida. |
| T6 | PASS | Tarefa temporária é finita, validada e removida em sucesso/falha. |
| T7 | PASS | Cutover ordena migração, parada, liberação da porta, registro, readiness e restauração. |
| T8 | PASS | Bundle, manifesto e workflow exigem os componentes endurecidos antes da publicação. |
| T9 | PASS | Commit `f21a964` isola o estado `0 / 0`; a mutação de uma etapa foi morta e o task plan registra a conclusão. |

---

## Spec-Anchored Acceptance Criteria

| Criterion | Spec-defined outcome | `file:line` + assertion expression | Result |
| --------- | -------------------- | ---------------------------------- | ------ |
| DEPLOY-01.1 - migração confirmada antes do avanço central | Revisão tenant = head, revisão central = head e `profile_version` avança de 1 para 2 uma única vez | `tests/backend/test_fleet.py:477` - `assert (selected.expected_tenant_revision, selected.status, selected.profile_version) == (TENANT_HEAD, "active", 2)`; `tests/backend/test_fleet.py:483` - `assert revisions == {"upgrade": TENANT_HEAD, ...}`; a ordem verificação→CAS está em `app/fleet.py:274` e `app/fleet.py:285` | PASS |
| DEPLOY-01.2 - falha de confirmação preserva perfil | Identidade/revisão/conexão inválida retorna falha e mantém revisão/status/profile anteriores | `tests/backend/test_fleet.py:511` - `assert tenant.expected_tenant_revision == PREVIOUS_TENANT_HEAD`; `tests/backend/test_fleet.py:513` - `assert tenant.profile_version == 1`; `tests/backend/test_fleet.py:514` - resultado `verification_failed` | PASS |
| DEPLOY-01.3 - retry já atual | Código `already_current` e nenhum novo incremento | `tests/backend/test_fleet.py:371` - `assert after.profile_version == profile_version_before`; `tests/backend/test_fleet.py:372` - `assert [...] == ["already_current", "already_current"]` | PASS |
| DEPLOY-01.4 - seleção/ack/confirmação explícitos | Cada ausência falha antes de abrir/migrar tenant | `tests/backend/test_fleet.py:298` a `tests/backend/test_fleet.py:300` definem os três casos; `tests/backend/test_fleet.py:314` exige `FleetOperationError`; `tests/backend/test_fleet.py:323` - `assert calls == []` | PASS |
| DEPLOY-02.1 - seed 1/9 sob RLS | Um funil padrão, nove etapas ativas e uma inicial válida | `tests/backend/test_deployment_repair_migration.py:129` - `assert forced_tables == 3`; `tests/backend/test_deployment_repair_migration.py:136` valida o funil; `tests/backend/test_deployment_repair_migration.py:142` - `assert len(state["stages"]) == 9`; `tests/backend/test_deployment_repair_migration.py:144` - uma `initial` | PASS |
| DEPLOY-02.2 - funil existente preservado | Nome, versão/ordem, semântica, cor e default existentes não são substituídos | `tests/backend/test_deployment_repair_migration.py:192` a `tests/backend/test_deployment_repair_migration.py:196` validam nome, versão, primeira etapa, cor e total após retry | PASS |
| DEPLOY-02.3 - payload canônico sem alterar credenciais/permissões | Campos obrigatórios vêm das colunas; hash/auth e extras permanecem | `tests/backend/test_deployment_repair_migration.py:145` valida o payload exato; `tests/backend/test_deployment_repair_migration.py:157` e `:158` preservam hash/auth; `tests/backend/test_deployment_repair_migration.py:197` e `:198` preservam extras | PASS |
| DEPLOY-02.4 - reparo idempotente | Reexecução não duplica nem muda o estado persistido válido | `tests/backend/test_deployment_repair_migration.py:188` e `:189` fazem downgrade/upgrade; `tests/backend/test_deployment_repair_migration.py:192` a `:201` comprovam o mesmo agregado e credenciais | PASS |
| DEPLOY-02.5 - isolamento FORCE RLS | Reparar somente o workspace de `tenant_identity` mantendo FORCE RLS | `tests/backend/test_deployment_repair_migration.py:129` comprova três tabelas com FORCE RLS; `tests/backend/test_deployment_repair_migration.py:136` a `:159` comprovam o estado no workspace identificado | PASS |
| DEPLOY-02.6 - banco novo vs. usuário órfão | Sem identidade/usuários avança sem dados; com usuário sem identidade aborta sem escrita | `tests/backend/test_deployment_repair_migration.py:226` exige erro; `:235` - `assert counts_after == counts_before`; `:245` confirma head e `:246` confirma zero identidade no banco novo | PASS |
| DEPLOY-03.1 - primeiro admin completo | Payload tem os mesmos id/name/email/role/status/jobTitle canônicos | `tests/backend/test_admin.py:257` a `tests/backend/test_admin.py:268` fazem igualdade exata do payload persistido | PASS |
| DEPLOY-03.2 - resume sincroniza na mesma operação | Um único usuário e payload atualizado com os valores canônicos | `tests/backend/test_admin.py:365` - `assert ... count(*) ... == 1`; `tests/backend/test_admin.py:372` a `:383` fazem igualdade exata do payload atualizado | PASS |
| DEPLOY-03.3 - somente hash Argon2id, sem credencial no payload | Coluna contém hash Argon2id; payload exato não contém senha/hash | `tests/backend/test_admin.py:256` - `assert admin.password_hash == "$argon2id$..."`; `tests/backend/test_admin.py:257` a `:268` enumeram todo o payload permitido | PASS |
| DEPLOY-04.1 - parser literal PS 5.1 | Barras invertidas e conteúdo após o primeiro `=` permanecem literais | `tests/backend/test_manual_windows_pg11_outcomes.py:498` a `:502` comparam exatamente `C:\ProgramData\...` e `one=two=three` | PASS |
| DEPLOY-04.2 - stderr informativo não falha | Exit 0 com stderr permanece sucesso e saída é capturada; exit 7 falha | `tests/backend/test_manual_windows_pg11_outcomes.py:829` a `:835` validam exit codes e conteúdo de stderr | PASS |
| DEPLOY-04.3 - parar tarefa e liberar porta antes da nova ação | Ordem stop→wait→install e timeout de porta é fatal | `tests/backend/test_manual_windows_pg11_outcomes.py:579` a `:582` validam a ordem; `tests/backend/test_manual_windows_pg11_outcomes.py:762` a `:764` validam liberação e timeout 8080 | PASS |
| DEPLOY-04.4 - health ok + versão exata | Só `status=ok` e versão idêntica passam | `tests/backend/test_manual_windows_pg11_outcomes.py:722` a `:725` exigem sucesso válido e falha para health ruim, versão divergente ou ausente | PASS |
| DEPLOY-04.5 - falhas não emitem PASS e são acionáveis | Porta/migração/tarefa/readiness inválidas retornam não-zero antes de PASS/publicação | `tests/backend/test_manual_windows_pg11_outcomes.py:745` e `:746` validam versão/timeout; `:763` e `:764` porta; `:926` tarefa temporária; `:964` a `:967` migração bloqueia publicação; `:579` a `:582` colocam `LOCAL GATE: PASS` por último | PASS |
| DEPLOY-04.6 - usuário e AppRoot imutável comprovados | Tarefa usa `SmartCRMService` e a ação/diretório da release exata | `tests/backend/test_manual_windows_pg11_outcomes.py:795` a `:797` aceitam alvo correto e rejeitam usuário/release divergentes | PASS |
| DEPLOY-05.1 - suíte reproduz incidentes | CI cobre parser/stderr, FORCE RLS, revisão central, admin, versão e bundle | Evidências específicas acima; `tests/backend/test_github_release_delivery.py:232` a `:240` exigem os contratos Windows antes do build; `tests/backend/test_github_release_delivery.py:219` a `:226` exigem PostgreSQL/full gate | PASS |
| DEPLOY-05.2 - regressão bloqueia publicação | Testes antes do build/publicação e mutações deliberadas terminam não-zero | `tests/backend/test_github_release_delivery.py:274` a `:276` - backend/UI < build < publish; mutantes atingiram `tests/backend/test_deployment_repair_migration.py:142`, `tests/backend/test_fleet.py:371` e `tests/backend/test_manual_windows_pg11_outcomes.py:722` | PASS |

**Status**: 21/21 ACs correspondem ao resultado preciso definido na spec; 0 spec-precision gaps.

---

## Edge Cases

- PASS - identidade ausente com usuário aborta sem escrita: `tests/backend/test_deployment_repair_migration.py:226` e `:235`; banco novo avança vazio em `:245` e `:246`.
- PASS - mais de um funil default aborta pelo invariant de integridade em `migrations/versions/a8d4e6f2b1c9_repair_tenant_deploy_state.py:73` a `:89`.
- PASS - campos adicionais do payload são preservados em `tests/backend/test_deployment_repair_migration.py:197` e `:198`.
- PASS - porta 8080 ainda ocupada falha em `tests/backend/test_manual_windows_pg11_outcomes.py:763` e `:764`.
- PASS - aplicação saudável com versão anterior falha em `tests/backend/test_manual_windows_pg11_outcomes.py:724` e `:745`.

---

## Discrimination Sensor

O sensor usou o worktree descartável `deployment-hardening-sensor-v034` em detached HEAD `f21a964`; nenhuma mutação tocou o worktree real. Profundidade: lightweight, 3/3 mutantes mortos.

| Mutation | File:line | Fault injected | Test/result | Killed? |
| -------- | --------- | -------------- | ----------- | ------- |
| 1 | `migrations/versions/a8d4e6f2b1c9_repair_tenant_deploy_state.py:29` | Removeu a etapa de posição 8 de `LEGACY_STAGES` | `pytest ... test_deployment_repair_migration.py` → exit 1, `2 failed, 2 passed`; ambas asserções observaram `8 != 9` | PASS - killed |
| 2 | `app/fleet.py:262` | Desativou o early-return `already_current`, permitindo dois incrementos | `pytest ...::test_already_current_retry_does_not_advance_profile_version` → exit 1; `profile_version 3 != 1` | PASS - killed |
| 3 | `deploy/manual-windows-pg11/deployment-policy.ps1:396` | Inverteu a comparação exata `-cne` para `-ceq` | `pytest ...::test_release_readiness_requires_health_ok_and_exact_version` → exit 1; o caso válido foi rejeitado em `tests/backend/test_manual_windows_pg11_outcomes.py:722` | PASS - killed |

Após restaurar cada mutação, `git diff --exit-code` passou. A confirmação conjunta restaurada terminou `6 passed in 10.25s`; `git status --short` do scratch ficou vazio antes de sua remoção. O porcelain do worktree real permaneceu igual ao baseline, exceto pelos dois artefatos de validação autorizados.

---

## Gate Check

| Command | Result |
| ------- | ------ |
| `validate_spec.py .specs/features/deployment-hardening-v034/spec.md` | exit 0; 0 errors, 0 warnings |
| `validate_tasks.py .specs/features/deployment-hardening-v034/tasks.md` | exit 0; 0 errors, 0 warnings |
| `git diff --check 9485586..f21a964` | exit 0 |
| Focused feature gate from `tasks.md` | `125 passed in 47.27s`, 0 failed, 0 skipped |
| Build gate backend | `859 passed, 6 warnings in 197.67s`, 0 failed, 0 skipped |
| Build gate UI (`pnpm test`) | `122 passed, 0 failed` |
| Restored sensor targets | `6 passed in 10.25s` |

O primeiro focused run sem elevação foi descartado: o sandbox negou 41 conexões a `127.0.0.1:5432` com WinSock 10013; os 84 testes sem banco passaram. A repetição autorizada contra o mesmo PostgreSQL local é o gate válido de 125/125.

- **Test count before feature (`9485586`)**: 830 backend collected + 122 UI = 952.
- **Test count after feature (`f21a964`)**: 859 backend + 122 UI = 981.
- **Delta**: +29 backend; UI inalterada; nenhum arquivo de teste UI foi modificado.
- **Skipped tests**: none.
- **Failures**: none no gate válido.
- **APP_VERSION**: permaneceu `0.3.3`; `tests/backend/test_windows_multitenant_bundle.py:120` e `:167` comprovam o valor no source e no bundle.

---

## Code Quality

| Principle | Status |
| --------- | ------ |
| Mudanças limitadas ao reparo tenant, payload admin, CLI/frota, scripts/gates Windows, bundle e seus testes/docs | PASS |
| Sem abstração/flexibilidade fora do escopo; padrões existentes (`FleetService`, `_packed`, policy helpers, bundle manifest) reutilizados | PASS |
| Sem push, tag, deploy, produção ou alteração de `APP_VERSION` | PASS |
| Testes mapeiam os 21 ACs e asserem valores/estados exatos | PASS |
| Camadas de domínio, migração, CLI, PowerShell, bundle e workflow cobertas por integração/contrato | PASS |
| Nenhum teste novo sem claim: todos mapeiam a AC, edge case ou Done-when de T1-T9 | PASS |
| Guidelines: `pyproject.toml`, `.github/workflows/release-windows-pg11.yml` e a matriz de `tasks.md`; sem `AGENTS.md`/contributor guide | PASS |

---

## Residual Risks

1. O Task Scheduler real, ACL/DPAPI e rollback completo não foram executados num Windows Server de produção; a cobertura local usa Windows PowerShell 5.1 real para helpers e um harness fiel para os cmdlets de tarefa. O runbook ainda exige UAT operacional antes de deploy.
2. O edge case de múltiplos funis default é protegido por código, mas não possui um teste PostgreSQL dedicado nesta feature.
3. Permanecem 6 warnings de dependências/Pydantic no gate backend; nenhum foi introduzido como falha desta feature.

---

## Requirement Traceability

| Requirement | Previous | Verified outcome |
| ----------- | -------- | ---------------- |
| DEPLOY-01 | Verified | PASS - 4/4 ACs |
| DEPLOY-02 | Verified | PASS - 6/6 ACs |
| DEPLOY-03 | Verified | PASS - 3/3 ACs |
| DEPLOY-04 | Verified | PASS - 6/6 ACs |
| DEPLOY-05 | Verified | PASS - 2/2 ACs |

---

## Summary

**Overall**: PASS - ready for the separately authorized release workflow; no push, tag, deploy or version change was performed.

**Spec-anchored check**: 21/21 ACs matched exact outcomes; 0 precision gaps.

**Sensor**: 3/3 required behavior mutations killed; restored state passed 6/6 focused tests and had an empty scratch diff.

**Gate**: 859 backend + 122 UI passed; no failures or skips.

**Lessons**: clean PASS, so no lesson was recorded and `.specs/LESSONS.md` / `.specs/lessons.json` were intentionally left untouched.
