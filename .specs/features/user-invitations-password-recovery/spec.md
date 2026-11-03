# Convites de usuários e recuperação de senha — Especificação

## Problem Statement

A tela de usuários simula convites alterando apenas o snapshot do navegador. O convidado não recebe e-mail, não cria credencial e não consegue entrar. Também não existe recuperação de senha. A v0.3.4 precisa transformar esses fluxos em operações reais, seguras e isoladas por empresa.

## Goals

- [ ] Permitir que um Administrador convide um funcionário por e-mail e acompanhe entrega, reenvio e cancelamento.
- [ ] Permitir que o convidado crie a própria senha e ative uma única conta no tenant correto.
- [ ] Permitir recuperação de senha sem revelar se uma conta existe.
- [ ] Manter tokens, senhas, sessões e auditoria protegidos contra repetição, concorrência e vazamento.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Alterar senha dentro de uma sessão autenticada | Esta versão cobre aceite inicial e recuperação por e-mail. |
| MFA e SSO | São mecanismos de autenticação separados. |
| Editor de templates | O conteúdo terá um template fixo com identidade da empresa. |
| Link manual como canal principal | O SMTP já está disponível e foi escolhido pelo usuário. |
| Limpeza física periódica de tokens antigos | A invalidação lógica atende a segurança desta versão; retenção física será tratada depois. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Canal de entrega | SMTP existente | O usuário confirmou que já possui SMTP funcional. | y |
| Experiência após o aceite | Voltar ao login sem criar sessão automática | O usuário quer que o funcionário informe e-mail e senha novamente. | y |
| Expiração | 48 horas, uso único | Limita exposição sem exigir reenvio diário. | y |
| Política de senha | 8 a 128 caracteres, sem composição obrigatória | Decisão explícita do usuário. | y |
| Autoridade administrativa | Somente Administrador; pode convidar qualquer perfil | Mantém o modelo de autorização atual e foi aprovado. | y |
| SMTP indisponível | Preservar usuário Pendente e oferecer reenvio | Evita perder o cadastro sem ativar acesso. | y |
| E-mail existente | Pendente reenvia; Ativo rejeita; Cancelado reinvita; Inativo exige reativação | Impede duplicação e preserva o ciclo de vida existente. | y |
| Recuperação | Resposta genérica, token único e revogação das sessões | Evita enumeração e encerra sessões com credencial antiga. | y |
| Botão de recuperação | Exibir na tela de login do tenant | O tenant é necessário para consultar o banco isolado correto. | y |
| Retenção | Manter metadados para auditoria e invalidar logicamente os tokens | Preserva rastreabilidade sem permitir reutilização. | y |

**Open questions:** none - all resolved or logged above.

---

## User Stories

### P1: Administrador envia e gerencia convites reais ⭐ MVP

**User Story**: Como Administrador da empresa, quero convidar funcionários por e-mail para que cada pessoa crie sua própria credencial e acesse somente o tenant correto.

**Why P1**: Sem convite real, novos usuários não conseguem obter credencial nem entrar no CRM.

**Acceptance Criteria**:

1. [INV-01] WHEN um Administrador enviar nome, e-mail, cargo, equipe e perfil válidos THEN the system SHALL criar ou reutilizar exatamente um usuário `Pendente`, com autenticação desabilitada, sem senha e com convite válido por 48 horas.
2. [INV-02] WHEN o convite for criado ou reenviado THEN the system SHALL enviar pelo SMTP um e-mail identificado como `Smart CRM — {empresa}` com um único link de aceite para o tenant correto.
3. [INV-03] IF o SMTP falhar THEN the system SHALL manter o usuário `Pendente`, invalidar qualquer token que não tenha sido entregue e retornar `deliveryStatus=failed` para a interface oferecer reenvio.
4. [INV-04] WHEN um Administrador reenviar um convite pendente THEN the system SHALL invalidar todos os convites anteriores desse usuário antes de criar e enviar um novo token.
5. [INV-05] WHEN um Administrador cancelar um convite THEN the system SHALL mudar o usuário para `Cancelado`, desabilitar autenticação e invalidar todos os tokens de convite ainda válidos.
6. [INV-06] IF o e-mail normalizado já pertencer a usuário `Ativo` THEN the system SHALL rejeitar o convite sem enviar e-mail e sem alterar o usuário.
7. [INV-07] WHEN o e-mail normalizado pertencer a usuário `Cancelado` THEN the system SHALL reutilizar a mesma conta, atualizar os dados administrativos e iniciar um novo convite pendente.
8. [INV-08] IF o e-mail normalizado pertencer a usuário `Inativo` THEN the system SHALL exigir reativação administrativa e SHALL NOT criar nova conta ou convite.
9. [INV-09] IF um usuário sem perfil `Administrador` tentar criar, reenviar ou cancelar convite THEN the system SHALL responder `403` sem escrita no banco e sem envio SMTP.
10. [INV-10] WHILE o usuário estiver `Pendente` ou `Cancelado`, the system SHALL impedir login e SHALL NOT oferecê-lo como responsável ou assistente nos cadastros comerciais.

**Independent Test**: Convidar um funcionário, verificar o e-mail capturado, reenviar e cancelar; repetir com e-mails Ativo, Inativo, Pendente e Cancelado e conferir uma única conta persistida.

---

### P1: Convidado aceita e cria a própria senha ⭐ MVP

**User Story**: Como funcionário convidado, quero criar minha senha pelo link recebido para ativar minha conta com segurança.

**Why P1**: O convite só tem valor quando produz uma credencial utilizável e vinculada à empresa correta.

**Acceptance Criteria**:

1. [ACCEPT-01] WHEN um token de convite válido for aberto THEN the system SHALL exibir o nome da empresa, o e-mail convidado e formulário de senha sem criar sessão autenticada.
2. [ACCEPT-02] WHEN senha e confirmação idênticas tiverem entre 8 e 128 caracteres THEN the system SHALL persistir somente o hash Argon2id, marcar o usuário `Ativo`, habilitar autenticação, consumir o token e incrementar `auth_version` uma única vez.
3. [ACCEPT-03] WHEN o aceite concluir THEN the system SHALL direcionar o usuário à tela de login do tenant com confirmação de conta ativada e sem sessão automática.
4. [ACCEPT-04] IF o token estiver ausente, vencido, usado, cancelado, substituído ou vinculado a outro tenant THEN the system SHALL rejeitar o aceite com a mesma mensagem pública e sem alterar usuário ou credencial.
5. [ACCEPT-05] IF senha e confirmação divergirem ou a senha tiver menos de 8 ou mais de 128 caracteres THEN the system SHALL rejeitar o aceite e manter o token disponível até expirar ou ser usado corretamente.
6. [ACCEPT-06] WHEN duas requisições tentarem consumir o mesmo convite THEN the system SHALL aceitar exatamente uma e rejeitar as demais sem incrementar novamente `auth_version`.

**Independent Test**: Aceitar o convite com senha válida, confirmar redirecionamento ao login e autenticar; repetir o mesmo token e executar duas aceitações concorrentes para comprovar uso único.

---

### P1: Usuário recupera a senha pelo login ⭐ MVP

**User Story**: Como usuário que esqueceu a senha, quero receber um link seguro para criar outra senha e voltar a entrar no CRM.

**Why P1**: Sem recuperação, qualquer perda de credencial exige intervenção técnica no servidor.

**Acceptance Criteria**:

1. [RESET-01] WHEN qualquer pessoa solicitar recuperação na tela de login de uma empresa THEN the system SHALL responder `202` com `Se o e-mail existir, enviaremos as instruções.` independentemente de tenant, e-mail, estado da conta ou resultado do SMTP.
2. [RESET-02] WHEN a solicitação corresponder a usuário `Ativo` com autenticação habilitada THEN the system SHALL invalidar tokens de recuperação anteriores e tentar enviar um link novo, válido por 48 horas, para o e-mail cadastrado.
3. [RESET-03] IF o tenant, usuário ou SMTP estiver indisponível THEN the system SHALL manter a resposta pública de RESET-01 e registrar internamente o resultado sem criar ou ativar conta.
4. [RESET-04] WHEN senha e confirmação válidas forem enviadas com token de recuperação válido THEN the system SHALL substituir o hash Argon2id, consumir o token, incrementar `auth_version` uma vez e revogar todas as sessões anteriores do usuário.
5. [RESET-05] WHEN a redefinição concluir THEN the system SHALL direcionar o usuário à tela de login do tenant com confirmação de senha alterada e sem sessão automática.
6. [RESET-06] IF o token estiver ausente, vencido, usado, cancelado, substituído ou vinculado a outro tenant THEN the system SHALL rejeitar a redefinição com uma única mensagem pública e sem alterar hash, versão ou sessões.

**Independent Test**: Solicitar recuperação para e-mail existente e inexistente, comparar respostas públicas, redefinir a senha, confirmar revogação das sessões e provar que token e senha antigos não funcionam.

---

### P1: Limites, auditoria e segredo ⭐ MVP

**User Story**: Como responsável pela segurança, quero que convites e recuperação resistam a abuso e não exponham credenciais ou tokens.

**Why P1**: Esses fluxos públicos concedem acesso e não podem virar canal de enumeração, spam ou replay.

**Acceptance Criteria**:

1. [SEC-01] The system SHALL gerar tokens com entropia criptográfica e persistir somente digest não reversível, propósito, usuário, tenant, expiração e estado de consumo.
2. [SEC-02] The system SHALL NOT registrar senha, hash de senha, token bruto, credencial SMTP ou DSN em banco de auditoria, log, resposta ou evento.
3. [SEC-03] WHILE houver 5 solicitações para a mesma conta em 15 minutos, the system SHALL bloquear novos envios para essa conta até o fim da janela sem revelar sua existência.
4. [SEC-04] WHILE houver 30 solicitações originadas do mesmo IP em 15 minutos, the system SHALL bloquear novos envios desse IP até o fim da janela.
5. [SEC-05] WHEN criação, envio, falha, reenvio, cancelamento, aceite ou redefinição ocorrer THEN the system SHALL registrar evento de segurança com tenant quando conhecido, usuário quando conhecido, digest de correlação, resultado e horário.
6. [SEC-06] WHEN um token expirar, for consumido, cancelado ou substituído THEN the system SHALL impedir permanentemente seu uso mesmo após reenvio, reinício do serviço ou nova solicitação.
7. [SEC-07] IF o link for apresentado ao tenant errado THEN the system SHALL rejeitar a operação antes de abrir ou alterar o banco de outro tenant.

**Independent Test**: Inspecionar banco, logs e eventos após sucesso e falha; exceder os dois limites; tentar replay, troca de tenant e uso após reinício.

---

### P1: Interface substitui a simulação ⭐ MVP

**User Story**: Como Administrador, quero que a tela atual reflita o estado real dos convites para gerenciar acesso sem comandos técnicos.

**Why P1**: Manter a simulação permitiria divergência entre o navegador e as credenciais reais.

**Acceptance Criteria**:

1. [INVUI-01] WHEN o Administrador abrir `Usuários e permissões` THEN the system SHALL carregar usuários e estados de convite do banco tenant sem usar criação simulada no navegador.
2. [INVUI-02] WHEN criar, reenviar ou cancelar concluir THEN the system SHALL atualizar a linha correspondente com estado e resultado de entrega confirmados pelo servidor.
3. [INVUI-03] IF a entrega falhar THEN the system SHALL mostrar que o usuário permanece pendente e oferecer `Reenviar` sem afirmar que o e-mail foi enviado.
4. [INVUI-04] WHEN a tela de login do tenant for exibida THEN the system SHALL oferecer `Esqueci minha senha` e manter a mensagem pública genérica após a solicitação.
5. [INVUI-05] WHILE o visitante estiver na tela de aceite ou redefinição, the system SHALL mostrar estados acessíveis de carregamento, validação, sucesso e link inválido sem expor detalhes internos.

**Independent Test**: Executar o fluxo completo em desktop e viewport móvel, incluindo SMTP capturado, falha de entrega, reenvio, aceite, login e recuperação.

---

## Implicit Requirement Dimensions

| Dimension | Resolution |
| --------- | ---------- |
| Input validation & bounds | E-mail normalizado; senha de 8 a 128; campos administrativos usam limites existentes. |
| Failure / partial-failure states | Falha SMTP preserva Pendente; recuperação mantém resposta genérica; aceite é transacional. |
| Idempotency / retry / duplicate handling | Um usuário por e-mail normalizado; reenvio substitui token; consumo é único. |
| Auth boundaries & rate limits | Administração exclusiva; 5 por conta e 30 por IP em 15 minutos. |
| Concurrency / ordering | Bloqueio transacional garante um único consumo e um único incremento de versão. |
| Data lifecycle / expiry | Tokens expiram em 48 horas e permanecem logicamente inválidos após qualquer término. |
| Observability | Eventos redigidos para todas as transições relevantes. |
| External-dependency failure | SMTP falho não ativa conta nem produz afirmação falsa de entrega. |
| State-transition integrity | Pendente → Ativo/Cancelado; Cancelado → Pendente; Inativo exige reativação explícita. |

---

## Edge Cases

- IF dois Administradores convidarem simultaneamente o mesmo e-mail THEN the system SHALL persistir uma conta e no máximo um convite válido.
- IF o endereço SMTP aceitar a conexão e rejeitar a mensagem THEN the system SHALL tratar o resultado como falha de entrega e manter o usuário Pendente.
- IF um usuário for inativado depois de solicitar recuperação THEN the system SHALL rejeitar o token sem alterar a conta.
- IF um convite for cancelado enquanto a página de aceite estiver aberta THEN the system SHALL rejeitar o envio subsequente da senha.
- WHEN o perfil convidado for `Administrador` THEN the system SHALL exigir a mesma autorização administrativa e auditoria dos demais perfis.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| INV-01 | P1: Gerenciar convites | Execute | T3, T5 and T6 complete; T9–T12, T14 pending |
| ACCEPT-01 | P1: Aceitar convite | Execute | T3 and T7 complete; T10, T11, T13 pending |
| RESET-01 | P1: Recuperar senha | Execute | T3–T5 complete; T8, T10, T11, T13, T14 pending |
| SEC-01 | P1: Segurança | Execute | T1–T7 complete; T8, T9, T13, T14 pending |
| INVUI-01 | P1: Interface real | Tasks | Mapped to T9, T10, T12, T13 |

**Coverage:** 5 requirement groups, 5 mapped to tasks, 0 pending design.

---

## Success Criteria

- [ ] Um Administrador envia, reenvia e cancela convite real sem criar conta duplicada.
- [ ] Um convidado aceita uma vez, cria senha e entra somente após autenticar na tela de login.
- [ ] Solicitações de recuperação não revelam se tenant ou e-mail existe.
- [ ] Uma senha redefinida revoga todas as sessões e torna link e senha anteriores inutilizáveis.
- [ ] Nenhum token bruto, senha ou credencial SMTP aparece em persistência de auditoria, logs ou respostas.
- [ ] Fluxos completos passam no backend, SMTP de teste, interface desktop e viewport móvel.

