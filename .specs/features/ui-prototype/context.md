# Protótipo Local do Smart CRM — Contexto

**Coletado:** 2026-08-17  
**Origem:** solicitação de uma versão demonstrativa sem banco de dados  
**Status:** aprovado para implementação pelo pedido direto do usuário

## Limite da entrega

Esta entrega é um protótipo navegável para validar layout e fluxos principais. Ela não é o MVP de produção e não substitui os requisitos de persistência, segurança, integração WordPress ou migração do Bitrix24 documentados em `.specs/features/crm-mvp/spec.md`.

## Decisões

- O protótipo será executado localmente por Docker Compose.
- Não haverá PostgreSQL nem outro serviço externo.
- Os dados iniciais serão fictícios e ficarão no navegador por `localStorage`.
- O usuário poderá restaurar os dados de demonstração a qualquer momento.
- A interface será em português do Brasil e baseada em listas.
- O perfil ativo poderá ser alternado para demonstrar visibilidade de Administrador, Gestor, Vendedor e Assistente.
- Serão demonstrados Dashboard, Leads, Contatos, Empresas, Negócios, orçamentos e notificações.
- As Pipelines fixas aprovadas serão representadas; as etapas ornamentais chamadas “Nome” não serão incluídas.
- Ações de criação, edição, exclusão, conversão, mudança de etapa e orçamento serão simulações locais.
- O anexo PDF do orçamento será opcional e somente o nome/metadado do arquivo será mantido na demonstração.

## Fora deste protótipo

- Autenticação e autorização reais no servidor.
- Banco de dados, persistência multiusuário e auditoria durável.
- Integração real com WordPress.
- Migração real do Bitrix24.
- Upload e armazenamento real de arquivos.
- Envio de notificações externas.
- Garantias de concorrência, segurança ou disponibilidade de produção.

## Estratégia de teste adotada

- Autoteste em Python para rotas e arquivos essenciais do servidor.
- Validação sintática do JavaScript.
- Validação da configuração e construção do container.
- Verificação visual e funcional no navegador sobre o container em execução.
