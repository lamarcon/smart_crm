# Personalização e Administração do Smart CRM

## Problem Statement

O protótipo permite editar campos adicionais importados, mas não permite criar campos próprios, controlar campos padrão por módulo nem ocultar um campo adicional em um cadastro. Também não existe uma área para o Administrador convidar funcionários ou separar cargo profissional de perfil de acesso.

## Goals

- [x] Permitir que Administradores gerenciem campos padrão e criem campos personalizados compartilhados por módulo.
- [x] Permitir ocultar e reexibir campos adicionais por cadastro sem apagar o valor.
- [x] Criar uma área administrativa para convites simulados e gestão de cargo, equipe, perfil e status de funcionários.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Envio real de e-mail e criação de senha | O protótipo não possui servidor de autenticação nem serviço de e-mail. |
| Excluir ou renomear esquemas personalizados | Esta entrega cobre criação e visibilidade; alterações destrutivas ficam para uma evolução. |
| Anexos e relacionamentos como tipos personalizados | Exigem armazenamento e seletores específicos. |
| Permissões granulares por ação | Os cinco perfis atuais permanecem como fronteira de acesso. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Escopo de campo personalizado | Compartilhado pelo módulo e visível por padrão em todos os cadastros existentes e novos | Mantém um esquema consistente para Leads, Contatos, Empresas ou Negócios. | y |
| Ocultação de campo adicional | Por cadastro, reversível em `Adicionar campo` | Evita apagar valores e permite layouts diferentes por registro. | y |
| Ocultação de campo padrão | Configuração global do módulo, reversível em `Gerenciar campos` | Campos padrão representam o esquema comum do módulo. | y |
| Administração | Somente o perfil `Administrador` vê e executa as ações | Evita alterações de esquema e acesso por usuários comuns. | y |
| Convite | Simulado localmente com status `Pendente` | O ambiente de teste não envia e-mail real. | y |
| Cargo e acesso | `Cargo profissional` separado de `Perfil de acesso` | Um cargo organizacional não deve conceder permissão técnica. | y |
| E-mail duplicado | Comparação sem diferença de maiúsculas e minúsculas | Impede dois usuários para o mesmo endereço. | y |

**Open questions:** none - all resolved or logged above.

---

## User Stories

### P1: Gerenciar campos do módulo ⭐ MVP

**User Story**: Como Administrador, quero criar campos personalizados e controlar campos padrão para adaptar cada módulo à operação.

**Why P1**: Esta é a capacidade aprovada para adaptar o CRM sem alterar código.

**Acceptance Criteria**:

1. WHILE o usuário atual tiver perfil `Administrador`, o sistema SHALL exibir `Gerenciar campos` em Leads, Contatos, Empresas e Negócios.
2. WHILE o usuário atual não tiver perfil `Administrador`, o sistema SHALL ocultar `Gerenciar campos` e rejeitar sua abertura por ação direta.
3. WHEN o Administrador abrir `Gerenciar campos` THEN o sistema SHALL listar todos os campos padrão do módulo com seu estado visível ou oculto.
4. WHEN o Administrador ocultar o campo padrão `Contato` em Negócios e salvar THEN o sistema SHALL removê-lo da aba `Informações` de todos os Negócios sem alterar o valor persistido.
5. WHEN o Administrador reexibir o campo padrão `Contato` em Negócios THEN o sistema SHALL restaurar o controle com o valor persistido.
6. WHEN o Administrador abrir o seletor de tipo THEN o sistema SHALL oferecer exatamente `Texto curto`, `Texto longo`, `Número`, `Moeda`, `Data`, `Sim/Não`, `E-mail`, `Telefone`, `Link`, `Seleção única` e `Seleção múltipla`.
7. WHEN o Administrador criar `Número do contrato` em Negócios como `Texto curto` THEN o sistema SHALL disponibilizar o campo em todos os Negócios existentes e novos.
8. IF já existir no módulo um campo personalizado com o mesmo nome sem diferenciar maiúsculas de minúsculas THEN o sistema SHALL rejeitar a criação e manter um único esquema.
9. IF o tipo for `Seleção única` ou `Seleção múltipla` e não houver opção não vazia THEN o sistema SHALL rejeitar a criação com a mensagem `Informe ao menos uma opção.`.

**Independent Test**: Ocultar e reexibir `Contato`, criar `Número do contrato` e verificar o mesmo esquema em dois Negócios.

---

### P1: Preencher e localizar campos personalizados ⭐ MVP

**User Story**: Como usuário comercial, quero preencher, ocultar e localizar campos personalizados para trabalhar com um cadastro adequado ao meu contexto.

**Why P1**: Um esquema configurável só gera valor se funcionar no formulário, pesquisa e filtros.

**Acceptance Criteria**:

1. WHEN um campo personalizado for exibido THEN o sistema SHALL usar o controle correspondente ao tipo configurado.
2. WHEN o usuário salvar valores de texto, número, moeda, data, Sim/Não, seleção única ou seleção múltipla THEN o sistema SHALL preservar seus tipos e valores após reabrir o cadastro.
3. WHEN o usuário ocultar um campo adicional com valor THEN o sistema SHALL remover o controle do card sem apagar o valor persistido.
4. WHEN o usuário reexibir um campo adicional oculto THEN o sistema SHALL restaurar o controle com o valor anterior.
5. WHEN uma busca corresponder ao valor de um campo personalizado THEN o sistema SHALL manter somente os registros correspondentes.
6. WHEN o painel de filtros for aberto THEN o sistema SHALL oferecer exatamente `Contém` e `É exatamente` para Texto curto, Texto longo, E-mail, Telefone e Link; `Valor exato`, `Maior que`, `Menor que` e `Entre` para Número e Moeda; `Qualquer data`, `Data exata`, `Antes de`, `Depois de` e `Entre` para Data; e `É um de` para Sim/Não, Seleção única e Seleção múltipla.

**Independent Test**: Preencher campos tipados, ocultar um deles, reexibir e pesquisar/filtrar pelo valor salvo.

---

### P1: Administrar funcionários e convites ⭐ MVP

**User Story**: Como Administrador, quero convidar e editar funcionários para organizar equipe, cargo e acesso no CRM.

**Why P1**: O seletor demonstrativo atual não oferece gestão de usuários.

**Acceptance Criteria**:

1. WHILE o usuário atual tiver perfil `Administrador`, o sistema SHALL exibir o destino `Usuários e permissões` na navegação.
2. WHILE o usuário atual não tiver perfil `Administrador`, o sistema SHALL ocultar `Usuários e permissões` e redirecionar tentativa direta para `Visão geral`.
3. WHEN o Administrador convidar `Juliana Lima` com e-mail `juliana@teste.invalid`, cargo `Consultora comercial`, equipe `Vendas CMS` e perfil `Vendedor` THEN o sistema SHALL criar um usuário com esses valores e status `Pendente`.
4. WHILE um convite estiver `Pendente`, o sistema SHALL omitir o usuário do seletor `Perfil demonstrativo`.
5. IF o e-mail informado já pertencer a qualquer usuário sem diferenciar maiúsculas de minúsculas THEN o sistema SHALL rejeitar o convite sem criar duplicata.
6. WHEN o Administrador editar cargo, equipe ou perfil de acesso THEN o sistema SHALL persistir cada valor separadamente.
7. WHEN o Administrador simular a aceitação de um convite THEN o sistema SHALL alterar o status para `Ativo` e incluir o usuário no seletor `Perfil demonstrativo`.
8. WHEN o Administrador reenviar um convite pendente THEN o sistema SHALL atualizar `invitedAt` e manter o status `Pendente`.
9. WHEN o Administrador cancelar um convite pendente THEN o sistema SHALL alterar o status para `Cancelado` e mantê-lo fora do seletor de perfis.
10. WHEN o Administrador desativar um usuário ativo diferente do usuário atual THEN o sistema SHALL alterar o status para `Inativo` e removê-lo do seletor de perfis.
11. IF o Administrador tentar desativar o próprio usuário atual THEN o sistema SHALL rejeitar a ação e manter seu status `Ativo`.

**Independent Test**: Convidar Juliana, editar cargo e acesso, reenviar, aceitar e desativar; repetir com e-mail duplicado e tentativa de auto-desativação.

---

## Edge Cases

- IF o nome do campo personalizado estiver vazio THEN o sistema SHALL rejeitar a criação sem alterar o esquema.
- WHEN opções repetidas forem informadas THEN o sistema SHALL preservar uma ocorrência de cada opção sem diferenciar maiúsculas de minúsculas.
- IF um valor de Link não for uma URL válida THEN o sistema SHALL impedir o salvamento pelo controle nativo.
- WHEN o estado legado não tiver configurações de campos ou status de usuários THEN o sistema SHALL aplicar padrões sem perder registros.
- IF um convite cancelado receber novo convite com o mesmo e-mail THEN o sistema SHALL reutilizar o cadastro cancelado com os novos dados e status `Pendente`.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| ADM-01 | P1: Gerenciar campos | Execute | Complete |
| ADM-02 | P1: Campos personalizados | Execute | Complete |
| ADM-03 | P1: Administrar funcionários | Execute | Complete |
| ADM-04 | Edge cases | Execute | Complete |

**Coverage:** 4 total, 4 mapped to the execution plan, 0 unmapped.

---

## Success Criteria

- [x] Administradores criam os 11 tipos de campo e ocultam campos padrão por módulo.
- [x] Usuários ocultam e reexibem campos adicionais sem perda de valor.
- [x] Campos personalizados participam de busca e filtros com tipos compatíveis.
- [x] Convites simulados e mudanças de funcionário respeitam status e perfil administrativo.
- [ ] Todos os critérios têm evidência executável e validação independente PASS.
