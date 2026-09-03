# Manual Windows PostgreSQL 11 Deployment Specification

## Problem Statement

O Smart CRM precisa ser levado ao Windows Server 2016 sem depender de Git, internet ou de uma nova instalação do PostgreSQL no servidor. A entrega deve reutilizar o Python 3.11 e o PostgreSQL 11 existentes, sem alterar o serviço ou os dados de outras aplicações.

## Goals

- [ ] Gerar um ZIP autocontido que possa ser copiado e instalado offline em `C:\Apps\smart-crm`.
- [ ] Criar somente o usuário e o banco exclusivos do CRM no PostgreSQL 11 existente.
- [ ] Bloquear a publicação no Apache até a migração e o `/health` local passarem.

## Out of Scope

| Feature | Reason |
| ------- | ------ |
| Instalar ou atualizar PostgreSQL | O usuário decidiu reutilizar a versão 11 já instalada. |
| Atualizar o Windows Server ou o Apache | Esta entrega prepara o CRM; manutenção do sistema operacional e do proxy é separada. |
| Renovar ou emitir o certificado TLS | O certificado do PunchSalad será tratado no corte, depois do teste local. |
| Migrar dados reais do Bitrix24 | A migração de dados continua como etapa própria do projeto. |
| Garantir produção antes do UAT no servidor | A aprovação depende de evidência obtida na máquina de destino. |

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --------------------- | -------------- | --------- | ---------- |
| Estratégia de transporte | Copiar um ZIP autocontido, sem Git no servidor | Escolha explícita do usuário para reduzir dependências de instalação. | y |
| Banco de dados | Reutilizar `postgresql-x64-11` em `127.0.0.1:5432` | Escolha explícita do usuário e porta padrão coerente com a instalação observada. | y |
| Isolamento do banco | Criar somente role `smartcrm` e database `smartcrm` | Evita mudanças no serviço, configuração e bancos das aplicações existentes. | y |
| Runtime Python | Exigir CPython 3.11 x64 em `C:\brbots\python\python.exe` | O caminho e a versão foram observados; x64 é necessário para as wheels do pacote e será validado antes da instalação. | n |
| Acesso à internet no servidor | Nenhum | O erro TLS já observado torna uma wheelhouse offline a opção reproduzível. | y |
| Caminho do Apache | Descobrir o caminho real antes de configurar o proxy | O Apache responde publicamente, mas não apareceu como serviço no levantamento inicial. | n |

**Open questions:** none - todas as incertezas têm default e validação bloqueante registrados acima.

## User Stories

### P1: Copiar um pacote autocontido ⭐ MVP

**User Story**: Como administrador do servidor, quero copiar um único ZIP com aplicação e dependências para instalar o CRM sem Git e sem acesso à internet.

**Why P1**: Sem o pacote offline, o erro TLS do servidor pode impedir a instalação das dependências.

**Acceptance Criteria**:

1. WHEN o gerador for executado com acesso ao índice Python THEN o gerador SHALL criar um ZIP versionado pelo commit e um arquivo SHA-256 correspondente em `dist`.
2. The ZIP SHALL conter `app`, `migrations`, `alembic.ini`, scripts de implantação, dependências fixadas e wheels compatíveis com CPython 3.11 x64 para Windows.
3. The ZIP SHALL excluir `.git`, `.specs`, `.venv`, testes, caches, chaves TLS e arquivos `server.env` com segredos.
4. IF qualquer arquivo extraído divergir do manifesto THEN o verificador de integridade SHALL encerrar com código diferente de zero antes da instalação.

**Independent Test**: Gerar o ZIP, listar seu conteúdo e executar o verificador após adulterar uma cópia em diretório temporário.

### P1: Instalar sem afetar o PostgreSQL existente ⭐ MVP

**User Story**: Como administrador do servidor, quero instalar o CRM usando os runtimes existentes sem interromper outras aplicações.

**Why P1**: O PostgreSQL 11 já atende outras cargas e não pode ser substituído ou reiniciado por esta instalação.

**Acceptance Criteria**:

1. IF `C:\brbots\python\python.exe` não for CPython 3.11 x64 THEN o instalador SHALL encerrar antes de criar ou alterar a virtualenv.
2. WHEN o instalador preparar a virtualenv THEN o instalador SHALL instalar somente a partir da wheelhouse com `--no-index`.
3. The configuração do CRM SHALL usar `127.0.0.1:5432`, database `smartcrm`, role `smartcrm` e senha hexadecimal de 64 caracteres armazenada fora do diretório da aplicação.
4. The procedimento SHALL proibir parar, reiniciar, remover ou reconfigurar o serviço `postgresql-x64-11`.
5. WHEN as credenciais do banco forem configuradas THEN o procedimento SHALL executar `alembic upgrade head` para criar as tabelas, sem comandos manuais `CREATE TABLE`.
6. WHEN o runtime for iniciado THEN o Uvicorn SHALL escutar somente em `127.0.0.1:8080`.
7. IF o endpoint local `/health` não retornar exatamente `{"status":"ok","database":"ok"}` THEN o procedimento SHALL bloquear a configuração ou reinicialização do Apache.

**Independent Test**: Instalar em uma pasta limpa, validar a configuração, aplicar as migrações no banco exclusivo e consultar o endpoint local.

## Edge Cases

- IF o PostgreSQL 11 não estiver ouvindo em `127.0.0.1:5432` THEN o procedimento SHALL parar antes da migração.
- IF o banco ou a role `smartcrm` já existirem THEN o procedimento SHALL orientar a validação da propriedade e não recriar nem apagar objetos existentes.
- IF a migração Alembic falhar THEN o procedimento SHALL manter o Apache inalterado e registrar a falha como bloqueio.

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| -------------- | ----- | ----- | ------ |
| MPG-01 | P1: Copiar pacote | Execute | Implementing |
| MPG-02 | P1: Copiar pacote | Execute | Implementing |
| MPG-03 | P1: Copiar pacote | Execute | Implementing |
| MPG-04 | P1: Copiar pacote | Execute | Implementing |
| MPG-05 | P1: Instalar | Execute | Implementing |
| MPG-06 | P1: Instalar | Execute | Implementing |
| MPG-07 | P1: Instalar | Execute | Implementing |
| MPG-08 | P1: Instalar | Execute | Implementing |
| MPG-09 | P1: Instalar | Execute | Implementing |
| MPG-10 | P1: Instalar | Execute | Implementing |
| MPG-11 | P1: Instalar | Execute | Implementing |
| MPG-12 | Edge case: PostgreSQL indisponível | Execute | Implementing |
| MPG-13 | Edge case: objetos existentes | Execute | Implementing |
| MPG-14 | Edge case: migração falhou | Execute | Implementing |

**Coverage:** 14 total, 14 mapeados ao plano de execução, 0 não mapeados.

## Success Criteria

- [ ] O ZIP e seu SHA-256 são gerados e o conteúdo passa no verificador de contrato.
- [ ] A instalação de dependências no servidor não exige acesso à internet.
- [ ] Nenhum comando do kit altera o serviço ou o diretório de dados do PostgreSQL 11.
- [ ] O Apache só entra no procedimento depois de migração e saúde local aprovadas.
