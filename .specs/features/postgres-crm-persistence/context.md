# Persistência do Smart CRM no PostgreSQL - Contexto

**Gathered:** 2026-08-26
**Spec:** `.specs/features/postgres-crm-persistence/spec.md`
**Status:** Confirmed

---

## Feature Boundary

Esta entrega conecta o ambiente de teste ao PostgreSQL por uma API Python. Ela migra o estado comercial atual para tabelas normalizadas, torna o banco a fonte principal, preserva os fluxos existentes e bloqueia confirmações de alterações que não tenham sido persistidas.

---

## Implementation Decisions

### Fonte de dados

- O PostgreSQL passa a prevalecer assim que o workspace for inicializado.
- O `localStorage` deixa de ser a fonte comercial e permanece apenas como cache da última versão e armazenamento de estados transitórios.
- A migração inicial exige confirmação e mostra contagens ao Administrador simulado.

### Cobertura persistente

- Usuários, equipes, Leads, Contatos, Empresas, Negócios, Assistentes e vínculos usam tabelas relacionais.
- Campos personalizados usam definições e valores separados, preservando tipo, ordem, visibilidade e valores vazios.
- Orçamentos, notificações, presets nomeados, modo Lista/Kanban e configurações de campos também são persistidos.
- Busca digitada, modal aberto, drawer aberto e filtros não salvos permanecem locais.

### Integridade

- A migração inicial e cada gravação agregada são transacionais.
- O workspace usa versão otimista; somente uma gravação para a versão corrente é aceita.
- Exclusões são lógicas e recuperáveis.
- Sucesso visual só aparece depois da confirmação da API.

### Indisponibilidade

- Uma falha na carga usa o último cache válido em modo somente leitura.
- Uma falha durante alteração restaura o último estado confirmado.
- Saúde da aplicação diferencia banco saudável e indisponível.

### Agent's Discretion

- Framework HTTP, driver PostgreSQL e ferramenta de migração, escolhidos após consulta à documentação oficial.
- Nomes físicos de tabelas, índices e constraints, mantendo o modelo e os resultados definidos pela spec.
- Organização interna do cliente de API e da camada de repositório.

### Declined / Undiscussed Gray Areas → Assumptions

- A API continua local e sem autenticação real nesta entrega.
- A migração inicial aceita até 25 MB.
- O cache offline é somente leitura e não possui fila de sincronização.
- Auditoria produtiva detalhada, anexos binários e paginação de alto volume ficam para entregas próprias.

---

## Specific References

- A abordagem foi confirmada pelo usuário em 2026-08-26.
- O PostgreSQL `smartcrm_test` e o volume `postgres_data` já estão saudáveis no Compose.
- O protótipo atual possui 55 cenários de navegador que formam a regressão mínima desta integração.

---

## Deferred Ideas

- Autenticação, sessões e autorização reais no servidor.
- API granular paginada para os volumes completos do Bitrix24.
- Auditoria campo a campo e histórico produtivo.
- WordPress, migração direta do Bitrix24 e armazenamento real de PDFs.
