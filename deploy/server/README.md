# Instalação do Smart CRM no servidor

Este é o ponto de entrada canônico para instalar o ambiente privado de
homologação. O PostgreSQL, a migração Alembic e a aplicação são executados pelo
`compose.server.yaml`; não crie as tabelas manualmente.

## Arquivo secreto fora do Git

Crie o arquivo de ambiente fora do clone:

```bash
sudo install -d -m 750 /etc/smart-crm
sudo cp deploy/server/.env.server.example /etc/smart-crm/server.env
sudo chmod 600 /etc/smart-crm/server.env
sudo nano /etc/smart-crm/server.env
```

Gere `SMART_CRM_DB_PASSWORD` com:

```bash
openssl rand -hex 32
```

Nunca confirme `/etc/smart-crm/server.env` no Git. Em todos os comandos abaixo,
o arquivo é informado explicitamente com `--env-file`.

## Primeira subida

```bash
git clone https://github.com/lamarcon/smart_crm.git
cd smart_crm
git fetch --prune origin
git merge --ff-only origin/main

python3 scripts/verify_server_config.py --self-test
python3 scripts/verify_server_config.py --env-file /etc/smart-crm/server.env

docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml build
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml up -d postgres
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml run --rm migrate
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml up -d crm
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml ps
curl --fail http://127.0.0.1:8080/health
```

O serviço web fica somente em `127.0.0.1:8080`. Para acesso do cliente, use o
modelo `nginx-smart-crm.conf.example`, troque `CRM_DOMAIN`, emita o certificado
TLS e habilite Basic Auth. Não exponha a porta 8080 diretamente à internet.

## Atualização por Git

Antes de atualizar, registre o SHA atual e faça o backup descrito no runbook.

```bash
git fetch --prune origin
git merge --ff-only origin/main
python3 scripts/verify_server_config.py --env-file /etc/smart-crm/server.env
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml build
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml run --rm migrate
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml up -d crm
curl --fail http://127.0.0.1:8080/health
```

Consulte `RUNBOOK.md` para backup, restauração e rollback. Sempre substitua
qualquer referência a `.env.server` daquele documento por
`/etc/smart-crm/server.env` e mantenha `--env-file` nos comandos Compose.

## Limite desta entrega

Este ambiente é para homologação privada com dados fictícios. A aplicação ainda
não possui autenticação individual e autorização por perfil; Basic Auth protege
apenas o perímetro. O uso produtivo com dados reais depende da conclusão dessas
funções e do UAT operacional no servidor.
