# Smart CRM: runbook de instalação privada

Este pacote instala a versão atual por Git com Docker Compose, PostgreSQL 17, Alembic e Nginx. O PostgreSQL não publica porta. O CRM escuta em `127.0.0.1:8080` e só chega ao cliente por HTTPS com uma senha compartilhada, VPN ou túnel SSH.

> Esta implantação é de homologação. O CRM ainda não possui login e autorização reais no servidor. Não use dados reais do cliente.

## Pré-requisitos

Servidor Linux com Git, Docker Engine, plugin Docker Compose, Nginx, OpenSSL e `htpasswd`:

```bash
git --version
docker --version
docker compose version
nginx -v
openssl version
```

Em Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y git nginx apache2-utils openssl
```

Instale Docker pelo procedimento oficial da distribuição. Use o mesmo usuário ou o mesmo prefixo `sudo` em todos os comandos Docker.

## Clonar pelo Git

```bash
sudo install -d -o "$USER" -g "$USER" /opt/smart-crm
git clone https://github.com/lamarcon/smart_crm.git /opt/smart-crm
cd /opt/smart-crm
git switch main
git pull --ff-only origin main
git rev-parse HEAD
```

Registre o SHA exibido. Ele identifica a versão instalada e permite rollback do código.

## Criar `/etc/smart-crm/server.env`

```bash
cd /opt/smart-crm
sudo install -d -o "$USER" -g "$USER" -m 750 /etc/smart-crm
umask 077
cp deploy/server/.env.server.example /etc/smart-crm/server.env
DB_PASSWORD="$(openssl rand -hex 32)"
sed -i "s/REPLACE_WITH_64_HEX_CHARACTERS/$DB_PASSWORD/" /etc/smart-crm/server.env
unset DB_PASSWORD
chmod 600 /etc/smart-crm/server.env
grep -v '^SMART_CRM_DB_PASSWORD=' /etc/smart-crm/server.env
```

O arquivo mantém estes defaults seguros:

| Variável | Valor |
| --- | --- |
| `SMART_CRM_DB_NAME` | `smartcrm` |
| `SMART_CRM_DB_USER` | `smartcrm` |
| `SMART_CRM_BIND_IP` | `127.0.0.1` |
| `SMART_CRM_PORT` | `8080` |

`SMART_CRM_DB_PASSWORD` deve ter os 64 caracteres hexadecimais gerados. O arquivo não pode entrar no Git.

## Validar sem iniciar containers

```bash
python3 scripts/verify_server_config.py --env-file /etc/smart-crm/server.env
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml --profile tools config --quiet
```

Resultado esperado:

```text
server deployment config: 10 passed, 0 failed
```

O gate rejeita senha placeholder, PostgreSQL publicado, CRM fora de loopback, migração errada, test mode e runtime gravável.

## Criar banco, tabelas e iniciar

O PostgreSQL cria o banco/usuário a partir do `/etc/smart-crm/server.env`. Não escreva `CREATE TABLE` manualmente. Alembic cria todas as tabelas e controla suas versões.

```bash
cd /opt/smart-crm
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml build --pull
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml up -d postgres
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml ps
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml run --rm migrate
```

Somente se a migração terminar com código zero:

```bash
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml up -d crm
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml ps
curl --fail --silent --show-error http://127.0.0.1:8080/health
```

Resposta exata:

```json
{"status":"ok","database":"ok"}
```

Conferir Alembic e tabelas:

```bash
set -a
. /etc/smart-crm/server.env
set +a
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml exec -T crm alembic current
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml exec -T postgres \
  psql -U "$SMART_CRM_DB_USER" -d "$SMART_CRM_DB_NAME" -c '\dt'
unset SMART_CRM_DB_PASSWORD
```

Na primeira abertura, confirme a inicialização do workspace com o perfil demonstrativo Administrador apenas depois de conferir domínio e banco.

## HTTPS e senha externa

A senha HTTP deve ser diferente da senha PostgreSQL:

```bash
sudo htpasswd -c /etc/nginx/.htpasswd-smart-crm crm-homologacao
sudo chmod 640 /etc/nginx/.htpasswd-smart-crm
sudo chown root:www-data /etc/nginx/.htpasswd-smart-crm
```

Para o primeiro certificado, use o modo standalone antes de habilitar o arquivo que referencia o certificado:

```bash
sudo apt-get install -y certbot
sudo systemctl stop nginx
sudo certbot certonly --standalone -d crm.seudominio.com.br
sudo systemctl start nginx
```

Copie e ajuste o virtual host:

```bash
cd /opt/smart-crm
sudo cp deploy/server/nginx-smart-crm.conf.example /etc/nginx/sites-available/smart-crm
sudo sed -i 's/CRM_DOMAIN/crm.seudominio.com.br/g' /etc/nginx/sites-available/smart-crm
sudo ln -s /etc/nginx/sites-available/smart-crm /etc/nginx/sites-enabled/smart-crm
sudo nginx -t
sudo systemctl reload nginx
```

Teste em janela anônima. A senha Nginx deve ser exigida para `/` e `/api/workspace`.

Sem domínio/HTTPS, não altere `SMART_CRM_BIND_IP`. Use VPN ou túnel:

```bash
ssh -L 8080:127.0.0.1:8080 usuario@servidor
```

Abra `http://127.0.0.1:8080` na máquina local.

## Operação e logs

```bash
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml ps
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml logs --tail 100 crm
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml logs --tail 100 postgres
curl --fail --silent --show-error http://127.0.0.1:8080/health
```

Reiniciar o CRM preserva o volume:

```bash
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml restart crm
```

Nunca execute `docker compose down -v`: `-v` apaga o PostgreSQL.

## Backup antes de atualizar

```bash
cd /opt/smart-crm
set -a
. /etc/smart-crm/server.env
set +a
BACKUP_DIR="/var/backups/smart-crm/$(date -u +%Y%m%dT%H%M%SZ)"
sudo install -d -o "$USER" -g "$USER" "$BACKUP_DIR"
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml exec -T postgres \
  pg_dump -U "$SMART_CRM_DB_USER" -d "$SMART_CRM_DB_NAME" --format=custom \
  > "$BACKUP_DIR/smartcrm.dump"
git rev-parse HEAD > "$BACKUP_DIR/application.sha"
sha256sum "$BACKUP_DIR/smartcrm.dump" > "$BACKUP_DIR/smartcrm.dump.sha256"
chmod 600 "$BACKUP_DIR"/*
unset SMART_CRM_DB_PASSWORD
echo "$BACKUP_DIR"
```

Copie o dump para outro host/armazenamento. Backup no mesmo disco não protege contra perda do servidor.

## Atualizar por fast-forward

Pare se `git status --short` exibir alterações. O servidor não deve editar código versionado.

```bash
cd /opt/smart-crm
git status --short
OLD_SHA="$(git rev-parse HEAD)"
echo "$OLD_SHA"
```

Faça o backup acima. Depois:

```bash
git fetch --prune origin
git merge --ff-only origin/main
NEW_SHA="$(git rev-parse HEAD)"
echo "$NEW_SHA"
python3 scripts/verify_server_config.py --env-file /etc/smart-crm/server.env
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml build --pull
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml run --rm migrate
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml up -d --no-deps crm
curl --fail --silent --show-error http://127.0.0.1:8080/health
```

## Rollback

Se o schema continua compatível, volte somente a aplicação ao SHA registrado:

```bash
cd /opt/smart-crm
git switch --detach "$OLD_SHA"
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml build
docker compose --env-file /etc/smart-crm/server.env -f compose.server.yaml up -d --no-deps crm
curl --fail --silent --show-error http://127.0.0.1:8080/health
```

Depois de corrigir ou descartar a atualização problemática, retorne à versão atual:

```bash
git switch main
git fetch --prune origin
git merge --ff-only origin/main
```

Se a migração alterou o schema de forma incompatível, voltar o código não basta. Pare o CRM e restaure o dump pré-migração em uma janela de manutenção. Restaurar substitui dados: confira SHA, hash e caminho antes de autorizar essa operação. Não use `down -v` como rollback.

## O que funciona agora

- layout e módulos atuais;
- Leads, Contatos, Empresas, Negócios, Pipelines, orçamentos e notificações demonstrativas;
- persistência PostgreSQL e reinício sem perda;
- acesso remoto protegido por HTTPS e senha compartilhada.

Ainda bloqueado para produção real:

- login individual e autorização no servidor;
- auditoria e APIs granulares;
- WordPress e migração integral do Bitrix24;
- backup automático, monitoramento e UAT de corte.

## Checklist

- [ ] SHA implantado registrado.
- [ ] `/etc/smart-crm/server.env` com modo `600` e fora do Git.
- [ ] Verificador: `10 passed, 0 failed`.
- [ ] PostgreSQL sem porta publicada.
- [ ] Alembic no head e tabelas listadas.
- [ ] `/health` com JSON exato.
- [ ] Porta 8080 somente em `127.0.0.1`.
- [ ] HTTPS e Basic Auth, ou VPN/túnel.
- [ ] Backup externo antes da primeira atualização.
- [ ] Ambiente sem dados reais.
