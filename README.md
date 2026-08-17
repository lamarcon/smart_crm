# Smart CRM

CRM em desenvolvimento para substituir o uso comercial atual do Bitrix24. O repositório contém as especificações do MVP de produção e um protótipo local navegável para validação antecipada do layout e dos fluxos.

## Protótipo local

O protótipo é uma demonstração funcional com dados fictícios. Ele inclui:

- Dashboard e navegação responsiva;
- listas de Leads, Contatos, Empresas e Negócios;
- criação, edição, exclusão, busca e filtros locais;
- Pipeline fixa de Leads e Negócios;
- conversão demonstrativa de Lead em Negócio;
- orçamento com cálculo de total e seleção opcional de PDF;
- automação demonstrativa de atribuição ao Faturamento;
- notificações internas;
- seletor de perfil para simular Administrador, Gestor, Vendedor e Assistente.

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

### Restaurar os dados

Use o botão **Restaurar demo** na Visão geral. As alterações ficam somente no `localStorage` do navegador utilizado.

### Logs e encerramento

```powershell
docker compose logs -f crm
docker compose down
```

## Limitações importantes

Esta versão serve apenas para validar aparência e experiência de uso. Ela não possui PostgreSQL, autenticação real, autorização no servidor, persistência multiusuário, integração com WordPress, migração do Bitrix24 ou armazenamento real de PDFs. Não devem ser inseridos dados pessoais ou comerciais reais.

O escopo produtivo permanece documentado em [.specs/features/crm-mvp/spec.md](.specs/features/crm-mvp/spec.md). O recorte desta demonstração está em [.specs/features/ui-prototype/spec.md](.specs/features/ui-prototype/spec.md).
