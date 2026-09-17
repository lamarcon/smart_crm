# Multiempresa Seguro Specification

## Problem Statement

O Smart CRM usa um único workspace default, aceita o estado completo enviado pelo navegador e aplica identidade e permissões apenas no JavaScript. Esse desenho não fornece autenticação individual nem uma fronteira segura entre empresas. A aplicação central deverá atender todas as URLs por caminho, enquanto cada empresa mantém usuários e dados de negócio em seu próprio PostgreSQL; o banco de destino será derivado exclusivamente da sessão opaca central e nunca de um parâmetro livre do navegador.

## Goals

- [x] Autenticar usuários por empresa com senha Argon2id e sessão opaca armazenada no plano de controle central.
- [x] Manter usuários e dados de negócio de cada tenant em um PostgreSQL exclusivo e impedir seleção, leitura ou mutação em banco de outra empresa.
- [x] Aplicar perfis e visibilidade no backend, sem confiar em perfil, tenant, cache, rota ou localStorage enviados pelo navegador.
- [x] Transformar o banco atual do workspace default no banco do primeiro tenant sem copiar nem perder os dados existentes.
- [x] Provisionar tenants e o primeiro administrador por ferramenta administrativa idempotente, sem cadastro público.
- [x] Operar conexões, migrações, saúde e recuperação como uma frota de bancos compatível com PostgreSQL 11 e o pacote offline Windows.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Subdomínios por empresa | A rota por caminho já foi escolhida para esta fase. |
| Uma instalação da aplicação por empresa | Foi escolhida uma única aplicação central. |
| Cadastro público de empresas | O provisionamento será administrativo. |
| Criação automática do servidor PostgreSQL do cliente | O servidor, database, role, rede e backup devem existir antes do registro do tenant. |
| SSO, OAuth externo e MFA | Exigem decisões e integrações próprias; ficam para uma feature posterior. |
| Recuperação de senha e convite por e-mail | Não existe provedor de e-mail no runtime offline atual. |
| Reescrita completa para CRUD REST granular | O recorte preserva o contrato de snapshot com projeção e merge autorizados no servidor. |
| Deploy, push ou alteração de qualquer servidor | Exigem autorização explícita separada. |

---

## Assumptions & Open Questions

Cada decisão abaixo tem um default proposto. A aprovação deste plano confirma os defaults, salvo indicação contrária do usuário.

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Topologia multiempresa | Aplicação central, plano de controle central e um PostgreSQL de negócio exclusivo por empresa | Escolha explícita do usuário para isolamento físico e escalabilidade futura | y |
| Conteúdo do plano de controle | Diretório de tenants, referências de segredo, sessões, throttling e auditoria de segurança; nenhum usuário, hash de senha ou dado comercial | Permite roteamento e sessões centralizadas sem transformar o banco central em repositório dos clientes | y |
| Local inicial do plano de controle | Database separado smartcrm_control no PostgreSQL 11 junto da aplicação; pode ser movido depois | Evita nova infraestrutura no primeiro corte e mantém separação lógica do banco de negócio | y |
| Credenciais dos bancos | Referências no plano de controle e segredos cifrados com DPAPI para a conta do serviço; variáveis de ambiente apenas em desenvolvimento/testes | Evita DSN e senha em texto claro no banco central e é compatível com Windows Server offline | y |
| Rede com bancos remotos | TLS com validação de certificado e allowlist do IP da aplicação; falha fechada quando indisponível | Bancos de clientes não devem aceitar conexão pública irrestrita nem fallback para outro tenant | y |
| Contrato de persistência do frontend | Preservar o snapshot versionado, com projeção e merge autorizados no servidor | Evita reescrita total do monólito e fecha o bypass atual do PUT integral | y |
| Visibilidade por perfil dentro do tenant | Preservar regras atuais para Leads/Negócios; Contatos/Empresas visíveis ao tenant; ações administrativas somente para Administrador | Mantém comportamento atual e move a decisão de segurança para o servidor | y |
| Cache de dados comerciais | Remover snapshots comerciais do localStorage; manter apenas preferências de UI por tenant e usuário | Evita mistura e exposição de dados em máquinas compartilhadas | y |
| Sessão | Inatividade de 30 minutos e limite absoluto de 12 horas | Equilibra uso interno e revogação previsível | y |
| Cookie | __Host-smartcrm_session, Secure, HttpOnly, SameSite=Strict, Path=/ e sem Domain | Proteção forte compatível com o domínio único e tenants por caminho | y |
| Proteção de login | 5 falhas por conta/tenant em 15 minutos e 30 por IP em 15 minutos bloqueiam por 15 minutos | Combina proteção da conta e da origem | y |
| Política de senha | 12 a 128 caracteres, sem truncamento e sem composição artificial | Favorece senhas longas e evita transformação silenciosa | y |
| Identificador do primeiro tenant | Informado na ativação; o ID interno default permanece no banco atual | A URL comercial ainda não foi fornecida e não precisa alterar chaves existentes | y |
| Usuários existentes sem credencial | Ficam sem login até receberem hash por ferramenta administrativa; o primeiro administrador é habilitado no corte | Não existe senha legada segura para migrar | y |
| Provisionamento distribuído | Fluxo idempotente provisioning → active; qualquer falha mantém o tenant não autenticável e permite retomada | Dois bancos independentes não compartilham transação SQL atômica | y |
| Migrações da frota | Duas cadeias Alembic, control e tenant; preflight global e aplicação explícita por tenant, nunca durante uma requisição | Evita drift silencioso e falha em massa | y |
| RLS no banco de negócio | Manter workspace_id, contexto transacional e RLS forçada como detector de conexão incorreta; não criar chaves compostas apenas para permitir IDs repetidos entre bancos | O database dedicado já separa IDs; RLS fecha falhas de roteamento e consultas sem contexto | y |
| Apache Basic Auth | Manter apenas em homologação e remover no corte autorizado | A autenticação individual substitui a senha compartilhada | y |

**Open questions:** none - todas as escolhas ainda não confirmadas estão registradas como defaults de aprovação.

---

## User Stories

### P1: Localizar a empresa e autenticar no banco correto

**User Story**: Como usuário de uma empresa cliente, quero acessar a URL da minha empresa e entrar com e-mail e senha para abrir somente o CRM dessa empresa.

**Why P1**: Sem vínculo verificável entre rota, credencial, sessão e banco de negócio, nenhuma operação pode ser considerada segura.

**Acceptance Criteria**:

1. WHEN um visitante abrir / THEN the system SHALL exibir um campo que aceite um slug ou uma URL do próprio domínio e normalize o identificador para minúsculas.
2. WHEN um identificador válido e ativo for localizado no plano de controle THEN the system SHALL navegar para /{slug} e exibir o login daquele tenant sem criar sessão.
3. WHEN um login for enviado para /{slug} THEN the system SHALL resolver internamente o perfil de conexão registrado e verificar e-mail, hash e estado do usuário somente no banco de negócio desse tenant.
4. IF empresa, conexão, e-mail, senha ou estado forem inválidos THEN the system SHALL responder com a mensagem Não foi possível entrar com os dados informados. sem revelar qual dado falhou.
5. WHEN uma senha for criada ou alterada THEN the system SHALL armazenar somente um hash Argon2id com salt único no banco de negócio do tenant e jamais persistir ou registrar a senha em texto puro.
6. IF o tenant, a conexão ou o usuário não existir THEN the system SHALL executar uma verificação Argon2id contra hash fictício antes de responder.
7. IF ocorrerem 5 falhas para a mesma conta e tenant em 15 minutos THEN the system SHALL bloquear novas tentativas dessa chave por 15 minutos e manter a mensagem pública genérica.
8. IF ocorrerem 30 falhas do mesmo IP em 15 minutos THEN the system SHALL bloquear novas tentativas desse IP por 15 minutos e manter a mensagem pública genérica.

**Independent Test**: Acessar /, informar slug, autenticar com credenciais existentes apenas em um banco e repetir com tenant, conexão, e-mail, senha, estado e limites inválidos, comparando mensagem e ausência de sessão.

### P1: Manter sessão opaca central e revogável

**User Story**: Como usuário autenticado, quero uma sessão segura e revogável para que credencial, tenant e identidade não fiquem acessíveis ao JavaScript.

**Why P1**: A sessão é a única fonte autorizada para selecionar o tenant após o login.

**Acceptance Criteria**:

1. WHEN o login for aceito THEN the system SHALL gerar um identificador opaco com pelo menos 128 bits de entropia e armazenar no plano de controle somente seu digest SHA-256.
2. WHEN o login for aceito THEN the system SHALL vincular no servidor a sessão ao tenant e ao ID do usuário autenticado sem armazenar o hash de senha no plano de controle.
3. WHEN o login for aceito THEN the system SHALL enviar a sessão apenas no cookie __Host-smartcrm_session com Secure, HttpOnly, SameSite=Strict, Path=/ e sem Domain.
4. The system SHALL rejeitar tokens de sessão recebidos por URL, corpo, localStorage, sessionStorage ou header de aplicação.
5. WHILE a sessão estiver ativa, the system SHALL expirá-la após 30 minutos de inatividade ou 12 horas desde a criação, o que ocorrer primeiro.
6. WHEN o usuário fizer logout THEN the system SHALL revogar a sessão no plano de controle e expirar o cookie no navegador.
7. WHEN senha, perfil, status ou versão de autenticação do usuário mudar THEN the system SHALL revogar todas as sessões anteriores desse usuário.
8. WHEN uma requisição autenticada usar método inseguro THEN the system SHALL validar a origem HTTPS esperada antes de executar qualquer mutação.

**Independent Test**: Entrar, verificar cookie e registro central, confirmar ausência do token nas APIs e no armazenamento JavaScript, e testar expiração, logout, mudança de perfil e origem inválida.

### P1: Rotear e isolar todas as operações por tenant

**User Story**: Como empresa cliente, quero que cada requisição use exclusivamente meu PostgreSQL para preservar confidencialidade e integridade.

**Why P1**: O banco dedicado é a fronteira principal de isolamento escolhida.

**Acceptance Criteria**:

1. WHILE uma sessão autenticada estiver ativa, the system SHALL derivar tenant, usuário e perfil a partir da sessão central e do usuário validado no banco de negócio vinculado.
2. WHEN uma API de negócio for chamada THEN the system SHALL selecionar o perfil de conexão por tenant_id da sessão usando somente o registro e a referência de segredo do servidor.
3. IF o navegador enviar tenant, workspace, perfil de conexão, DSN, usuário ou perfil no corpo, query ou header THEN the system SHALL ignorar esses valores para roteamento e autorização.
4. WHEN uma conexão de negócio for aberta THEN the system SHALL verificar que a identidade imutável do banco corresponde ao tenant da sessão antes de executar qualquer consulta tenant-owned.
5. IF a identidade do banco não corresponder ao tenant da sessão THEN the system SHALL falhar fechado, registrar o evento e não consultar, alterar nem tentar outro banco.
6. The system SHALL exigir workspace_id explícito em toda consulta e mutação tenant-owned, sem default default em serviços ou repositórios.
7. WHILE uma transação de negócio estiver ativa, the system SHALL configurar o workspace no PostgreSQL e aplicar RLS forçada com USING e WITH CHECK nas tabelas tenant-owned.
8. WHEN dois tenants possuírem o mesmo ID público THEN the system SHALL ler e alterar somente o registro no PostgreSQL selecionado pela sessão autenticada.
9. IF um ID existir apenas no PostgreSQL de outro tenant THEN the system SHALL responder como registro não encontrado e manter ambos os bancos inalterados.
10. IF o tenant da rota /{slug} não corresponder ao tenant da sessão THEN the system SHALL rejeitar o acesso sem trocar o tenant ou a conexão da sessão.
11. IF o PostgreSQL do tenant estiver indisponível THEN the system SHALL responder indisponibilidade temporária sem usar cache comercial nem fallback para outro tenant.

**Independent Test**: Configurar dois bancos com IDs públicos idênticos, forjar rota, corpo, headers e registro de conexão, e executar cargas, saves, exclusões e restores, verificando respostas e estado SQL de ambos.

### P1: Aplicar perfis no servidor e remover troca de identidade

**User Story**: Como administrador da empresa, quero que cada usuário mantenha sua identidade e permissões reais durante toda a sessão.

**Why P1**: O seletor atual permite personificação e as regras visuais podem ser contornadas por chamadas diretas.

**Acceptance Criteria**:

1. WHEN o frontend carregar uma sessão válida THEN the system SHALL obter o usuário atual do backend e exibi-lo como informação não editável.
2. The system SHALL remover o seletor que altera currentUserId e impedir que dados locais mudem a identidade efetiva.
3. WHILE o usuário for Administrador, the system SHALL permitir gerenciamento de usuários, campos, importação, reset e recuperação de excluídos somente no banco de seu tenant.
4. WHILE o usuário for Gestor, the system SHALL permitir leitura e mutação apenas de Leads e Negócios de sua equipe, além de Contatos e Empresas do tenant.
5. WHILE o usuário for Vendedor, Assistente ou Faturamento, the system SHALL permitir leitura e mutação apenas de Leads e Negócios atribuídos ou assistidos por ele, além de Contatos e Empresas do tenant.
6. IF um usuário não Administrador modificar usuários, perfis, estados de acesso, campos globais, importação, reset ou recuperação THEN the system SHALL responder 403 e manter o banco inalterado.
7. IF uma resposta de workspace contiver registros fora da visibilidade do perfil THEN the system SHALL removê-los no servidor antes de serializar a resposta.
8. WHEN um snapshot parcial autorizado for salvo THEN the system SHALL mesclá-lo com registros invisíveis canônicos sem excluir ou alterar esses registros.

**Independent Test**: Repetir operações com os cinco perfis, inclusive requisições fabricadas, e comparar os registros visíveis e modificáveis no banco correto.

### P1: Preservar o banco atual e provisionar novos tenants

**User Story**: Como operador autorizado, quero ativar o banco atual e registrar novos bancos de empresa sem perda de dados nem estado parcialmente ativo.

**Why P1**: O primeiro cliente deve sobreviver ao corte e os seguintes precisam de onboarding repetível.

**Acceptance Criteria**:

1. WHEN a migração tenant for aplicada ao banco atual THEN the system SHALL preservar o ID interno default e todas as linhas, payloads e vínculos existentes sem copiar dados comerciais para o plano de controle.
2. WHEN o primeiro tenant for ativado THEN the system SHALL registrar no plano de controle a referência ao banco atual e comprovar contagens e integridade iguais às anteriores, exceto por estruturas novas.
3. WHEN um novo tenant for provisionado THEN the system SHALL manter seu estado provisioning até conexão, identidade do banco, schema, primeiro Administrador e hash de senha serem validados.
4. IF qualquer etapa de provisionamento falhar THEN the system SHALL impedir login, registrar a falha sem segredo e permitir retomada idempotente sem duplicar tenant ou administrador.
5. WHEN um operador executar a ferramenta administrativa local THEN the system SHALL solicitar senha e segredo de conexão por entrada oculta e não imprimir nem armazenar seus valores em texto puro.
6. The system SHALL manter inexistente qualquer endpoint público de criação de tenant ou primeiro administrador.
7. The system SHALL usar dependências fixadas com wheels CPython 3.11 x64 disponíveis no pacote offline e SQL compatível com PostgreSQL 11.
8. WHEN a aplicação iniciar ou um tenant for ativado THEN the system SHALL rejeitar schema tenant incompatível com a versão suportada sem executar migração automática.

**Independent Test**: Ativar uma cópia representativa do banco atual, comparar hashes e contagens, e testar criação, falha intermediária, retomada e duplicidade em dois bancos independentes.

### P2: Operar a frota e observar com segurança

**User Story**: Como operador, quero diagnosticar sessões, conexões e versões sem expor segredos ou misturar empresas.

**Why P2**: O isolamento físico amplia a superfície operacional e precisa ser verificável.

**Acceptance Criteria**:

1. WHEN login, logout, bloqueio, revogação, falha de roteamento ou negação ocorrer THEN the system SHALL registrar event_id, tenant quando conhecido, usuário quando conhecido e digest de correlação sem senha, token bruto ou DSN.
2. IF uma API protegida for chamada sem sessão válida THEN the system SHALL responder 401 com payload estável e sem estado do workspace.
3. IF uma API protegida for chamada por perfil insuficiente THEN the system SHALL responder 403 com payload estável e sem indicar existência de dado de outro tenant.
4. WHEN respostas de login, logout, sessão ou workspace forem emitidas THEN the system SHALL enviar Cache-Control: no-store.
5. WHILE um tenant estiver inativo, provisioning ou com schema incompatível THEN the system SHALL negar novos logins e sessões existentes sem apagar dados.
6. WHEN o operador executar o preflight de frota THEN the system SHALL listar por tenant conectividade, identidade, versão Alembic e prontidão sem revelar credenciais.
7. WHEN uma migração de frota for solicitada THEN the system SHALL exigir seleção explícita de tenants, confirmação operacional e resultado individual, sem alterar bancos não selecionados.

**Independent Test**: Exercitar eventos, falhas de um banco e preflight com tenants em versões diferentes, confirmando isolamento, logs sem segredo e ausência de fallback.

---

## Edge Cases

- IF o slug contiver host externo, barras adicionais, caracteres fora de [a-z0-9-], segmento reservado ou mais de 63 caracteres THEN the system SHALL rejeitar a entrada sem redirecionamento externo.
- IF o cookie estiver ausente, malformado, expirado, revogado ou tiver digest desconhecido THEN the system SHALL responder 401 e apagar o cookie recebido.
- IF duas tentativas de login concorrentes atingirem o limite THEN the system SHALL serializar o contador e impedir que ambas ultrapassem o limite sem bloqueio.
- IF duas mutações concorrentes usarem a mesma versão do workspace THEN the system SHALL aceitar uma e rejeitar a outra com conflito no mesmo tenant.
- IF uma referência do payload apontar para registro ausente no banco selecionado THEN the system SHALL responder erro genérico e reverter a transação.
- IF o contexto RLS estiver ausente em uma transação tenant-owned THEN the system SHALL produzir zero linhas ou erro e nunca operar sem filtro.
- IF dois tenants forem configurados por engano com o mesmo perfil de conexão THEN the system SHALL detectar identidade divergente para pelo menos um deles e impedir sua ativação.
- IF o pool de um tenant falhar THEN the system SHALL invalidar somente esse pool e manter os demais tenants disponíveis.
- IF o pacote offline não contiver wheel Argon2 compatível com CPython 3.11 x64 THEN the system SHALL falhar no gate de empacotamento.
- IF uma migração ou ativação detectar inconsistência THEN the system SHALL abortar antes de habilitar login para o tenant afetado.

---

## Implicit-Requirement Dimensions

| Dimension | Resolution |
| --------- | ---------- |
| Input validation & bounds | Slug, URL, e-mail, senha, cookie, payload e dados de conexão têm formatos e limites explícitos. |
| Failure / partial-failure states | Provisionamento distribuído usa estados e retomada; indisponibilidade de um banco falha fechada sem afetar os demais. |
| Idempotency / retry / duplicate handling | Slug é globalmente único; e-mail é único no tenant; provisionamento e preflight são repetíveis; versionamento controla save. |
| Auth boundaries & rate limits | Sessão central, perfil no banco tenant e dois buckets centrais de throttling são obrigatórios. |
| Concurrency / ordering | Locks protegem throttling, sessão, versão do workspace e transições de provisionamento. |
| Data lifecycle / expiry | Sessões expiram e podem ser revogadas; inativar tenant não apaga seu banco. |
| Observability | Eventos usam correlação e estado por tenant, sem segredos ou dados comerciais. |
| External-dependency failure | Cada PostgreSQL tenant é dependência externa isolada; timeout, identidade, versão e falha sem fallback são definidos. |
| State-transition integrity | Apenas active com banco identificado e schema compatível autentica; transições são idempotentes e auditadas. |

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| MT-01 | Localizar e autenticar no banco correto | Execute | Verified |
| MT-02 | Sessão opaca central | Execute | Verified |
| MT-03 | Roteamento e isolamento de banco | Execute | Verified |
| MT-04 | Autorização por perfil | Execute | Verified |
| MT-05 | Migração e provisionamento distribuído | Execute | Verified |
| MT-06 | Operação segura da frota | Execute | Verified |
| MT-07 | Edge cases e concorrência | Execute | Verified |

**Coverage:** 7 requirement groups, 7 mapped to design/tasks, 0 unmapped.

---

## Success Criteria

- [x] Dois tenants em PostgreSQL distintos e com IDs públicos idênticos não conseguem ler, alterar, excluir ou restaurar dados cruzados por API, serviço, repositório ou conexão forjada.
- [x] Nenhuma rota de negócio aceita operação sem sessão válida e nenhum parâmetro do navegador seleciona tenant, perfil de conexão, usuário ou autorização.
- [x] Uma identidade de banco incompatível, schema incompatível ou banco indisponível falha fechado sem fallback.
- [x] O banco atual mantém contagens, payloads e vínculos e se torna o banco do primeiro tenant sem copiar dados comerciais.
- [x] O plano de controle não contém hash de senha, dados comerciais, DSN nem segredo de conexão em texto puro.
- [x] O pacote offline valida wheels e execução no contrato CPython 3.11 x64/PostgreSQL 11.
- [x] Todos os gates backend, UI, migração, frota, implantação e validadores do skill passam antes de qualquer deploy.
