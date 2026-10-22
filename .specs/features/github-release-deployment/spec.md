# GitHub Release Deployment Specification

## Problem Statement

O deploy atual depende de copiar manualmente um ZIP e seu hash para o Windows Server, o que torna cada atualização demorada e sujeita a seleção incorreta de arquivo. O repositório público deve publicar artefatos versionados e permitir que o servidor baixe e valide uma release exata sem instalar Git, sem credenciais do GitHub e sem alterar a release ativa durante o download.

## Goals

- [ ] Publicar automaticamente um ZIP offline e seu SHA-256 quando uma tag de versão aprovada for enviada ao GitHub.
- [ ] Permitir que o Windows Server prepare uma release imutável lado a lado a partir de uma tag explícita.
- [ ] Preservar a ativação, migração, health check e rollback já validados como uma etapa operacional separada.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Executar automaticamente migrações ou trocar a tarefa `SmartCRM` após o download | O corte de produção exige credencial, backup, janela e autorização próprios. |
| Instalar Git ou executar `git pull` no servidor | A release ativa deve continuar imutável e reproduzível. |
| Publicar releases a partir de branches sem tag | Uma release precisa de identidade imutável e correspondente à versão exibida pela aplicação. |
| Armazenar credenciais de banco ou do Windows no GitHub | Os segredos permanecem exclusivamente no servidor. |
| Automatizar restauração destrutiva de banco | Rollback de banco continua exigindo autorização explícita e backup verificado. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Visibilidade do repositório | Público | O usuário confirmou que `lamarcon/smart_crm` é público. | y |
| Identidade da release | Tag `vX.Y.Z` igual a `v` + `APP_VERSION` | Evita divergência entre GitHub, nome do pacote e versão exibida. | y |
| Publicação | Push de tag dispara GitHub Actions | Mantém a origem da release auditável e imutável. | y |
| Download no servidor | API pública do GitHub, sem token | Recursos públicos podem ser consultados sem autenticação e o servidor não precisa guardar PAT. | y |
| Alcance do primeiro automatizador | Preparar e validar uma pasta nova; não ativar | Reduz o trabalho manual sem ampliar o blast radius do download. | y |
| Release existente | Falhar sem sobrescrever | Releases e pastas já publicadas são imutáveis. | y |
| Releases preliminares | Rejeitar drafts e prereleases | O servidor de produção só prepara releases publicadas como estáveis. | y |
| Concorrência | Uma execução por tag; pasta final preexistente bloqueia repetição | Evita duas preparações competindo pela mesma identidade. | y |
| Retenção | Manter release ativa e anterior; limpeza é operação separada | Preserva rollback e impede exclusão automática. | y |
| Observabilidade | GitHub Actions registra testes/publicação; PowerShell imprime tag, hash e pasta preparada | Fornece evidência sem registrar segredos. | y |

**Open questions:** none - todas as decisões foram confirmadas ou receberam um default seguro acima.

---

## User Stories

### P1: Publicar uma release verificável no GitHub ⭐ MVP

**User Story**: Como responsável pelo Smart CRM, quero transformar uma tag aprovada em um pacote de produção testado para que eu não precise montar nem escolher arquivos manualmente.

**Why P1**: A automação elimina a etapa mais repetitiva do deploy e mantém o pacote reproduzível.

**Acceptance Criteria**:

1. WHEN uma tag no formato `vX.Y.Z` for enviada THEN o workflow SHALL confirmar que ela é exatamente `v` + `APP_VERSION` antes de criar artefatos.
2. WHEN a tag e a versão corresponderem THEN o workflow SHALL executar todos os testes backend e de interface antes da publicação.
3. WHEN os testes passarem THEN o workflow SHALL gerar `smart-crm-manual-pg11-<tag>.zip` e `smart-crm-manual-pg11-<tag>.zip.sha256` usando o construtor offline existente.
4. IF qualquer validação, teste ou construção falhar THEN o workflow SHALL terminar sem criar uma GitHub Release publicada.
5. WHEN o pacote for construído com sucesso THEN o workflow SHALL criar uma GitHub Release para a tag existente e anexar exatamente o ZIP e o SHA-256.

**Independent Test**: Validar estaticamente o contrato do workflow e executar localmente as mesmas validações, testes e construção com uma versão de teste.

### P1: Preparar a release no Windows Server sem Git ⭐ MVP

**User Story**: Como administrador do servidor, quero informar uma tag e obter uma pasta nova já validada para reduzir o trabalho anterior ao cutover.

**Why P1**: O servidor não deve depender de Git nem aceitar arquivos sem integridade comprovada.

**Acceptance Criteria**:

1. WHEN o script receber uma tag válida THEN o script SHALL consultar somente a release pública dessa tag em `lamarcon/smart_crm` sem exigir token.
2. IF a release for draft, prerelease, tiver tag diferente ou não contiver exatamente um ZIP e seu SHA-256 esperado THEN o script SHALL falhar antes de extrair qualquer arquivo.
3. WHEN os dois assets forem baixados THEN o script SHALL confirmar que o nome e o SHA-256 do ZIP correspondem exatamente ao conteúdo do arquivo `.sha256`.
4. WHEN o SHA-256 externo corresponder THEN o script SHALL extrair em uma pasta temporária dentro de `C:\brbots\apps` e validar o `MANIFEST.sha256` interno antes de renomeá-la para `smart-crm-<tag>`.
5. IF `smart-crm-<tag>` já existir THEN o script SHALL falhar sem modificar a pasta existente.
6. IF download, hash, extração ou manifesto falhar THEN o script SHALL remover somente sua pasta temporária e SHALL manter a tarefa, bancos, `server.env` e releases existentes inalterados.
7. WHEN a preparação terminar THEN o script SHALL informar tag, hash e caminho final sem revelar segredos.

**Independent Test**: Executar as funções PowerShell contra fixtures locais válidas, adulteradas e duplicadas, verificando pasta final e ausência de alterações fora da staging.

## Edge Cases

- IF a tag contiver separadores de caminho ou não seguir `vX.Y.Z` THEN o sistema SHALL rejeitá-la antes de formar caminhos ou URLs.
- IF o GitHub estiver indisponível ou retornar uma release inexistente THEN o script SHALL falhar antes de criar a pasta final.
- IF o arquivo SHA-256 tiver formato, hash ou nome divergente THEN o script SHALL falhar antes da extração.
- IF duas execuções tentarem preparar a mesma tag THEN somente a primeira que concluir SHALL ocupar a pasta final e a outra SHALL falhar sem sobrescrevê-la.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| GRD-01 | P1: Publicar release | Execute | Verified |
| GRD-02 | P1: Publicar release | Execute | Verified |
| GRD-03 | P1: Publicar release | Execute | Verified |
| GRD-04 | P1: Publicar release | Execute | Verified |
| GRD-05 | P1: Publicar release | Execute | Verified |
| GRD-06 | P1: Preparar release | Design | Pending |
| GRD-07 | P1: Preparar release | Design | Pending |
| GRD-08 | P1: Preparar release | Design | Pending |
| GRD-09 | P1: Preparar release | Design | Pending |
| GRD-10 | P1: Preparar release | Design | Pending |
| GRD-11 | P1: Preparar release | Design | Pending |
| GRD-12 | Edge case: tag inválida | Execute | Implementing |
| GRD-13 | Edge case: GitHub indisponível | Design | Pending |
| GRD-14 | Edge case: digest inválido | Design | Pending |
| GRD-15 | Edge case: concorrência | Design | Pending |

**Coverage:** 15 total, 15 mapped to tasks, 0 unmapped.

## Success Criteria

- [ ] Uma tag correta produz uma release pública com exatamente os dois assets esperados.
- [ ] Uma tag incorreta, teste falho ou build falho não publica release.
- [ ] O servidor prepara uma pasta imutável validada sem Git e sem token.
- [ ] Nenhum caminho de preparação altera banco, tarefa agendada, `server.env` ou release existente.

