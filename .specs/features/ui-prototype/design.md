# Design — Protótipo Local do Smart CRM

**Spec**: `.specs/features/ui-prototype/spec.md`  
**Status**: Approved

## Arquitetura

O protótipo usa um único processo Python baseado na biblioteca padrão para servir a interface estática e a rota `/health`. Toda regra demonstrativa é executada no navegador. O estado é serializado em `localStorage`, portanto não há banco, sessão compartilhada ou gravação no container.

```text
Navegador
  ├─ interface HTML/CSS/JavaScript
  ├─ dados fictícios iniciais
  └─ estado localStorage
          │ HTTP
          ▼
Servidor Python estático
  ├─ GET /
  ├─ GET /assets/*
  └─ GET /health
          │
          ▼
Container Docker (porta 8000 → localhost:8080)
```

## Componentes

### `app/server.py`

- Servidor HTTP sem dependências Python externas.
- Entrega `app/static/index.html` e ativos locais.
- Responde `/health` com JSON.
- Oferece `--self-test` para verificar saúde, resolução segura de caminhos e presença dos arquivos essenciais.

### `app/static/index.html`

- Documento autocontido com a estrutura visual, estilos e comportamento do protótipo.
- Mantém o estado `smart-crm-demo-v1` no `localStorage`.
- Inclui dados fictícios, navegação, tabelas, modais, filtros, formulários e notificações.
- Não realiza chamadas a APIs externas, fontes remotas ou CDNs.

### Container

- `Dockerfile` usa Python 3.12 slim, usuário não privilegiado e verificação de saúde.
- `compose.yaml` publica somente a porta local 8080 e não declara banco ou dependências.

## Modelo de estado demonstrativo

```text
state
  ├─ currentProfile
  ├─ users[]
  ├─ leads[]
  ├─ contacts[]
  ├─ companies[]
  ├─ deals[]
  │    └─ quotes[]
  └─ notifications[]
```

Cada registro usa identificador local, datas legíveis e referências simples por identificador. A exclusão remove o item apenas do estado demonstrativo. A restauração descarta o `localStorage` e recria toda a massa fictícia.

## Regras de demonstração

- Administrador vê tudo.
- Gestor vê registros da equipe de Vendas CMS.
- Vendedor vê registros de sua responsabilidade ou em que conste como Assistente.
- Assistente usa um usuário de exemplo e vê somente os cards em que foi incluído.
- Converter Lead cria um Negócio e uma notificação.
- Mover para Faturando troca o responsável para “Equipe Faturamento” e notifica.
- O orçamento calcula `quantidade × valor unitário − desconto` e guarda o nome de um PDF opcional.

## Estados e falhas

- Formulários exigem os campos essenciais marcados na interface.
- Um aviso visual confirma ações concluídas ou bloqueadas.
- Se o `localStorage` estiver corrompido, o protótipo recupera os dados iniciais.
- Nenhuma ação da demonstração é tratada como persistência durável.

## Segurança e produção

O servidor impede saída do diretório estático ao resolver caminhos. Isso não transforma o protótipo em sistema produtivo: não há autenticação real, autorização no backend, proteção de dados pessoais, CSRF, auditoria ou persistência multiusuário.

## Verificação

- Autoteste Python do servidor.
- Verificação sintática do JavaScript incorporado será feita pela extração para arquivo temporário durante a execução dos gates.
- `docker compose config`, construção da imagem e healthcheck.
- Navegação visual nos viewports desktop e móvel.
