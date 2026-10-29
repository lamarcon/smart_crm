# Deployment Hardening v0.3.4 Specification

## Problem Statement

O deploy v0.3.3 passou pelos testes de release, mas exigiu correções manuais em produção: o parser do `server.env` falhou no Windows PowerShell 5.1, mensagens normais do Alembic em stderr interromperam o inicializador, a revisão tenant no plano de controle ficou desatualizada, dados estruturais não foram semeados sob RLS e o primeiro administrador foi criado sem o payload consumido pela interface. O próximo deploy precisa transformar essas falhas em invariantes testadas e concluir a atualização em um único fluxo validado.

## Goals

- [ ] Atualizar uma release Windows lado a lado sem edição manual de banco, arquivo de ambiente ou tarefa agendada.
- [ ] Manter banco tenant, plano de controle e metadados de roteamento na mesma revisão confirmada.
- [ ] Reparar, de forma idempotente, tenants afetados pelo seed vazio e usuários administrativos sem payload de interface.
- [ ] Impedir a publicação de uma release quando migração, processo ativo, saúde ou versão não puderem ser comprovados.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Alterar ou migrar `DW_CMS` e `DW_PRODUTOS` | São bancos externos ao Smart CRM e devem permanecer intocados. |
| Remover RLS ou reduzir o isolamento tenant | RLS é uma fronteira de segurança vigente e será preservada. |
| Automatizar backup de todos os bancos PostgreSQL compartilhados | O fluxo apenas exige confirmação explícita de backup adequado; a política de backup é operação separada. |
| Alterar funcionalidades visuais do CRM | O escopo é confiabilidade de dados, provisionamento e deploy. |
| Fazer push, criar release ou aplicar v0.3.4 em produção | Operações remotas exigem autorização separada após a validação local. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Segurança tenant | Manter FORCE RLS e executar reparos dentro do workspace obtido de `tenant_identity` | Corrige o seed sem enfraquecer o isolamento. | yes |
| Experiência operacional | Um comando de ativação após staging, credencial interativa e confirmação de backup | Reduz etapas manuais sem guardar senha na linha de comando. | yes |
| Pipeline já personalizado | Reparar somente workspace sem funil padrão; nunca substituir configuração existente | O reparo não pode apagar personalizações válidas. | yes |
| Usuários antigos | Completar somente payload ausente/incompleto a partir das colunas canônicas | Preserva dados existentes e corrige seletores da interface. | yes |
| Falha durante cutover | Não declarar sucesso; manter ou restaurar a tarefa anterior e emitir erro acionável | Uma release sem gate completo não pode ficar publicada silenciosamente. | yes |
| Compatibilidade | Suportar Windows PowerShell 5.1 e PostgreSQL 11 usados no servidor atual | É o ambiente real de produção. | yes |

**Open questions:** none - all resolved or logged above.

---

## User Stories

### P1: Migração tenant consistente ⭐ MVP

**User Story**: Como operador do Smart CRM, quero migrar cada tenant selecionado e atualizar seu perfil central somente após a verificação do banco, para que o roteador nunca rejeite um tenant por divergência criada pelo próprio deploy.

**Why P1**: A divergência de revisão bloqueou autenticação e acesso ao banco mesmo com a aplicação saudável.

**Acceptance Criteria**:

1. WHEN um tenant selecionado é migrado com sucesso para a revisão alvo THEN o sistema SHALL confirmar essa revisão no banco tenant antes de atualizar `expected_tenant_revision` e incrementar `profile_version` exatamente uma vez.
2. IF a revisão, identidade tenant ou conexão não puder ser confirmada após a migração THEN o sistema SHALL manter o perfil central anterior e falhar o deploy antes da publicação.
3. WHEN o fluxo é repetido para um tenant já na revisão alvo THEN o sistema SHALL concluir como `already_current` sem incrementar novamente `profile_version`.
4. The system SHALL exigir seleção explícita de tenant, confirmação operacional e reconhecimento de backup antes de migrar.

**Independent Test**: Executar o fluxo contra bancos de teste com revisões anterior, atual e divergente e comparar revisão tenant, revisão central e `profile_version`.

### P1: Reparação idempotente sob RLS ⭐ MVP

**User Story**: Como administrador do tenant, quero que estruturas obrigatórias e perfis de usuário antigos sejam reparados durante a migração, para que funis e responsáveis estejam disponíveis após o deploy.

**Why P1**: O seed v0.3.3 passou de forma vazia sob FORCE RLS e o administrador ficou invisível nos seletores.

**Acceptance Criteria**:

1. WHEN a migração de reparo encontra um workspace identificado por `tenant_identity` sem funil THEN o sistema SHALL criar exatamente um funil padrão com nove etapas ativas e uma etapa inicial válida.
2. WHEN a migração de reparo encontra um funil existente THEN o sistema SHALL preservar nomes, ordem, semântica, cores e etapa inicial existentes.
3. WHEN a migração de reparo encontra um `crm_user` com payload ausente ou incompleto THEN o sistema SHALL completar `id`, `name`, `email`, `role`, `status`, `jobTitle` e `avatar` a partir das colunas canônicas sem alterar hash de senha, versão de autenticação ou permissões.
4. WHEN a migração de reparo é executada mais de uma vez THEN o sistema SHALL produzir o mesmo estado persistido sem duplicar funis, etapas ou usuários.
5. WHILE FORCE RLS estiver ativo, o sistema SHALL executar o reparo somente no workspace declarado em `tenant_identity`.
6. WHEN um banco novo ainda não tiver `tenant_identity` nem usuários THEN o sistema SHALL avançar a revisão sem executar reparo de dados; IF houver usuários sem identidade THEN o sistema SHALL abortar antes de alterar o workspace.

**Independent Test**: Migrar um banco PostgreSQL com FORCE RLS, seed ausente e administrador com `{}`, repetir a migração e verificar contagens e payload final.

### P1: Provisionamento de administrador completo ⭐ MVP

**User Story**: Como primeiro administrador de uma empresa, quero aparecer imediatamente nos campos de responsável e assistente, para que seja possível criar registros sem correção SQL manual.

**Why P1**: Novos tenants repetiriam o defeito do payload vazio.

**Acceptance Criteria**:

1. WHEN `activate-default` cria o primeiro administrador THEN o sistema SHALL persistir um payload de interface com os mesmos `id`, `name`, `email`, `role`, `status` e `jobTitle` das colunas canônicas.
2. WHEN `resume-provisioning` atualiza um administrador ainda não ativo THEN o sistema SHALL sincronizar o payload de interface com as colunas canônicas na mesma transação.
3. The system SHALL persistir somente o hash Argon2id da senha e SHALL NOT incluir senha ou hash no payload de interface.

**Independent Test**: Provisionar um tenant vazio e consultar o usuário pela API de workspace e diretamente no banco.

### P1: Cutover Windows verificável ⭐ MVP

**User Story**: Como operador do servidor Windows, quero ativar uma release com um único comando seguro, para que a tarefa agendada nunca aponte para uma versão não comprovada ou deixe um processo antigo atendendo a porta 8080.

**Why P1**: O deploy anterior registrou a tarefa nova enquanto o processo antigo continuava atendendo e declarou um gate incompatível com o health real.

**Acceptance Criteria**:

1. WHEN o inicializador lê `server.env` THEN o sistema SHALL preservar literalmente barras invertidas e valores após o primeiro `=` no Windows PowerShell 5.1.
2. WHEN um processo nativo escreve informação em stderr e termina com código 0 THEN o sistema SHALL registrar a saída sem tratar a execução como falha.
3. WHEN o cutover começa THEN o sistema SHALL parar a tarefa ativa e confirmar que a porta 8080 está livre antes de iniciar a nova ação.
4. WHEN a nova tarefa inicia THEN o sistema SHALL aceitar sucesso somente se `/health` retornar `status=ok` e `/api/version` retornar exatamente a versão esperada da release.
5. IF a porta não for liberada, a migração falhar, a tarefa não iniciar, o health não for `ok` ou a versão divergir THEN o sistema SHALL falhar sem emitir `LOCAL GATE: PASS` e SHALL fornecer uma mensagem acionável.
6. WHEN o cutover termina com sucesso THEN o sistema SHALL comprovar que a tarefa executa sob `SmartCRMService` e referencia a pasta imutável da release alvo.

**Independent Test**: Executar os helpers em Windows PowerShell 5.1 com ambientes, stderr, versões e estados de porta simulados e validar o fluxo completo em integração.

### P1: Gate de release contra regressões ⭐ MVP

**User Story**: Como mantenedor, quero que a CI reproduza as falhas vistas em produção, para que um pacote com os mesmos defeitos não possa ser publicado novamente.

**Why P1**: A release v0.3.3 passou na CI sem cobrir o ambiente real e os estados de dados afetados.

**Acceptance Criteria**:

1. WHEN a suíte de release executa THEN o sistema SHALL testar parser Windows PowerShell 5.1, stderr nativo com exit code 0, migração sob FORCE RLS, sincronização de revisão central, payload administrativo e validação da versão ativa.
2. IF qualquer regressão coberta for introduzida THEN o gate SHALL terminar com código diferente de zero e impedir a publicação do pacote.

**Independent Test**: Executar os comandos de gate localmente e confirmar que mutações deliberadas em cada comportamento são detectadas.

---

## Edge Cases

- IF `tenant_identity` estiver ausente em um tenant já ativado, ou apontar para workspace inexistente, THEN o sistema SHALL abortar o reparo sem criar dados em outro workspace; um banco novo sem usuários SHALL apenas avançar sem reparo.
- IF existir mais de um funil padrão para o mesmo workspace THEN o sistema SHALL abortar com erro de integridade em vez de escolher silenciosamente.
- IF um payload de usuário contiver campos adicionais THEN o sistema SHALL preservá-los enquanto sincroniza os campos canônicos obrigatórios.
- IF outro processo continuar escutando na porta 8080 após parar a tarefa THEN o sistema SHALL abortar antes de iniciar a nova release.
- IF a aplicação saudável responder uma versão anterior THEN o sistema SHALL considerar o cutover inválido.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| DEPLOY-01 | Migração tenant consistente | Execute | In Progress |
| DEPLOY-02 | Reparação idempotente sob RLS | Execute | Verified |
| DEPLOY-03 | Provisionamento de administrador completo | Execute | Verified |
| DEPLOY-04 | Cutover Windows verificável | Execute | In Progress |
| DEPLOY-05 | Gate de release contra regressões | Execute | In Progress |

**Coverage:** 5 total, 5 mapped to tasks, 0 unmapped.

---

## Success Criteria

- [ ] O caminho de upgrade de v0.3.3 para a próxima revisão conclui sem SQL manual e deixa tenant e plano de controle na mesma revisão.
- [ ] Um tenant afetado termina com 1 funil, 9 etapas e usuários visíveis nos seletores, sem duplicação em retry.
- [ ] O inicializador em PowerShell 5.1 não falha por barras invertidas nem por stderr informativo.
- [ ] O gate confirma simultaneamente tarefa, porta, health e versão alvo antes de declarar sucesso.
- [ ] Todos os testes locais e o validador independente terminam com PASS antes de qualquer push ou deploy.
