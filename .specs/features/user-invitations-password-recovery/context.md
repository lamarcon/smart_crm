# Convites de usuários e recuperação de senha — Contexto

**Coletado em:** 2026-10-30
**Spec:** `.specs/features/user-invitations-password-recovery/spec.md`
**Status:** Confirmado

---

## Limite da funcionalidade

A v0.3.4 substituirá os convites simulados por convites reais enviados pelo SMTP já disponível. O funcionário aceitará o convite, criará sua própria senha e depois fará login normalmente. A tela de login também ganhará o fluxo `Esqueci minha senha` por e-mail.

---

## Decisões de implementação

### Entrega e identidade do e-mail

- O fluxo principal enviará e-mail real pelo SMTP existente.
- O remetente visível combinará `Smart CRM` com o nome da empresa.
- O assunto identificará a empresa que fez o convite.
- O endereço real de envio virá da configuração SMTP do servidor.
- Link manual não será o fluxo principal desta versão.

### Convite e aceite

- Somente `Administrador` poderá convidar, reenviar, cancelar e reativar usuários.
- O administrador poderá escolher qualquer perfil existente, inclusive `Administrador`.
- O funcionário criará a própria senha ao aceitar o convite.
- Depois do aceite, o funcionário voltará à tela de login e informará e-mail e senha novamente.
- Convites valerão por 48 horas, serão de uso único e o reenvio invalidará o link anterior.
- Convite e aceite concorrentes não criarão contas duplicadas; somente o primeiro aceite válido vencerá.

### Estados de usuário

- E-mail `Pendente`: reenviar o convite e invalidar o link anterior.
- E-mail `Ativo`: informar que o usuário já existe e não enviar convite.
- E-mail `Cancelado`: permitir um novo convite reutilizando a conta.
- E-mail `Inativo`: exigir reativação administrativa, sem criar outra conta.
- Usuário pendente não poderá entrar nem aparecer como responsável ou assistente até aceitar o convite.

### Falha do SMTP

- Se o envio falhar, o usuário continuará `Pendente`.
- A interface informará que o cadastro foi criado, mas o e-mail não foi entregue.
- O administrador poderá usar `Reenviar` para gerar um link novo.
- Nenhuma conta será ativada por falha ou indisponibilidade do SMTP.

### Senha e recuperação

- Senhas terão de 8 a 128 caracteres e confirmação idêntica.
- Não haverá exigência artificial de maiúscula, número ou símbolo.
- `Esqueci minha senha` ficará disponível na tela de login.
- A solicitação sempre responderá com mensagem genérica, sem revelar se o e-mail existe.
- O link de redefinição valerá por 48 horas, será de uso único e invalidará todas as sessões anteriores após a troca.
- Depois da redefinição, o usuário voltará à tela de login.

### Segurança, limites e auditoria

- Tokens serão aleatórios; somente o digest será persistido.
- Haverá limite de 5 solicitações por conta em 15 minutos e 30 por IP no mesmo período.
- A auditoria registrará criação, envio, falha, reenvio, cancelamento, aceite e redefinição sem senha ou token bruto.
- Registros permanecerão para auditoria, mas tokens vencidos, usados, cancelados ou substituídos nunca voltarão a funcionar.

### Discrição do agente

- Texto exato e apresentação visual dos e-mails, respeitando a identidade definida.
- Organização interna dos componentes de SMTP, token e persistência.
- Mensagens técnicas de log, desde que não exponham segredo ou dado além do necessário.

### Áreas não discutidas convertidas em premissas

- O botão de recuperação será mostrado somente na tela de login da empresa, pois a empresa é necessária para localizar o banco correto.
- A reativação de usuário `Inativo` continuará como ação administrativa existente e não enviará convite automaticamente.
- A limpeza física de registros antigos não faz parte desta versão; a validade lógica impede reutilização.

---

## Referências específicas

- Manter a tela atual `Usuários e permissões`, substituindo o comportamento simulado por operações reais.
- E-mail da BRBots: remetente visível semelhante a `Smart CRM — BRBots` e assunto `Você foi convidado para o Smart CRM da BRBots`.

---

## Ideias adiadas

- Alteração voluntária de senha dentro do CRM.
- MFA e SSO.
- Editor de templates de e-mail.
- Link copiável como canal alternativo ao SMTP.

