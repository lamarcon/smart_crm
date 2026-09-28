# Funil de Negócios Personalizável V1 — Context

## Product Decisions

- A V1 possui somente um funil de Negócios por empresa.
- Administradores podem criar, renomear, reordenar, recolorir e arquivar etapas.
- O nome visível não é a identidade; os tipos internos são `open`, `won` e `lost`.
- Etapa ocupada só pode ser arquivada após seleção de destino e transferência total.
- A V1 não possui probabilidade por etapa.
- Mudanças de configuração ficam em histórico administrativo.
- Recomendações técnicas de versionamento, auditoria atômica, IDs estáveis e preparação para múltiplos funis foram aprovadas.

## Existing System Facts

- `app/static/index.html` define `dealStages` com nove strings e usa nomes em Kanban, filtros, dashboard, criação, ganho, encerramento e automação de Faturamento.
- `app/models.py` persiste `Deal.stage` e `DealStageHistory.from_stage/to_stage` como texto.
- `app/repositories/workspace.py` reconcilia o snapshot inteiro e recria o histórico de cada Negócio.
- `app/services/workspace.py` usa versão otimista do workspace e projeção/merge por perfil.
- `app/main.py` resolve tenant e usuário exclusivamente da sessão e já possui dependência central de autorização.
- `app/policies.py` concentra ações administrativas e deverá receber `MANAGE_PIPELINE`.
- A revisão tenant atual é `a4c9d2e7f1b6`; o roteador exige igualdade com `expected_tenant_revision` do plano de controle.
- As tabelas tenant usam `workspace_id`, RLS habilitada e forçada, com contexto transacional `smartcrm.workspace_id`.
- Produção usa pacote offline Windows, release lado a lado e PostgreSQL 11 compartilhado, sem incluir `DW_CMS` ou `DW_PRODUTOS` nas migrações do CRM.

## Approved UX Defaults

- Item administrativo separado: **Funil de negócios**.
- Editor em lista com nome, cor, tipo semântico, marcador de etapa inicial, ordem e ação Arquivar.
- Reordenação por arrastar/soltar e botões subir/descer.
- Tipos semânticos aparecem em português como Em andamento, Ganho e Perdido, mas não podem ser alterados após a criação.
- Ao arquivar etapa ocupada, modal mostra quantidade, destino obrigatório e o efeito semântico da transferência.
- Histórico paginado mostra ator, data/hora, resumo, antes/depois e contagem transferida.
- Conflito de versão pede recarregamento; não tenta mesclar silenciosamente.

## Legacy Stage Mapping

| Ordem | Nome atual | Tipo | Cor inicial | Chave interna |
| ----- | ---------- | ---- | ------------ | ------------- |
| 0 | Em Contato | open | preservar cor atual da UI | initial |
| 1 | Orçamento Proposta Preço | open | preservar cor atual da UI | - |
| 2 | Orçamentos enviados | open | preservar cor atual da UI | - |
| 3 | Negociação Revisão | open | preservar cor atual da UI | - |
| 4 | Pedido aprovado Consultar | open | preservar cor atual da UI | - |
| 5 | Faturando | open | preservar cor atual da UI | billing |
| 6 | Ganho | won | preservar cor atual da UI | - |
| 7 | Orçamento Não Aprovado | lost | preservar cor atual da UI | - |
| 8 | Analisar falha | lost | preservar cor atual da UI | - |

As cores exatas serão extraídas do registry visual existente durante a tarefa de migração; não serão inventadas na especificação.

## Security Boundaries

- O tenant e workspace vêm somente da sessão autenticada.
- Leitura do funil é permitida a usuários autenticados; alteração e histórico administrativo são exclusivos de Administrador.
- A configuração não entra no snapshot integral substituível pelo navegador.
- IDs de pipeline e etapa enviados pelo cliente são sempre conferidos contra o workspace da sessão.
- Não existe endpoint de exclusão física de etapa ou auditoria.

## Deferred Ideas

- Múltiplos funis por empresa.
- Probabilidade e previsão por etapa.
- Editor de automações por etapa.
- Templates, duplicação e importação de funis.
- Personalização do funil de Leads.
- SLA/tempo máximo por etapa.
