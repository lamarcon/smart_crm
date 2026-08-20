# Personalização e Administração - Contexto

**Gathered:** 2026-08-20
**Spec:** `.specs/features/admin-customization/spec.md`
**Status:** Ready for implementation

---

## Feature Boundary

A entrega adiciona personalização de campos nos quatro módulos comerciais e uma área local de usuários/permissões. Convites são simulados. Não há autenticação ou envio de e-mail real.

---

## Implementation Decisions

### Campos

- Administradores acessam `Gerenciar campos` a partir da página do módulo.
- Campos padrão podem ser ocultados globalmente no formulário daquele módulo.
- Campos personalizados são esquemas compartilhados pelo módulo e aparecem por padrão em todos os registros.
- Campos adicionais podem ser ocultados por registro e recuperados em `Adicionar campo`.
- Os tipos iniciais são texto curto/longo, número, moeda, data, booleano, e-mail, telefone, URL, seleção única e seleção múltipla.
- Exclusão e renomeação de esquema ficam fora desta entrega.

### Usuários e permissões

- O destino administrativo aparece somente para Administradores.
- `Cargo profissional` e `Perfil de acesso` são propriedades separadas.
- Perfis disponíveis: Administrador, Gestor, Vendedor, Assistente e Faturamento.
- Status disponíveis: Pendente, Ativo, Inativo e Cancelado.
- Convites pendentes não aparecem no seletor de perfil.
- Aceitação é simulada por botão; reenvio atualiza o horário; cancelamento preserva o registro.
- O Administrador não pode desativar o próprio usuário atual.

### Persistência

- Tudo permanece no `localStorage` deste navegador.
- O estado legado recebe esquemas vazios, configurações visíveis e usuários ativos por padrão.

### Agent's Discretion

- Ícones, espaçamento, textos auxiliares e composição visual que sigam o protótipo atual.

### Declined / Undiscussed Gray Areas → Assumptions

- Campos personalizados não serão obrigatórios nesta versão.
- O e-mail de usuários ativos será editável somente no convite, evitando mudança de identidade posterior.
- Convite cancelado com o mesmo e-mail reutiliza o cadastro existente.

---

## Specific References

- O usuário aprovou campos compartilhados por módulo e configuração somente por Administradores.
- O usuário aprovou convite simulado e separação entre cargo profissional e perfil de acesso.

---

## Deferred Ideas

- Envio real de e-mail, token com expiração, criação de senha e autenticação.
- Permissões granulares, trilha de auditoria e grupos de acesso.
- Exclusão/renomeação de esquemas e migração de tipo.
- Tipos de anexo e relacionamento.
