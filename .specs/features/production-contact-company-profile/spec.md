# Production Contact Company Profile Specification

## Problem Statement

A interface publicada ainda se identifica como ambiente de demonstração e a ficha do Contato não apresenta os dados da Empresa vinculada, obrigando o usuário a procurar a organização em outra tela.

## Goals

- Remover da interface pronta os avisos visuais de ambiente de demonstração ou local.
- Mostrar na ficha do Contato um resumo da Empresa vinculada.

## Out of Scope

| Feature | Reason |
| --- | --- |
| Alterar o modelo de dados do vínculo | Os registros atuais continuam relacionados pelo nome da Empresa. |
| Criar abas iguais às do Bitrix | A referência visual serve apenas para o resumo da Empresa dentro da ficha. |
| Deploy no servidor | Esta entrega altera e valida somente o arquivo local. |

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Estado pronto do workspace | Ocultar a faixa superior | Remove o aviso sem perder alertas de banco vazio ou indisponível. | y |
| Aviso lateral local | Remover por completo | A aplicação publicada não deve se apresentar como ambiente local. | y |
| Dados da Empresa na ficha | Nome, segmento, cidade e telefone | São as informações principais disponíveis no cadastro atual. | y |
| Empresa não localizada | Mostrar o nome informado e `Cadastro não localizado` | Preserva o vínculo textual e deixa clara a inconsistência. | y |

**Open questions:** none - all resolved or logged above.

## User Stories

### P1: Interface de produção

**User Story**: Como usuário do CRM, quero navegar sem avisos de demonstração para reconhecer a aplicação como ambiente operacional.

**Acceptance Criteria**:

1. WHILE o workspace estiver pronto THEN the system SHALL ocultar a faixa superior de status em todas as telas.
2. WHILE a aplicação estiver aberta THEN the system SHALL usar o título `Smart CRM` e não exibir o aviso lateral `Ambiente local`.
3. IF o banco estiver vazio ou indisponível THEN the system SHALL manter visível a faixa superior com a orientação correspondente.

### P1: Empresa vinculada na ficha do Contato

**User Story**: Como usuário do CRM, quero ver a Empresa vinculada ao abrir um Contato para entender seu contexto comercial na mesma ficha.

**Acceptance Criteria**:

1. WHEN o usuário abrir um Contato com Empresa cadastrada THEN the system SHALL mostrar, na ficha, o nome, segmento, cidade e telefone dessa Empresa.
2. IF o Contato tiver um nome de Empresa sem cadastro correspondente THEN the system SHALL mostrar esse nome e `Cadastro não localizado`.
3. IF o Contato não tiver Empresa informada THEN the system SHALL mostrar `Nenhuma empresa vinculada`.

## Edge Cases

- IF o nome vinculado diferir apenas por maiúsculas ou espaços externos THEN the system SHALL localizar a Empresa correspondente.

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| PCCP-01 | P1: Interface de produção | Execute | Verified |
| PCCP-02 | P1: Interface de produção | Execute | Verified |
| PCCP-03 | P1: Interface de produção | Execute | Verified |
| PCCP-04 | P1: Empresa vinculada | Execute | Verified |
| PCCP-05 | P1: Empresa vinculada | Execute | Verified |
| PCCP-06 | P1: Empresa vinculada | Execute | Verified |
| PCCP-07 | Edge case: nome normalizado | Execute | Verified |

**Coverage:** 7 total, 7 mapped to inline execution steps, 0 unmapped.

## Success Criteria

- A interface pronta não apresenta avisos de demonstração ou ambiente local.
- Alertas operacionais de banco vazio ou indisponível continuam visíveis.
- A ficha do Contato apresenta o resumo da Empresa vinculada e estados explícitos para vínculo ausente ou inválido.