# Smart CRM — Repasse para outra IA

Este documento fornece contexto técnico suficiente para outra IA colaborar sem acessar segredos, produção ou o mesmo espaço de trabalho de outro agente.

## Repositório e estado seguro

- Repositório: `https://github.com/lamarcon/smart_crm.git`
- Branch de integração atual: `main` (contém `codex/deploy-hardening-v0.3.4` e os branches `ai2/*` até a release `v0.3.7`)
- Commit de referência: `7efe86d` (`chore(release): bump application version to 0.3.7`)
- Versão atualmente publicada no servidor: `0.3.7` (implantada em 2026-11-11, com SMTP `mail.brbots.com:465`)
- As tags `v0.3.4`, `v0.3.5` e `v0.3.6` existem sem GitHub Release: o workflow falhou por diferenças do ambiente de CI (banco vazio, tempo de toast e `PSModulePath` do `pwsh`), corrigidas até a `v0.3.7`. Não reutilize esses números.
- Próxima versão: `0.3.8`; não alterar `APP_VERSION`, criar tag ou publicar release sem autorização explícita.
- A branch de integração pode conter commits ainda não enviados ao GitHub. Confirme com o responsável antes de escolher a base remota.

## Arquivos que devem ser lidos primeiro

1. `README.md`
2. `.specs/STATE.md`
3. `.specs/features/user-invitations-password-recovery/context.md`
4. `.specs/features/user-invitations-password-recovery/spec.md`
5. `.specs/features/user-invitations-password-recovery/design.md`
6. `.specs/features/user-invitations-password-recovery/tasks.md`
7. `RUNBOOK_DEPLOY_WINDOWS_SERVER_2016.md`, somente se a tarefa envolver empacotamento ou deploy.

As decisões AD-005, AD-006, AD-011, AD-012 e AD-013 em `.specs/STATE.md` são limites arquiteturais obrigatórios.

## Arquitetura resumida

- Backend: FastAPI, SQLAlchemy 2, Psycopg 3 e Alembic.
- Plano central: banco `smartcrm_control`, responsável por tenants, sessões, limites e auditoria.
- Dados comerciais: um banco PostgreSQL exclusivo por empresa.
- Primeiro tenant: `brbots`, usando o banco `smartcrm`.
- Isolamento tenant: RLS e `smartcrm.workspace_id` por transação.
- Serviço Windows: conta dedicada `SmartCRMService` e segredos protegidos com DPAPI.
- Releases: pastas imutáveis lado a lado, originadas de tags e GitHub Releases; staging e ativação são operações separadas.

## Trabalho atual: convites e recuperação de senha

Concluído e commitado:

- T1/T2: entidade e migration tenant para tokens de ação.
- T3: repositório de tokens de convite/redefinição.
- T4: throttling e auditoria central generalizados.
- T5: adaptador SMTP seguro e injetável.
- T6: criação, reenvio e cancelamento administrativo de convites.

Próximo trabalho sequencial:

- T7: inspeção e aceite de convite.
- T8: recuperação de senha e invalidação de sessões.
- T9: proteção dos campos de autenticação contra snapshots do workspace.
- T10: contratos da API.
- T11–T14: rotas, interface e configuração SMTP do Windows.

Não avance uma tarefa cuja dependência ainda não esteja concluída. Cada tarefa precisa de testes derivados da especificação, gate verde, atualização de `tasks.md`/`spec.md` e um commit atômico.

## Como outra IA deve trabalhar

Use uma branch e um worktree próprios. Nunca compartilhe a mesma pasta de trabalho com outro agente.

Exemplo, depois que a branch de integração estiver no GitHub:

```powershell
git fetch origin
git worktree add ..\smart-crm-ai2 -b ai2/<nome-da-tarefa> origin/codex/deploy-hardening-v0.3.4
Set-Location ..\smart-crm-ai2
```

Antes de editar, a outra IA deve informar:

1. tarefa e requisitos que assumirá;
2. arquivos que pretende alterar;
3. testes e gate que executará;
4. possíveis conflitos com o trabalho em andamento.

Ao concluir, deve entregar commit(s) locais ou uma PR própria. Não deve fazer merge, deploy, migração em produção, tag ou release sem autorização explícita.

## Divisão recomendada

Enquanto o agente principal trabalha na sequência T7–T14, a segunda IA deve assumir somente um escopo sem sobreposição, por exemplo:

- revisão independente e testes adicionais de uma tarefa já commitada;
- documentação não operacional;
- uma funcionalidade futura em outra branch, depois de ter especificação aprovada;
- investigação somente leitura de um problema.

Se a segunda IA precisar trabalhar em T7–T14, o responsável deve atribuir tarefas inteiras e interromper o agente principal nessa mesma superfície até o merge.

## Segurança e dados proibidos

Nunca copiar para chat, commit, issue, PR ou arquivo de repasse:

- `C:\ProgramData\SmartCRM\server.env`;
- senha PostgreSQL ou SMTP;
- conteúdo de `tenant-secrets` ou `service-secrets`;
- arquivos DPAPI `.bin`;
- cookies, tokens brutos, DSNs completos ou credenciais da conta Windows;
- dumps reais do banco.

Use valores fictícios em testes. Não execute comandos contra o servidor de produção sem autorização específica.

## Regras de Git

- Preservar mudanças alheias e arquivos sujos preexistentes.
- Não usar `git reset --hard`, `git checkout --` ou force-push.
- Não editar nem incluir `.specs/LESSONS.md` e `.specs/lessons.json` sem uma tarefa específica do processo de lições.
- Um entregável por commit, com mensagem Conventional Commits.
- Não reduzir, apagar ou pular testes para obter gate verde.
- Não enviar a branch ao remoto sem autorização.

## Verificação

Os comandos exatos de gate estão em `.specs/features/user-invitations-password-recovery/tasks.md`. Testes PostgreSQL precisam de uma instância de desenvolvimento e de uma pasta `--basetemp` única dentro do worktree quando o ambiente Windows restringir `%TEMP%`.

Última evidência da T6:

- testes focados: `11 passed`;
- gate backend: `897 passed`, com 6 avisos preexistentes;
- nenhum teste removido, enfraquecido ou ignorado;
- commit: `944cf5e`.

## Texto curto para iniciar outra IA

```text
Trabalhe no Smart CRM somente em uma branch e worktree próprios. Leia AI_HANDOFF.md, .specs/STATE.md e a especificação da funcionalidade antes de editar. Informe tarefa, arquivos, testes e conflitos previstos. Preserve a arquitetura multiempresa, RLS, DPAPI e releases lado a lado. Não exponha segredos e não faça push, merge, deploy, migration de produção, tag ou release sem autorização explícita. Entregue mudanças pequenas, testadas e em commits atômicos.
```
