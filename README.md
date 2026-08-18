# Smart CRM

CRM em desenvolvimento para substituir o uso comercial atual do Bitrix24. O repositório contém as especificações do MVP de produção e um protótipo local navegável para validação antecipada do layout e dos fluxos.

## Protótipo local

O protótipo é uma demonstração funcional com dados fictícios. Ele inclui:

- Dashboard e navegação responsiva;
- listas de Leads, Contatos, Empresas e Negócios;
- criação e exclusão local, com edição ao clicar no nome e abrir o painel lateral;
- busca em todos os campos pesquisáveis e filtros configuráveis por campo, operador, responsável, período e etapa;
- filtros nomeados salvos por usuário e por módulo no navegador;
- alternância entre Lista e Kanban para Leads e Negócios;
- Pipeline fixa com barra de etapas segmentada, confirmações para transições protegidas e ação de desfazer;
- conversão demonstrativa de Lead em Negócio;
- orçamento com cálculo de total e seleção opcional de PDF;
- automação demonstrativa de atribuição ao Faturamento;
- Dashboard filtrável nos escopos Todos, Leads e Negócios, com recálculo de indicadores, Pipeline e movimentações;
- notificações internas;
- seletor de perfil para simular Administrador, Gestor, Vendedor e Assistente.

### Usar o workspace comercial

- Em Leads, Contatos, Empresas ou Negócios, clique no nome de um registro para editar seus dados no painel lateral direito.
- Use **Filtros** para combinar quantos critérios forem necessários. Valores múltiplos de um mesmo campo funcionam como alternativas; campos diferentes são combinados simultaneamente.
- Em Leads e Negócios, alterne entre **Lista** e **Kanban**. A preferência e os filtros ativos são preservados no navegador.
- Na Visão geral, use **Filtrar painel** para escolher o escopo e analisar um responsável, uma equipe, um período ou uma etapa específica.
- Mudanças para Faturando, etapas de encerramento, descarte ou conversão pedem confirmação ou motivo. Transições de etapa concluídas exibem **Desfazer** por alguns segundos.

### Iniciar

Pré-requisito: Docker Desktop em execução.

```powershell
docker compose up --build -d
```

Abra [http://localhost:8080](http://localhost:8080).

Para usar outra porta local:

```powershell
$env:SMART_CRM_PORT=8081
docker compose up --build -d
```

### Verificar

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8080/health
```

O serviço deve aparecer como `healthy`, e a rota de saúde deve retornar `{"status":"ok","service":"smart-crm-demo"}`.

Para executar a regressão completa do protótipo:

```powershell
pnpm install
pnpm test
python scripts/verify_demo.py
```

### Restaurar os dados

Use o botão **Restaurar demo** na Visão geral. As alterações ficam somente no `localStorage` do navegador utilizado.

### Logs e encerramento

```powershell
docker compose logs -f crm
docker compose down
```

## Limitações importantes

Esta versão serve apenas para validar aparência e experiência de uso. Ela não possui PostgreSQL, autenticação real, autorização no servidor, persistência multiusuário, integração com WordPress, importação ou sincronização com o Bitrix24, nem armazenamento real de PDFs. Não devem ser inseridos dados pessoais ou comerciais reais.

O escopo produtivo permanece documentado em [.specs/features/crm-mvp/spec.md](.specs/features/crm-mvp/spec.md). O recorte inicial da demonstração está em [.specs/features/ui-prototype/spec.md](.specs/features/ui-prototype/spec.md), e a evolução deste workspace está em [.specs/features/ui-crm-workspace/spec.md](.specs/features/ui-crm-workspace/spec.md).
