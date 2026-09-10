# CRM Relationship Cards Context

## Product Decisions

- Os vínculos continuam baseados nos nomes já persistidos em `company` e `contact`.
- A correspondência ignora maiúsculas e espaços nas extremidades.
- A listagem de Negócios mostra um resumo compacto com os principais dados encontrados.
- O Kanban mostra Empresa e Contato, mantendo valor, responsável, etapa e ações atuais.
- A listagem de Empresas mostra contagem e nomes dos contatos associados.
- Vínculos ausentes são informativos e não impedem renderização, edição ou persistência.

## Deferred Ideas

- Transformar os resumos em links para abrir a entidade relacionada.
- Migrar vínculos textuais para identificadores estáveis.
- Propagar renomeações de Empresa e Contato para os registros relacionados.
