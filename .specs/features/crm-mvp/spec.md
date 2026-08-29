# Smart CRM MVP Specification

## Problem Statement

O cliente depende do Bitrix24 Cloud Professional para Leads, Contatos, Empresas, Negócios, Pipelines, automações e captação pelo WordPress. O Smart CRM substituirá esse uso com um MVP funcional em Python e PostgreSQL, mantendo os dados e os fluxos essenciais sem reproduzir a complexidade completa do Bitrix24.

## Delivery Baseline

A aplicação local em `http://localhost:8080` está concluída e validada. Ela não é um rascunho pendente: entrega a interface navegável, os fluxos comerciais demonstrativos, a API FastAPI e a persistência PostgreSQL do workspace. As validações independentes estão registradas nas features `ui-prototype`, `ui-crm-workspace`, `postgres-crm-persistence` e nas features incrementais da interface.

Os requisitos abaixo descrevem a evolução dessa base para uso produtivo com usuários e dados reais. Um requisito marcado como `Pending` não significa que o layout ou o fluxo local esteja ausente. Significa que a garantia produtiva correspondente ainda precisa de implementação ou evidência própria dentro desta feature guarda-chuva.

| Área | Base local validada | Garantia produtiva ainda necessária |
| --- | --- | --- |
| Interface e cadastros | Layout, CRUD, vínculos, filtros, Lista/Kanban, dashboard e campos personalizados funcionam localmente. | APIs granulares, paginação por banco, auditoria por campo e autorização em toda consulta/mutação. |
| Identidade e acesso | Perfis de Administrador, Gestor, Vendedor e Assistente são simulados na interface. | Login real, sessões seguras, credenciais e autorização obrigatória no servidor. |
| Leads e Negócios | Pipelines, conversão, transições protegidas, desfazer e Faturamento funcionam no workspace local. | Regras transacionais no backend, idempotência das automações e trilha de auditoria produtiva. |
| Orçamentos e notificações | Orçamentos, metadado de PDF e notificações internas são persistidos. | Itens/estados completos, armazenamento e download autorizado de PDFs e eventos de notificação no servidor. |
| WordPress | Não integra o fluxo local atual. | Endpoint autenticado, idempotência por submissão, fila de falhas e reprocessamento administrativo. |
| Bitrix24 | Importação CSV representativa preserva IDs e campos adicionais. | Inventário e migração integral de dados acessíveis, históricos, atividades, arquivos, reconciliação e relatório de exceções. |
| Operação | Compose local, health checks, migrações e recuperação foram validados. | UAT com dados representativos, segurança operacional, backup/restore de corte, observabilidade e plano de desativação do Bitrix24. |

## Goals

- [ ] Permitir o cadastro, consulta, edição, exclusão lógica e vinculação de Leads, Contatos, Empresas e Negócios.
- [ ] Operar as Pipelines fixas de Leads e Negócios com as automações essenciais do cliente.
- [ ] Captar cada nova oportunidade enviada pelo WordPress sem depender do Bitrix24.
- [ ] Migrar e reconciliar todos os dados tecnicamente acessíveis dos módulos incluídos no MVP.
- [ ] Aplicar permissões por perfil, responsabilidade e participação como Assistente.
- [ ] Entregar uma interface funcional baseada em listas para validação rápida do produto.

## Out of Scope

| Feature | Reason |
| --- | --- |
| Tarefas e Projetos, incluindo sua interface e migração | Módulo adiado para reduzir o tempo até o MVP. |
| Editor de Pipelines | O MVP usará as Pipelines fixas do cliente. |
| Construtor genérico de automações | O MVP implementará somente regras predefinidas. |
| Kanban | A primeira interface usará listas. |
| Notificações por e-mail ou WhatsApp | O MVP terá apenas notificações internas. |
| Geração automática de PDF de orçamento | O orçamento terá apenas anexos PDF opcionais. |
| Exclusão física de registros | O MVP preservará histórico e permitirá recuperação conforme as permissões. |
| Migração de dados que o Bitrix24 Cloud não disponibilize | Todo item indisponível será documentado no relatório de exceções. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Idioma da interface | Português do Brasil | É o idioma usado pelo cliente e nas configurações apresentadas. | n |
| Moeda dos orçamentos | Real brasileiro (BRL) | Os valores atuais são apresentados em reais. | n |
| Quantidade de orçamentos por Negócio | Vários orçamentos por Negócio | Permite revisões e novas propostas sem apagar o histórico. | n |
| Estrutura mínima do orçamento | Número, data, cliente, empresa, itens, quantidade, valor unitário, desconto, total, validade, observações e estado | Mantém o orçamento funcional sem reproduzir recursos avançados do Bitrix24. | n |
| Estados do orçamento | Rascunho, Enviado, Aprovado e Rejeitado | Representa o ciclo mínimo necessário para a Pipeline. | n |
| Anexos PDF do orçamento | Opcionais, vários arquivos, máximo de 20 MB por arquivo | Atende ao pedido de anexação sem bloquear o fluxo comercial. | n |
| Acesso do Assistente aos vínculos | Contatos e Empresas vinculados ficam disponíveis somente para leitura | O Assistente precisa de contexto sem receber permissão indireta para alterar cadastros mestres. | n |
| Escopo do Gestor | Todos os registros dos usuários da sua equipe | Permite acompanhamento e redistribuição sem liberar toda a organização. | y |
| Distribuição para Faturamento | Selecionar aleatoriamente apenas usuários ativos do grupo Faturamento | Evita atribuição a contas inativas ou desligadas. | n |
| Retenção de histórico e registros excluídos | Sem expiração automática no MVP | A substituição do Bitrix24 exige preservação do histórico operacional. | n |
| Conflito de edição simultânea | Bloquear a gravação desatualizada e pedir recarregamento | Evita sobrescrita silenciosa de alterações recentes. | n |
| Falha persistente na integração WordPress | Manter o envio pendente e permitir reprocessamento administrativo | Evita perda silenciosa de oportunidades. | n |
| Desempenho das listas | Responder em até 2 segundos para consultas paginadas nos volumes atuais | Mantém a interface utilizável com a base informada pelo cliente. | n |

**Open questions:** none - all unresolved choices are logged as assumptions above.

---

## User Stories

### P1: Acesso e visibilidade por responsabilidade ⭐ MVP

**User Story**: Como usuário do CRM, quero acessar somente os registros autorizados para cumprir minha função sem expor dados de outros vendedores.

**Why P1**: O CRM contém dados comerciais e pessoais que precisam de controle por perfil e por registro.

**Acceptance Criteria**:

1. [AUTH-01] WHEN um usuário ativo informar credenciais válidas THEN o Smart CRM SHALL iniciar uma sessão autenticada com o perfil atribuído.
2. [AUTH-02] IF um usuário estiver inativo ou informar credenciais inválidas THEN o Smart CRM SHALL negar o acesso sem revelar qual credencial falhou.
3. [AUTH-03] WHILE um usuário tiver o perfil Administrador o Smart CRM SHALL permitir acesso a todos os registros e configurações do MVP.
4. [AUTH-04] WHILE um usuário tiver o perfil Gestor o Smart CRM SHALL permitir acesso aos Leads e Negócios dos usuários da sua equipe.
5. [AUTH-05] WHILE um usuário tiver o perfil Vendedor o Smart CRM SHALL exibir somente Leads e Negócios em que seja responsável ou Assistente.
6. [AUTH-06] WHEN um usuário com perfil Assistente for adicionado a um Lead ou Negócio THEN o Smart CRM SHALL permitir que ele visualize e edite esse registro.
7. [AUTH-07] WHEN um Assistente for removido de um Lead ou Negócio THEN o Smart CRM SHALL revogar seu acesso ao registro na próxima requisição.
8. [AUTH-08] WHEN um Administrador criar ou editar um usuário THEN o Smart CRM SHALL permitir atribuir perfil, equipe e estado ativo ou inativo.

**Independent Test**: Criar usuários dos quatro perfis e verificar a matriz de acesso usando registros próprios, de equipe, de terceiros e com Assistente atribuído.

---

### P1: Cadastros centrais e campos personalizados ⭐ MVP

**User Story**: Como usuário autorizado, quero administrar os cadastros centrais e seus vínculos para manter a operação comercial completa.

**Why P1**: Leads, Contatos, Empresas e Negócios são a base funcional que substituirá o CRM atual.

**Acceptance Criteria**:

1. [CORE-01] WHEN um usuário autorizado enviar dados válidos de um Lead, Contato, Empresa ou Negócio THEN o Smart CRM SHALL criar o registro e retornar seu identificador.
2. [CORE-02] WHEN um usuário autorizado alterar dados válidos THEN o Smart CRM SHALL salvar a nova versão e registrar autor, data e campos alterados.
3. [CORE-03] WHEN um usuário autorizado solicitar a exclusão de um registro THEN o Smart CRM SHALL ocultá-lo das listas ativas sem remover seu histórico ou vínculos.
4. [CORE-04] WHEN um usuário autorizado recuperar um registro excluído THEN o Smart CRM SHALL restaurá-lo com o histórico e os vínculos anteriores.
5. [CORE-05] WHEN um usuário autorizado editar vínculos THEN o Smart CRM SHALL permitir relacionar Contatos com Empresas e Negócios com Contatos e Empresas.
6. [CORE-06] WHEN um Administrador configurar um campo personalizado THEN o Smart CRM SHALL permitir definir módulo, nome, tipo, obrigatoriedade, ordem e estado ativo.
7. [CORE-07] IF um valor não atender ao tipo ou à obrigatoriedade de um campo THEN o Smart CRM SHALL rejeitar a alteração e identificar o campo inválido.
8. [CORE-08] WHEN um usuário acessar uma lista THEN o Smart CRM SHALL oferecer busca, filtros, ordenação e paginação respeitando suas permissões.
9. [CORE-09] IF uma alteração for baseada em uma versão desatualizada THEN o Smart CRM SHALL bloquear a gravação e informar que o registro precisa ser recarregado.
10. [CORE-10] IF qualquer parte de uma operação de cadastro falhar THEN o Smart CRM SHALL desfazer toda a operação sem deixar dados parciais.

**Independent Test**: Criar os quatro tipos de cadastro, configurar campos personalizados, vincular os registros, editar, excluir, recuperar e provocar erros de validação e concorrência.

---

### P1: Pipeline e ciclo de vida dos Leads ⭐ MVP

**User Story**: Como Vendedor, quero trabalhar cada Lead até descartá-lo ou convertê-lo para transformar solicitações em oportunidades comerciais.

**Why P1**: O formulário WordPress e a conversão de Leads iniciam o fluxo comercial do cliente.

**Acceptance Criteria**:

1. [LEAD-01] The Smart CRM SHALL disponibilizar para Leads os estados fixos Em contato, Lead descartado e Lead convertido.
2. [LEAD-02] IF um usuário tentar descartar um Lead sem selecionar um motivo THEN o Smart CRM SHALL bloquear a transição e solicitar o motivo.
3. [LEAD-03] WHEN um Lead for descartado THEN o Smart CRM SHALL preservar motivo, observação opcional, responsável e histórico.
4. [LEAD-04] WHILE um Lead estiver descartado somente Gestores e Administradores SHALL poder recuperá-lo e reatribuí-lo.
5. [LEAD-05] WHEN um usuário iniciar a conversão de um Lead THEN o Smart CRM SHALL procurar Contatos e Empresas existentes pelos dados disponíveis.
6. [LEAD-06] WHEN o usuário confirmar a conversão THEN o Smart CRM SHALL vincular os registros existentes e criar os Contatos ou Empresas ausentes.
7. [LEAD-07] WHEN a conversão for concluída THEN o Smart CRM SHALL criar um Negócio em Em Contato preservando responsável e Assistentes.
8. [LEAD-08] WHEN a conversão for concluída THEN o Smart CRM SHALL manter o Lead no estado Lead convertido com vínculos e histórico consultáveis.

**Independent Test**: Cadastrar um Lead, descartá-lo com motivo, recuperá-lo como Gestor e convertê-lo reutilizando uma Empresa e criando um Contato e um Negócio.

---

### P1: Pipeline e automações dos Negócios ⭐ MVP

**User Story**: Como Vendedor, quero movimentar Negócios por etapas com validações e automações predefinidas para seguir o processo atual do cliente.

**Why P1**: A Pipeline de vendas e suas regras concentram o processo comercial que hoje funciona no Bitrix24.

**Acceptance Criteria**:

1. [PIPE-01] The Smart CRM SHALL disponibilizar as etapas Em Contato, Orçamento Proposta Preço, Orçamentos enviados, Negociação Revisão, Pedido aprovado Consultar, Faturando, Ganho, Orçamento Não Aprovado e Analisar falha.
2. [PIPE-02] WHEN um usuário autorizado alterar a etapa pela lista ou pelo formulário THEN o Smart CRM SHALL aplicar a transição e executar as regras predefinidas da etapa de destino.
3. [PIPE-03] IF os campos obrigatórios estiverem vazios ou marcados como não preenchidos THEN o Smart CRM SHALL mover o Negócio para Em Contato.
4. [PIPE-04] IF o orçamento estiver vazio ou marcado como não realizado THEN o Smart CRM SHALL mover o Negócio para Negociação Revisão.
5. [PIPE-05] WHEN um Negócio entrar em Faturando THEN o Smart CRM SHALL atribuir a responsabilidade a um usuário ativo do grupo Faturamento selecionado aleatoriamente.
6. [PIPE-06] WHEN uma automação alterar etapa, responsável ou campo THEN o Smart CRM SHALL registrar regra executada, resultado e data no histórico do Negócio.
7. [PIPE-07] IF a mesma transição for processada novamente com o mesmo identificador de execução THEN o Smart CRM SHALL manter um único efeito para cada automação.

**Independent Test**: Movimentar um Negócio por todas as etapas, testar os dois retornos condicionais e verificar a distribuição para Faturamento e o histórico das automações.

---

### P1: Orçamentos vinculados ao Negócio ⭐ MVP

**User Story**: Como Vendedor, quero registrar orçamentos e anexar PDFs para acompanhar as propostas feitas em cada Negócio.

**Why P1**: A existência do orçamento controla etapas e automações do processo comercial.

**Acceptance Criteria**:

1. [QUOTE-01] WHEN um usuário autorizado cadastrar um orçamento válido THEN o Smart CRM SHALL vinculá-lo a um único Negócio e calcular seu valor total.
2. [QUOTE-02] WHEN quantidade, valor unitário ou desconto de um item mudar THEN o Smart CRM SHALL recalcular subtotal e total antes de salvar.
3. [QUOTE-03] WHEN um usuário alterar o estado do orçamento THEN o Smart CRM SHALL registrar a mudança no histórico do Negócio.
4. [QUOTE-04] WHERE um orçamento possuir anexos o Smart CRM SHALL aceitar somente arquivos PDF de até 20 MB e permitir download conforme as permissões do Negócio.
5. [QUOTE-05] WHEN um orçamento for aprovado THEN o Smart CRM SHALL marcar o indicador de orçamento realizado para uso pelas automações da Pipeline.

**Independent Test**: Criar dois orçamentos no mesmo Negócio, calcular itens e descontos, anexar PDF opcional e aprovar um orçamento.

---

### P1: Captação de Leads pelo WordPress ⭐ MVP

**User Story**: Como equipe comercial, quero receber cada solicitação legítima do formulário WordPress como um novo Lead sem depender do Bitrix24.

**Why P1**: O WordPress é a origem principal de captação e precisa continuar funcionando após a substituição do Bitrix24.

**Acceptance Criteria**:

1. [FORM-01] WHEN o WordPress enviar uma submissão autenticada com identificador inédito THEN o Smart CRM SHALL criar um novo Lead em Em contato.
2. [FORM-02] WHEN submissões diferentes vierem do mesmo e-mail, telefone, Contato ou Empresa THEN o Smart CRM SHALL criar um Lead para cada identificador de submissão.
3. [FORM-03] WHEN o WordPress repetir o mesmo identificador de submissão THEN o Smart CRM SHALL retornar o Lead criado anteriormente sem criar outro registro.
4. [FORM-04] WHEN uma submissão for aceita THEN o Smart CRM SHALL armazenar nome, sobrenome, cidade, e-mail, telefone, segmento, mensagem, consentimento, origem e data de recebimento quando esses valores forem enviados.
5. [FORM-05] IF a autenticação da integração for inválida THEN o Smart CRM SHALL rejeitar a submissão sem criar dados.
6. [FORM-06] IF o processamento da submissão falhar THEN o Smart CRM SHALL preservar o identificador para reprocessamento sem criar dados parciais.

**Independent Test**: Enviar duas solicitações distintas da mesma pessoa, repetir tecnicamente uma delas e provocar falhas de autenticação e processamento.

---

### P1: Notificações internas ⭐ MVP

**User Story**: Como responsável ou Assistente, quero receber notificações dentro do CRM para acompanhar atribuições e mudanças importantes.

**Why P1**: As notificações substituem parte das automações operacionais usadas no Bitrix24.

**Acceptance Criteria**:

1. [NOTIF-01] WHEN um usuário for atribuído como responsável ou Assistente THEN o Smart CRM SHALL criar uma notificação interna para esse usuário.
2. [NOTIF-02] WHEN uma automação alterar responsável ou etapa THEN o Smart CRM SHALL notificar o novo responsável e os Assistentes que mantiverem acesso.
3. [NOTIF-03] WHILE uma notificação estiver não lida o Smart CRM SHALL exibi-la na central e contabilizá-la no indicador de pendências.
4. [NOTIF-04] WHEN um usuário marcar uma notificação como lida THEN o Smart CRM SHALL removê-la da contagem sem apagar seu conteúdo.

**Independent Test**: Atribuir responsável e Assistente, executar uma mudança automatizada e verificar criação, leitura e contagem das notificações.

---

### P1: Migração e reconciliação do Bitrix24 ⭐ MVP

**User Story**: Como Administrador, quero migrar os dados acessíveis do Bitrix24 Cloud para substituir o sistema sem perder o contexto comercial.

**Why P1**: A base atual possui aproximadamente 16.000 Negócios, 3.043 Leads, 16.613 Contatos e 8.605 Empresas.

**Acceptance Criteria**:

1. [MIG-01] WHEN a migração importar um registro do Bitrix24 THEN o Smart CRM SHALL preservar o identificador de origem para rastreabilidade e reexecução.
2. [MIG-02] WHEN campos personalizados acessíveis forem inventariados THEN o Smart CRM SHALL importar suas definições e valores nos módulos incluídos no MVP.
3. [MIG-03] WHEN vínculos acessíveis forem importados THEN o Smart CRM SHALL preservar as relações entre Leads, Contatos, Empresas, Negócios, responsáveis, Assistentes, orçamentos e arquivos.
4. [MIG-04] WHEN históricos e atividades acessíveis forem importados THEN o Smart CRM SHALL associá-los ao registro de destino correspondente.
5. [MIG-05] WHEN a migração for reexecutada THEN o Smart CRM SHALL atualizar o registro identificado sem criar uma cópia adicional.
6. [MIG-06] IF um campo, tipo, arquivo ou relação não puder ser importado THEN o Smart CRM SHALL registrar a origem, o motivo e o registro afetado no relatório de exceções.
7. [MIG-07] WHEN uma execução terminar THEN o Smart CRM SHALL produzir contagens por entidade para lidos, criados, atualizados, ignorados e falhos.

**Independent Test**: Executar duas vezes uma amostra representativa com campos personalizados, vínculos, históricos e um dado incompatível, comparando os relatórios e a ausência de duplicação.

---

## Edge Cases

- Um Vendedor não pode descobrir registros de terceiros por busca, filtro, URL direta ou vínculo indireto.
- A remoção de um Assistente revoga o acesso sem apagar as alterações feitas enquanto ele estava autorizado.
- Uma nova solicitação legítima da mesma pessoa cria outro Lead; somente o mesmo identificador técnico é idempotente.
- A conversão reutiliza cadastros existentes quando o usuário os confirmar, mas sempre cria um novo Negócio.
- Uma falha durante conversão, automação ou migração não deixa vínculos parciais.
- Campos personalizados desativados permanecem no histórico e deixam de aceitar novos valores.
- PDFs inválidos ou acima do limite são rejeitados sem afetar o orçamento já salvo.
- Pipelines não contêm as etapas ornamentais chamadas Nome existentes no Bitrix24.
- Automações de Tarefas e fluxos genéricos do Bitrix24 não fazem parte deste MVP.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| AUTH-01 | P1: Acesso e visibilidade | Design | Pending |
| AUTH-02 | P1: Acesso e visibilidade | Design | Pending |
| AUTH-03 | P1: Acesso e visibilidade | Design | Pending |
| AUTH-04 | P1: Acesso e visibilidade | Design | Pending |
| AUTH-05 | P1: Acesso e visibilidade | Design | Pending |
| AUTH-06 | P1: Acesso e visibilidade | Design | Pending |
| AUTH-07 | P1: Acesso e visibilidade | Design | Pending |
| AUTH-08 | P1: Acesso e visibilidade | Design | Pending |
| CORE-01 | P1: Cadastros centrais | Design | Pending |
| CORE-02 | P1: Cadastros centrais | Design | Pending |
| CORE-03 | P1: Cadastros centrais | Design | Pending |
| CORE-04 | P1: Cadastros centrais | Design | Pending |
| CORE-05 | P1: Cadastros centrais | Design | Pending |
| CORE-06 | P1: Cadastros centrais | Design | Pending |
| CORE-07 | P1: Cadastros centrais | Design | Pending |
| CORE-08 | P1: Cadastros centrais | Design | Pending |
| CORE-09 | P1: Cadastros centrais | Design | Pending |
| CORE-10 | P1: Cadastros centrais | Design | Pending |
| LEAD-01 | P1: Pipeline de Leads | Design | Pending |
| LEAD-02 | P1: Pipeline de Leads | Design | Pending |
| LEAD-03 | P1: Pipeline de Leads | Design | Pending |
| LEAD-04 | P1: Pipeline de Leads | Design | Pending |
| LEAD-05 | P1: Pipeline de Leads | Design | Pending |
| LEAD-06 | P1: Pipeline de Leads | Design | Pending |
| LEAD-07 | P1: Pipeline de Leads | Design | Pending |
| LEAD-08 | P1: Pipeline de Leads | Design | Pending |
| PIPE-01 | P1: Pipeline de Negócios | Design | Pending |
| PIPE-02 | P1: Pipeline de Negócios | Design | Pending |
| PIPE-03 | P1: Pipeline de Negócios | Design | Pending |
| PIPE-04 | P1: Pipeline de Negócios | Design | Pending |
| PIPE-05 | P1: Pipeline de Negócios | Design | Pending |
| PIPE-06 | P1: Pipeline de Negócios | Design | Pending |
| PIPE-07 | P1: Pipeline de Negócios | Design | Pending |
| QUOTE-01 | P1: Orçamentos | Design | Pending |
| QUOTE-02 | P1: Orçamentos | Design | Pending |
| QUOTE-03 | P1: Orçamentos | Design | Pending |
| QUOTE-04 | P1: Orçamentos | Design | Pending |
| QUOTE-05 | P1: Orçamentos | Design | Pending |
| FORM-01 | P1: Captação WordPress | Design | Pending |
| FORM-02 | P1: Captação WordPress | Design | Pending |
| FORM-03 | P1: Captação WordPress | Design | Pending |
| FORM-04 | P1: Captação WordPress | Design | Pending |
| FORM-05 | P1: Captação WordPress | Design | Pending |
| FORM-06 | P1: Captação WordPress | Design | Pending |
| NOTIF-01 | P1: Notificações internas | Design | Pending |
| NOTIF-02 | P1: Notificações internas | Design | Pending |
| NOTIF-03 | P1: Notificações internas | Design | Pending |
| NOTIF-04 | P1: Notificações internas | Design | Pending |
| MIG-01 | P1: Migração | Design | Pending |
| MIG-02 | P1: Migração | Design | Pending |
| MIG-03 | P1: Migração | Design | Pending |
| MIG-04 | P1: Migração | Design | Pending |
| MIG-05 | P1: Migração | Design | Pending |
| MIG-06 | P1: Migração | Design | Pending |
| MIG-07 | P1: Migração | Design | Pending |

**Coverage:** 55 requisitos produtivos, 0 mapeados a tarefas, 55 pendentes de Design produtivo. A base local reutilizável está documentada em `Delivery Baseline` e não será reconstruída.

---

## Success Criteria

- [ ] Um usuário conclui o fluxo WordPress → Lead → conversão → Negócio → orçamento → Ganho sem usar o Bitrix24.
- [ ] Um Vendedor não acessa Leads ou Negócios de terceiros quando não for responsável nem Assistente.
- [ ] Repetir tecnicamente uma submissão do WordPress não cria outro Lead, enquanto uma nova submissão da mesma pessoa cria um novo Lead.
- [ ] A migração contabiliza 100% dos itens lidos como criados, atualizados, ignorados ou falhos com motivo.
- [ ] As listas paginadas respondem em até 2 segundos nos volumes atuais informados.
- [ ] Todas as alterações de etapa, responsável, Assistente, exclusão, recuperação e automação ficam auditáveis.
