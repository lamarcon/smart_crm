# Manual Windows PostgreSQL 11 Deployment Context

**Gathered:** 2026-09-03
**Spec:** `.specs/features/manual-windows-pg11-deployment/spec.md`
**Status:** Implemented and independently verified

## Feature Boundary

Entregar um arquivo compactado que o administrador copie para o Windows Server 2016 e instale offline usando Python 3.11 e PostgreSQL 11 já existentes. O pacote prepara o CRM, cria suas tabelas por Alembic e comprova a saúde local antes do corte no Apache.

## Implementation Decisions

### Transporte

- Um ZIP substitui Git como mecanismo de transporte para esta implantação.
- O ZIP leva código, migrações, scripts, wheelhouse e manifesto SHA-256.

### PostgreSQL 11 compartilhado

- O CRM usa a instância existente em `127.0.0.1:5432`.
- A única mudança autorizada é criar a role `smartcrm` e o database `smartcrm`.
- O procedimento não edita `postgresql.conf`, `pg_hba.conf`, serviço ou diretório de dados.

### Instalação e corte

- As dependências são instaladas com `--no-index`.
- Segredos ficam em `C:\ProgramData\SmartCRM\server.env`.
- Migração e `/health` local são gates obrigatórios antes do Apache.

### Agent's Discretion

- Estrutura interna do ZIP, desde que ele possa ser extraído diretamente em `C:\brbots\apps\smart-crm`.
- Formato do manifesto, desde que use SHA-256 e rejeite arquivo ausente ou adulterado.

### Declined / Undiscussed Gray Areas → Assumptions

- A arquitetura do Python ainda não foi mostrada; o pacote assume x64 e o instalador bloqueia qualquer outra arquitetura.
- O caminho real do Apache ainda não foi identificado; o runbook inclui descoberta antes de copiar a configuração.

## Specific References

- Python observado em `C:\brbots\python\python.exe`.
- PostgreSQL observado como serviço `postgresql-x64-11` e cliente em `C:\Program Files\PostgreSQL\11\bin\psql.exe`.
- Host público definido pelo usuário: `sc2030.brbots.com`.

## Deferred Ideas

- Atualização futura para uma versão suportada do PostgreSQL.
- Retorno ao fluxo de atualização por Git depois da estabilização do servidor.
