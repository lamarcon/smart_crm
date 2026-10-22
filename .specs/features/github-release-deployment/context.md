# GitHub Release Deployment Context

**Gathered:** 2026-10-22
**Spec:** `.specs/features/github-release-deployment/spec.md`
**Status:** Ready for design

---

## Feature Boundary

Publicar o pacote offline existente em GitHub Releases a partir de uma tag semântica e preparar essa release no Windows Server com validação externa e interna, preservando a ativação de produção como um passo explícito separado.

---

## Implementation Decisions

### Canal de distribuição

- O repositório `lamarcon/smart_crm` é público.
- O servidor usa a API pública do GitHub e não armazena PAT.
- GitHub é a fonte da identidade da release; o servidor apenas mantém pastas das releases instaladas.

### Versionamento e publicação

- Tags estáveis seguem `vX.Y.Z` e devem corresponder ao `APP_VERSION` da aplicação.
- A pipeline publica somente depois dos testes backend e UI.
- Os assets continuam sendo o ZIP offline e seu SHA-256, sem `server.env` ou segredos.

### Limite operacional

- O script novo somente baixa, valida e prepara uma pasta lado a lado.
- Banco, Alembic, tarefa agendada e health check permanecem no inicializador existente e exigem a janela de produção.
- Pastas de release existentes nunca são sobrescritas ou removidas pelo script.

### Agent's Discretion

- Nomes internos de funções e organização das validações PowerShell.
- Forma exata dos testes de contrato, desde que cubram todos os resultados definidos pela especificação.

### Declined / Undiscussed Gray Areas → Assumptions

- Limpeza automática de releases antigas não foi discutida; o default é não apagar nada.
- Prereleases não foram solicitadas; o default é rejeitá-las no servidor de produção.
- Deploy automático no push não foi solicitado; o default é publicar o artefato e exigir comando explícito no servidor.

---

## Deferred Ideas

- Cutover integral em um único comando com backup de ambos os bancos e rollback transacional coordenado.
- Assinatura/attestation verificável no Windows Server além do SHA-256 publicado.
- Política automatizada de retenção depois que o histórico de rollback estiver estabilizado.
