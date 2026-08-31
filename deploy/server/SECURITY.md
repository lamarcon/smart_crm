# Segredos do ambiente de servidor

O arquivo com a senha real do PostgreSQL deve ficar fora do clone Git.

Use `/etc/smart-crm/server.env` e passe `--env-file /etc/smart-crm/server.env`
em todos os comandos `docker compose`. O arquivo
`deploy/server/.env.server.example` contém apenas valores de exemplo e pode
permanecer versionado.

Nunca crie ou confirme `.env.server` dentro do repositório enquanto esse nome
não estiver coberto pelo `.gitignore` versionado.
