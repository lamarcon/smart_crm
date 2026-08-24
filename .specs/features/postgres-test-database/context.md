# Banco PostgreSQL local para testes — Contexto

**Gathered:** 2026-08-24
**Spec:** `.specs/features/postgres-test-database/spec.md`
**Status:** Ready for implementation

---

## Feature Boundary

Esta entrega adiciona e valida um PostgreSQL local no Docker. Ela não conecta os módulos do Smart CRM ao banco e não migra o estado já salvo no navegador.

## Implementation Decisions

### Isolamento e acesso

- O serviço se chamará `postgres` na rede interna do Compose.
- A porta será publicada somente no loopback do computador.
- Banco, usuário, senha e porta aceitarão substituição por variáveis de ambiente.

### Persistência e verificação

- O diretório de dados usará o volume nomeado `postgres_data`.
- O healthcheck usará `pg_isready` com o banco e o usuário configurados.
- O gate criará uma tabela técnica `_smartcrm_test_probe`, garantirá uma única linha, reiniciará o serviço e confirmará a persistência.

### Agent's Discretion

- Intervalos e tentativas do healthcheck, desde que o limite do gate permaneça em 30 segundos.

### Declined / Undiscussed Gray Areas → Assumptions

- Backup, restauração e esquema comercial ficam para a etapa de integração com a API.
- As credenciais padrão são locais e não serão reutilizadas em produção.

## Specific References

No specific requirements - standard Docker Compose and PostgreSQL behavior applies.

## Deferred Ideas

- API de persistência para Leads, Contatos, Empresas, Negócios, usuários e campos personalizados.
- Migração dos dados existentes do `localStorage`.
