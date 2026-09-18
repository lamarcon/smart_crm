# Multiempresa Seguro Context

**Gathered:** 2026-09-14
**Spec:** .specs/features/secure-multitenancy/spec.md
**Status:** Approved

---

## Feature Boundary

Esta feature mantém uma aplicação central em sc2030.brbots.com, identifica empresas por /{slug}, autentica contra o PostgreSQL exclusivo daquela empresa e mantém a sessão opaca no plano de controle central. Ela aplica isolamento e perfis no backend, preserva o frontend monolítico e o contrato de snapshot quando isso não reduz a segurança. Não inclui subdomínios, uma aplicação por cliente, cadastro público, criação do servidor PostgreSQL, SSO/MFA, deploy nem alterações em servidor.

---

## Implementation Decisions

### Topologia escolhida

- O usuário confirmou uma única aplicação central com sessão opaca central e um PostgreSQL de negócio separado por empresa.
- O plano de controle central conterá apenas diretório de tenants, referências de segredos, sessões, throttling e eventos de segurança; usuários, hashes e dados comerciais permanecem no banco da empresa.
- A URL pública identifica o tenant somente antes do login. Depois da autenticação, o tenant_id da sessão central é a única entrada do roteador de banco.
- O banco atual do workspace default será preservado como banco de negócio do primeiro tenant; dados comerciais não serão copiados para o plano de controle.

### Rota e autenticação

- / será uma tela pública mínima para receber slug ou URL do domínio sc2030.brbots.com.
- O parser aceitará somente o host esperado e exatamente um segmento de tenant.
- Um tenant localizado abrirá /{slug}; a API autenticada continuará em /api/... e derivará o tenant da sessão.
- O login usará o slug apenas para resolver no servidor o banco contra o qual a credencial será verificada.
- Uma sessão de outro tenant em /{slug} será rejeitada, nunca remapeada.
- Falhas de empresa, conexão, e-mail, senha ou estado usarão a mesma mensagem pública.

### Credenciais e sessão

- Senhas e estado de usuário residirão no banco da empresa e usarão Argon2id via wheel fixada para CPython 3.11 x64.
- O runtime fará verificação com hash fictício quando tenant, conexão ou usuário não existir.
- O cookie conterá token CSPRNG bruto; o plano de controle guardará apenas SHA-256, tenant_id, user_id, auth_version e metadados de expiração.
- O cookie será __Host-smartcrm_session; Secure; HttpOnly; SameSite=Strict; Path=/, sem Domain.
- Logout, TTLs, mudança de senha/perfil/status e revogação administrativa invalidarão sessões centrais.
- Métodos inseguros validarão Origin contra a origem HTTPS configurada.

### Roteamento de banco e isolamento

- Um TenantDatabaseRouter receberá somente o tenant_id confiável da sessão, localizará uma referência de conexão e carregará o segredo por provider do servidor.
- DSN, host, database, role ou segredo enviados pelo navegador jamais serão considerados.
- A produção usará segredo cifrado por DPAPI para a conta do serviço; desenvolvimento e testes poderão usar referências de ambiente sem valores versionados.
- Cada abertura validará a identidade do banco contra o tenant esperado antes das consultas; identidade divergente, timeout ou schema incompatível falham fechado sem fallback.
- Pools SQLAlchemy serão criados sob demanda, limitados e isolados por tenant; invalidar um pool não afetará os demais.
- Nenhum serviço ou repositório terá workspace_id=default como valor implícito.
- workspace_id continuará nas linhas e em contexto transacional. RLS forçada será defesa adicional contra roteamento incorreto ou consulta sem contexto.
- Como cada database terá um tenant, não será necessário trocar todas as chaves primárias por chaves compostas apenas para permitir IDs iguais entre empresas.

### Autorização e navegador

- O endpoint de sessão devolverá identidade e tenant; o frontend exibirá o usuário sem seletor.
- O backend projetará o snapshot conforme o perfil e mesclará saves parciais com linhas invisíveis canônicas.
- Administrador mantém ações administrativas. Gestor mantém escopo de equipe. Vendedor, Assistente e Faturamento mantêm escopo por responsabilidade ou assistência. Contatos e Empresas permanecem tenant-wide.
- Credenciais, sessão, tenant autorizado e perfil nunca serão gravados em Web Storage.
- Snapshots comerciais persistentes serão removidos do localStorage.
- Preferências de UI poderão usar smart-crm:{tenant-id}:{user-id}:... e nunca autorizarão acesso.

### Provisionamento e frota

- O plano de controle começará em database próprio junto da aplicação; essa localização poderá mudar sem alterar os bancos dos tenants.
- O servidor, database, role, TLS, allowlist e backup do cliente deverão estar prontos antes do registro.
- O provisionamento entre bancos será uma máquina de estados idempotente. Somente active aceita login; falha mantém provisioning ou failed e permite retomada segura.
- A ferramenta local usará getpass para senha do primeiro administrador e segredo de conexão, armazenará apenas referência cifrada e nunca imprimirá segredos.
- Haverá cadeias Alembic separadas para control e tenant, além de preflight e aplicação explícita por tenant. Nenhuma requisição web executará migração.
- Usuários existentes não receberão senha inventada e ficam sem login até provisionamento explícito.
- Não haverá endpoint público para criar tenant ou primeiro administrador.
- Apache Basic Auth poderá permanecer em homologação e será removido somente em corte autorizado após UAT.
- O primeiro tenant de produção usará slug `brbots`, nome exibido `brbots`, administrador `Luiz Felipe` e e-mail `lfmarcon@brbots.com`; nenhuma senha foi registrada na especificação.
- O banco atual do aplicativo permanecerá como banco de negócio do tenant `brbots`; um database separado `smartcrm_control` será criado na mesma instância PostgreSQL 11 para o plano de controle.
- A tarefa Windows usará uma conta dedicada `SmartCRMService`. O CLI administrativo e o runtime deverão operar sob essa mesma identidade para que o DPAPI permaneça vinculado à conta do serviço.
- Releases serão instaladas lado a lado em diretórios versionados. A versão ativa e o Apache somente mudarão dentro de uma janela de corte autorizada separadamente.

### Agent's Discretion

- Nomes internos de módulos, interfaces e eventos, desde que preservem as fronteiras descritas.
- Política exata do cache limitado de engines, respeitando isolamento, descarte seguro e limites configuráveis.
- Layout das telas de localização e login, preservando o estilo atual e acessibilidade por teclado.
- Frequência de atualização de last_seen_at, desde que a expiração de 30 minutos seja respeitada.

### Declined / Undiscussed Gray Areas → Assumptions

- A senha inicial do administrador, a senha da conta `SmartCRMService`, as credenciais dos bancos, a janela de mudança e a autorização de acesso ao servidor serão fornecidas somente no ambiente operacional e permanecem fora desta implementação local.
- O onboarding por convite ou e-mail permanece fora de escopo; credenciais adicionais poderão ser atribuídas localmente até uma feature própria.

---

## Specific References

- Topologia escolhida pelo usuário: /cliente-a, /cliente-b e /cliente-c convergem para uma aplicação central, que usa sessão opaca central para rotear a PostgreSQLs separados.
- URL escolhida: https://sc2030.brbots.com/{identificador-da-empresa}.
- Runtime interno: 127.0.0.1:8080 atrás do Apache.
- Compatibilidade mínima: PostgreSQL 11 e pacote Windows offline.
- O seletor atual de perfil não deve sobreviver como controle editável.

---

## Deferred Ideas

- SSO, MFA, convites e recuperação de senha por e-mail.
- CRUD REST granular por entidade.
- Réplicas de leitura, sharding ou failover automático por tenant.
- Aplicação dedicada por tenant regulado.
- Automação da infraestrutura PostgreSQL do cliente.
