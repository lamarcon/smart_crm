# API de captação de Leads

Sistemas externos (o bot do Instagram, um formulário do site, uma landing page) usam esta API para criar Leads no Smart CRM. Cada Lead recebido guarda a origem: canal, campanha, UTMs, ID externo, página e a chave usada. Essas informações aparecem no bloco **Origem e rastreio** do Lead.

## 1. Criar a chave

1. Entre como **Administrador** e abra **Usuários e permissões → Captação de Leads**.
2. Clique em **＋ Nova chave**. Informe o nome (por exemplo, `Bot Instagram`), o **canal padrão** e o **responsável** que vai receber os Leads.
3. Copie a chave (começa com `sck_`). **Ela só é mostrada uma vez.** Se perder, crie outra e revogue a antiga.

Use uma chave para cada sistema. Assim dá para revogar só uma delas e ver o **último uso** de cada uma.

## 2. Endereço e cabeçalhos

```
POST https://sc2030.brbots.com/api/public/<empresa>/leads
Content-Type: application/json
X-SmartCRM-Key: sck_...
```

`<empresa>` é o identificador da empresa no endereço de login (por exemplo, `brbots`). A tela de captação mostra o endereço completo.

> Enquanto o servidor de homologação pedir usuário e senha (Apache), o bot também precisa enviar `Authorization: Basic ...` com esses dados. A chave do CRM vai sempre no cabeçalho `X-SmartCRM-Key`, nunca em `Authorization`.

## 3. Corpo (JSON, até 16 KB)

| Campo | Tipo | Observação |
|---|---|---|
| `name` | texto (até 120) | Nome da pessoa |
| `email` | texto (até 254) | Precisa ser um e-mail válido |
| `phone` | texto ou número (até 40) | |
| `company` | texto (até 160) | |
| `message` | texto (até 2000) | Fica no histórico de rastreio do Lead |
| `channel` | texto | Opcional; se ausente, usa o canal padrão da chave. Valores: `Site`, `Instagram`, `WhatsApp`, `Google Ads`, `Meta Ads`, `Busca orgânica`, `Redes sociais`, `E-mail`, `Indicação`, `Evento`, `Telefone`, `Outro` |
| `externalId` | texto (até 128) | ID da pessoa no sistema de origem (ex.: ID do usuário no Instagram). Evita Leads duplicados |
| `profileUrl` | texto (até 500) | Link do perfil |
| `campaign` | texto (até 120) | Nome da campanha |
| `utm` | objeto | `source`, `medium`, `campaign`, `term`, `content` (até 200 cada) |
| `pageUrl` | texto (até 1000) | Página onde o contato aconteceu |
| `referrer` | texto (até 1000) | Página anterior |

É obrigatório enviar **pelo menos um** destes: `name`, `email` ou `phone`. Campos desconhecidos são ignorados.

### Sem duplicar

Se já existir um Lead **em contato** com o mesmo `externalId` **no mesmo canal**, esse Lead é atualizado em vez de criar outro:

- os dados que estavam vazios são preenchidos;
- a mensagem entra no histórico;
- a data do último contato é atualizada.

O responsável recebe uma notificação nos dois casos.

## 4. Respostas

| Código | Significado |
|---|---|
| `201` | `{"leadId": "L-12", "status": "created"}` — Lead novo |
| `200` | `{"leadId": "L-12", "status": "updated"}` — Lead existente atualizado |
| `400` | JSON inválido |
| `401` | Chave ausente, inválida ou revogada |
| `404` | Empresa não encontrada |
| `413` | Corpo maior que 16 KB |
| `422` | Dados inválidos (`error.field` indica o campo) |
| `429` | Muitas requisições; respeite o cabeçalho `Retry-After` (segundos) |
| `503` | CRM temporariamente indisponível; tente de novo mais tarde |

**Limites de requisições:**

- 60 por minuto para cada chave;
- 120 por minuto para cada endereço IP;
- depois de 10 tentativas com chave errada em 10 minutos, o IP fica bloqueado temporariamente.

Em `429` e `503`, espere e reenvie. Usar o mesmo `externalId` no reenvio evita duplicar o Lead.

## 5. Exemplos

**curl**

```bash
curl -X POST https://sc2030.brbots.com/api/public/brbots/leads \
  -H "Content-Type: application/json" \
  -H "X-SmartCRM-Key: $SMARTCRM_KEY" \
  -d '{"name":"Maria Souza","phone":"(11) 99999-0000","externalId":"17841400000000000","profileUrl":"https://instagram.com/maria","message":"Quero um orçamento"}'
```

**Node.js (bot)**

```js
const response = await fetch('https://sc2030.brbots.com/api/public/brbots/leads', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-SmartCRM-Key': process.env.SMARTCRM_KEY },
  body: JSON.stringify({
    name: contato.nome,
    phone: contato.telefone,
    externalId: String(contato.instagramId),
    profileUrl: contato.perfil,
    message: contato.ultimaMensagem
  })
});
if (response.status === 429 || response.status >= 500) { /* aguarde e tente de novo */ }
const result = await response.json(); // { leadId, status }
```

**Python**

```python
import os, requests

response = requests.post(
    "https://sc2030.brbots.com/api/public/brbots/leads",
    headers={"X-SmartCRM-Key": os.environ["SMARTCRM_KEY"]},
    json={"name": "Maria Souza", "email": "maria@example.com", "channel": "Site",
          "utm": {"source": "google", "medium": "cpc", "campaign": "black-friday"}},
    timeout=10,
)
response.raise_for_status()
print(response.json())
```

## 6. Boas práticas

- **Guarde a chave só no servidor** do bot ou do site, em variável de ambiente. Nunca coloque a chave em código que roda no navegador (JavaScript de página, app mobile): quem a vir poderá criar Leads. Num formulário do site, envie primeiro para o seu servidor e ele chama o CRM.
- **Revogue a chave na hora** se ela vazar e crie outra.
- **Formulários do site:** leia os parâmetros `utm_source`, `utm_medium`, `utm_campaign`, `utm_term` e `utm_content` da URL de entrada e envie-os em `utm`. Envie também `pageUrl` e `referrer`, para saber qual anúncio ou página trouxe o Lead.
