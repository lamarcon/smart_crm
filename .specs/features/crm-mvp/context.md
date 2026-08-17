# Smart CRM MVP Context

**Gathered:** 2026-08-17
**Spec:** `.specs/features/crm-mvp/spec.md`
**Status:** Ready for review

---

## Feature Boundary

O MVP substitui o uso essencial do Bitrix24 com Leads, Contatos, Empresas, Negócios, orçamentos, Pipelines fixas, automações predefinidas, notificações internas, captação pelo WordPress e migração dos dados acessíveis. A interface inicial usa listas. Tarefas e Projetos ficam adiados.

---

## Implementation Decisions

### Stack e substituição

- O backend usará Python.
- A persistência usará PostgreSQL.
- O Smart CRM substituirá integralmente o Bitrix24 Cloud Professional.
- O WordPress enviará Leads diretamente ao Smart CRM.
- A migração abrangerá tudo que for tecnicamente acessível nos módulos do MVP.

### Interface e cadastros

- O MVP será funcional, não apenas visual.
- Leads, Contatos, Empresas e Negócios terão cadastro, consulta, edição, exclusão lógica e vínculos.
- A interface inicial será baseada em listas com busca, filtros, ordenação e paginação.
- O Administrador poderá criar, editar, ordenar e desativar campos personalizados.
- As definições e os valores dos campos personalizados do Bitrix24 serão importados quando acessíveis.

### Perfis e acesso

- Administradores acessam todos os registros e configurações.
- Gestores acessam e redistribuem registros da equipe.
- Vendedores acessam apenas Leads e Negócios em que sejam responsáveis ou Assistentes.
- O cargo Assistente recebe acesso de visualização e edição quando adicionado ao Lead ou Negócio.
- Remover o Assistente revoga o acesso ao registro.

### Pipeline de Leads

- A única etapa ativa é Em contato.
- Lead descartado e Lead convertido são estados de encerramento.
- A etapa ornamental Nome não será reproduzida.
- O descarte exige um motivo e aceita uma observação opcional.
- Gestores e Administradores podem recuperar e reatribuir Leads descartados.
- A conversão procura Contato e Empresa existentes, cria os ausentes e sempre cria um novo Negócio em Em Contato.
- A conversão preserva responsável, Assistentes, vínculos e histórico.

### Pipeline de Negócios

- As etapas funcionais são Em Contato, Orçamento Proposta Preço, Orçamentos enviados, Negociação Revisão, Pedido aprovado Consultar, Faturando, Ganho, Orçamento Não Aprovado e Analisar falha.
- As duas etapas ornamentais Nome não serão reproduzidas.
- Ganho é sucesso.
- Orçamento Não Aprovado e Analisar falha são encerramentos sem sucesso.
- As etapas serão fixas no MVP.

### Automações predefinidas

- Alterar etapa quando as condições predefinidas forem atendidas.
- Retornar para Em Contato quando os campos obrigatórios não estiverem preenchidos.
- Retornar para Negociação Revisão quando o orçamento não estiver realizado.
- Alterar a pessoa responsável para o grupo Faturamento ao entrar em Faturando.
- Registrar cada execução no histórico do Negócio.
- Automações de criação de Tarefas e fluxos genéricos ficam adiadas.

### Orçamentos

- O Negócio terá uma área própria de orçamentos.
- O orçamento será composto por dados gerais, itens, valores, desconto, total, validade, observações e estado.
- O campo para anexar PDF será opcional.
- O PDF não bloqueará salvamento, envio, aprovação ou automações.
- A geração automática de PDF fica fora do MVP.

### Captação pelo WordPress

- Cada envio comercial legítimo cria um novo Lead, mesmo quando e-mail, telefone, Contato ou Empresa já existirem.
- Somente a repetição técnica do mesmo identificador de submissão será idempotente.
- O mapeamento atual inclui nome, sobrenome, cidade, e-mail, telefone, segmento e mensagem.
- Consentimento, título, hostname, referenciador e IP serão preservados quando enviados e quando forem permitidos pelas regras de dados do projeto.
- O Bitrix24 deixa de participar do fluxo.

### Notificações

- O MVP terá somente notificações internas.
- Responsáveis e Assistentes serão notificados sobre atribuições e mudanças automatizadas relevantes.
- A central distinguirá notificações lidas e não lidas.
- E-mail e WhatsApp ficam adiados.

### Migração

- O Bitrix24 atual é Cloud, plano Professional, com acesso administrativo.
- Os volumes aproximados informados são 16.000 Negócios, 3.043 Leads, 16.613 Contatos e 8.605 Empresas.
- A migração preservará identificadores de origem, campos, vínculos, responsáveis, Assistentes, históricos, atividades e arquivos acessíveis.
- Cada execução produzirá reconciliação e relatório de exceções.
- A migração será reexecutável sem duplicar registros.

### Agent's Discretion

- Organização visual das listas e formulários dentro do escopo aprovado.
- Textos de validação e estados vazios em português do Brasil.
- Detalhes técnicos de autenticação, auditoria, concorrência, retentativas e processamento assíncrono, desde que cumpram a especificação.

### Declined / Undiscussed Gray Areas → Assumptions

- Múltiplos orçamentos por Negócio, moeda BRL e estados mínimos do orçamento.
- Limite de 20 MB por PDF e possibilidade de vários anexos.
- Contatos e Empresas vinculados ficam somente para leitura quando o acesso vier exclusivamente do papel de Assistente.
- Apenas usuários ativos do grupo Faturamento participam da distribuição aleatória.
- Histórico e registros excluídos não expiram automaticamente no MVP.
- Uma gravação desatualizada é bloqueada em vez de sobrescrever a versão atual.
- A integração WordPress mantém falhas persistentes disponíveis para reprocessamento administrativo.

---

## Specific References

- Pipeline de Negócios observada no Bitrix24 com o nome Vendas CMS.
- Pipeline de Leads observada com Em contato, Lead descartado e Lead convertido.
- Automação de notificação imediata destinada à pessoa responsável.
- Automação de retorno para Em Contato quando o indicador de campos obrigatórios estiver vazio ou marcado como Não.
- Automação de retorno para Negociação Revisão quando o indicador de orçamento realizado estiver vazio ou marcado como Não.
- Automação de alteração de responsável para o grupo Faturamento com seleção aleatória.
- Integração WordPress atual com mapeamento de campos para o Bitrix24.

---

## Deferred Ideas

- Tarefas e Projetos.
- Editor de Pipelines.
- Construtor genérico de automações.
- Kanban.
- Notificações por e-mail e WhatsApp.
- Geração automática de PDF.
- Recursos avançados de Negócios existentes no Bitrix24.
