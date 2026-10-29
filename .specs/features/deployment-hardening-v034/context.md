# Deployment Hardening v0.3.4 Context

**Gathered:** 2026-10-29
**Spec:** `.specs/features/deployment-hardening-v034/spec.md`
**Status:** Approved for design and tasks

---

## Feature Boundary

Transformar as correções manuais observadas no deploy v0.3.3 em um fluxo de atualização Windows idempotente, verificável e coberto por testes, preservando FORCE RLS, o isolamento por banco e as releases imutáveis lado a lado.

---

## Implementation Decisions

### Segurança e dados

- FORCE RLS permanece ativo.
- O workspace de reparo vem de `tenant_identity`; nenhum reparo enumera ou adivinha workspaces fora dessa identidade.
- Uma nova migração posterior a `f6b1d3a8c2e4` repara dados já afetados; migrações publicadas não serão reescritas.
- Funis existentes e personalizados são preservados; o seed padrão só é criado quando estiver ausente.
- Payloads antigos de usuários são completados sem alterar credenciais ou permissões.

### Operação Windows

- O operador continuará informando a credencial de `SmartCRMService` interativamente.
- A migração tenant rodará em uma tarefa temporária sob `SmartCRMService`, reutilizando `FleetService` e o segredo DPAPI.
- A ativação será um comando após staging e confirmação de backup, com parada, migração, registro, início e gates ordenados.
- Informações normais em stderr de processos nativos serão registradas e julgadas pelo código de saída.
- O gate final exige health `ok`, versão exata e tarefa apontando para a release alvo.

### Compatibilidade e rollback

- Windows PowerShell 5.1 e PostgreSQL 11 permanecem suportados nesta entrega.
- A pasta de release permanece imutável e lado a lado.
- Nenhuma operação alcança `DW_CMS` ou `DW_PRODUTOS`.
- Falhas não podem emitir sucesso; a tarefa anterior deve continuar recuperável conforme o runbook.

### Agent's Discretion

- Organização interna dos helpers PowerShell e do comando Python de migração dentro da arquitetura de tarefa temporária aprovada.
- Nome da nova revisão Alembic e divisão exata dos testes por arquivo.

### Declined / Undiscussed Gray Areas → Assumptions

- Política detalhada de backup permanece fora do escopo; o deploy exige apenas reconhecimento explícito de que um backup adequado foi verificado.
- Não haverá migração automática de PostgreSQL 11 nesta entrega.

---

## Specific References

- Incidentes reais do deploy v0.3.3 em 2026-10-29: `ConvertFrom-StringData` com `C:\ProgramData`, stderr informativo do Alembic, revisão central antiga, seed vazio sob RLS, processo antigo na porta 8080 e payload administrativo vazio.
- O usuário quer que próximos deploys sejam simples e não repitam a sequência de SQL e reparos manuais.

---

## Deferred Ideas

- Automatização e retenção de backups por tenant.
- Atualização do PostgreSQL 11 para uma versão suportada.
- Observabilidade centralizada de rollout para múltiplos servidores.
