# Histórico Operacional de Negócios e Empresas V1 — Context

## Product Decisions

- O painel de Negócio será amplo, ocupando a maior parte da área útil do navegador, semelhante à experiência de detalhe do Bitrix24.
- Em desktop, os dados do Negócio ficam à esquerda e a linha do tempo operacional fica à direita.
- O histórico do Negócio reúne movimentações de etapa, execuções/notificações de automação e observações manuais.
- Tarefas, agenda e calendário estão explicitamente fora da V1.
- Observações manuais são permanentes: depois de enviadas, não podem ser editadas nem excluídas.
- A Empresa terá as abas `Informações`, `Negócios` e `Histórico`, em uma experiência semelhante à ficha de empresa do RD Station.
- A aba `Negócios` da Empresa mostra total, quantidade e valor em andamento, ganhos e perdidos, além da lista de Negócios vinculados.
- A aba `Histórico` da Empresa mostra alterações do cadastro e observações manuais; movimentações detalhadas dos Negócios não são duplicadas nela.

## Existing System Facts

- `app/models.py` já possui `DealStageHistory`, com etapa anterior, etapa posterior, IDs estáveis, ator e instante.
- `Deal` já persiste `pipeline_id`, `stage_id`, `stage_changed_at`, `stage_changed_by_id` e `won_at`.
- O funil canônico usa tipos semânticos imutáveis `open`, `won` e `lost`, portanto indicadores não precisam depender do nome visível da etapa.
- `app/repositories/workspace.py` já projeta `stageHistory` no registro de Negócio.
- A automação interna da etapa com `system_key=billing` altera responsável e cria uma notificação.
- O modelo atual de `Notification` é voltado ao destinatário e não é uma fonte de auditoria imutável do Negócio.
- `Company` possui campos relacionais e payload adicional, mas ainda não possui modelo dedicado de eventos.
- O drawer atual tem aproximadamente 560px e abas de informações, campos adicionais e orçamentos; ele precisará de uma variação ampla para esta experiência.
- A aplicação é multiempresa, com um banco de negócio por tenant, workspace derivado da sessão e RLS forçada.

## Approved UX Defaults

- A linha do tempo usa ordem decrescente, do evento mais recente para o mais antigo.
- Cada item exibe tipo, descrição, ator e data/hora; transições mostram etapa anterior e posterior.
- O compositor de observação permanece no topo da coluna direita e exige confirmação explícita de envio.
- A linha do tempo pode ser filtrada por `Tudo`, `Movimentações`, `Automações` e `Observações`.
- O painel de Empresa usa cartões de resumo e uma tabela/lista dos Negócios vinculados.
- Negócios excluídos logicamente não entram nos indicadores operacionais da Empresa.
- Em telas estreitas, as duas colunas viram abas/seções empilhadas sem perder nenhuma função.

## Security and Integrity Boundaries

- Tenant e workspace continuam vindo somente da sessão autenticada.
- Quem pode visualizar a entidade pode visualizar seu histórico e seus indicadores.
- Somente quem pode alterar a entidade pode publicar observações nela.
- O cliente não pode fornecer ator, tenant, workspace ou timestamp canônico de um evento.
- Eventos persistidos e observações não possuem endpoint de edição ou exclusão.
- Uma falha ao persistir evento e mutação comercial deve reverter a operação inteira.

## Deferred Ideas

- Tarefas, lembretes, agendamento, calendário e painel geral de atividades.
- Ticket médio, tempo médio até a venda e previsões.
- Comentários encadeados, menções, anexos e mensagens externas.
- Edição ou exclusão de observações.
- Replicação de todas as movimentações dos Negócios no histórico da Empresa.
- Editor de regras de automação.
- Deploy, publicação ou alteração do servidor em produção.
