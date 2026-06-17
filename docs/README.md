# asterisk-api-call

API REST para originação de chamadas telefônicas via Asterisk/FreePBX, com reprodução de gravações de áudio e interface administrativa web.

---

## Sumário

- [Visão geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Fluxo de uma chamada](#fluxo-de-uma-chamada)
- [Modelo de dados](#modelo-de-dados)
- [Endpoints da API](#endpoints-da-api)
- [Autenticação](#autenticação)
- [Configuração](#configuração)
- [Configuração Asterisk / FreePBX](#configuração-asterisk--freepbx)
- [Interface administrativa](#interface-administrativa)
- [Deploy em produção](#deploy-em-produção)
- [Troubleshooting](#troubleshooting)
- [Estrutura de arquivos](#estrutura-de-arquivos)

---

## Visão geral

O sistema permite que sistemas externos (CRM, ERPs, automações) originem chamadas telefônicas enviando uma simples requisição HTTP. A API valida as credenciais, o número de destino e o arquivo de áudio, e então instrui o Asterisk a realizar a ligação e reproduzir uma gravação para o destinatário.

**Tecnologias principais:**

| Camada | Tecnologia |
|---|---|
| API | FastAPI (Python 3.11) |
| PBX | Asterisk 22 / FreePBX (Debian 12) |
| Protocolo PBX | AMI — Asterisk Manager Interface (`panoramisk`) |
| Banco de dados | SQLite + SQLAlchemy 2 |
| Interface admin | Jinja2 + Bootstrap 5 |
| Servidor ASGI | Uvicorn |
| Proxy reverso | Apache2 (FreePBX) ← NGINX Proxy Manager |

---

## Arquitetura

```
┌─────────────────────────────────────────────────────┐
│                    Internet                         │
└────────────────────┬────────────────────────────────┘
                     │ HTTPS
                     ▼
┌─────────────────────────────────────────────────────┐
│          NGINX Proxy Manager (servidor externo)     │
│  Termina TLS · Injeta X-Forwarded-For / Proto       │
└────────────────────┬────────────────────────────────┘
                     │ HTTP (rede interna)
                     ▼
┌─────────────────────────────────────────────────────┐
│                 Servidor FreePBX  10.1.1.50          │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  Apache 2  :80                               │   │
│  │  /api/v1, /health, /docs → :8000 (proxy)    │   │
│  │  /adminAPI               → :8000 (interno)  │   │
│  │  /admin                  → FreePBX UI       │   │
│  └────────────────────┬─────────────────────────┘  │
│                        │ ProxyPass                  │
│                        ▼                            │
│  ┌──────────────────────────────────────────────┐   │
│  │  Uvicorn  127.0.0.1:8000                     │   │
│  │  ┌────────────────────────────────────────┐  │   │
│  │  │  FastAPI app                           │  │   │
│  │  │  · Bearer auth (SQLite)                │  │   │
│  │  │  · Rate limiting (in-memory)           │  │   │
│  │  │  · Phone validation (E.164 BR)         │  │   │
│  │  │  · Audio resolution (WAV 8kHz)         │  │   │
│  │  │  · AMI client (panoramisk)             │  │   │
│  │  │  · Admin GUI (/adminAPI)               │  │   │
│  │  └───────────────────┬────────────────────┘  │   │
│  └──────────────────────┼──────────────────────┘   │
│                         │ TCP socket               │
│                         ▼                          │
│  ┌──────────────────────────────────────────────┐   │
│  │  Asterisk  AMI  127.0.0.1:5038               │   │
│  │  Usuário AMI: callapi                        │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  /var/lib/asterisk/sounds/custom/{client_id}/*.wav   │
└─────────────────────────────────────────────────────┘
```

---

## Fluxo de uma chamada

```
Cliente HTTP (CRM/sistema externo)
        │
        │  POST /api/v1/call
        │  Authorization: Bearer <token>
        │  {
        │    "to_number": "+5511999999999",
        │    "company_id": "empresa_abc",
        │    "audio_source": {
        │      "type": "recording",
        │      "content": "aviso_feriado"
        │    }
        │  }
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  1. Autenticação do Bearer Token                    │
│     · Hash SHA-256 do token bruto                   │
│     · Consulta SQLite: token ativo, não expirado    │
│     · Verifica se o Client pai está ativo           │
└─────────────────────────────────────────────────────┘
        │ token inválido → HTTP 401
        │ cliente inativo → HTTP 401
        ▼
┌─────────────────────────────────────────────────────┐
│  2. Rate Limiting (in-memory por token_id)          │
│     · Janela deslizante de 60 segundos              │
│     · Limite: calls_per_minute (configurado p/token)│
└─────────────────────────────────────────────────────┘
        │ limite excedido → HTTP 429
        ▼
┌─────────────────────────────────────────────────────┐
│  3. Autorização da Empresa                          │
│     · company_id deve existir no mesmo Client       │
│       do token (multi-tenancy)                      │
│     · Empresa deve estar ativa                      │
└─────────────────────────────────────────────────────┘
        │ empresa não encontrada/inativa → HTTP 403
        ▼
┌─────────────────────────────────────────────────────┐
│  4. Validação do Número de Telefone                 │
│     · Normaliza para dígitos puros                  │
│     · Valida formato E.164 Brasil (CC 55)           │
│     · Monta dial_string:                            │
│       {dial_prefix}{national_number}                │
│       ex.: "2002" + "61993798382" → "2002619937938382"│
└─────────────────────────────────────────────────────┘
        │ número inválido → HTTP 400
        ▼
┌─────────────────────────────────────────────────────┐
│  5. Resolução do Áudio                              │
│     · type=recording: verifica existência do WAV    │
│       em: {SOUNDS_BASE_DIR}/{RECORDINGS_BASE_PATH}/ │
│           {client_id}/{content}.wav                 │
│     · Retorna o playback_ref para o Asterisk        │
│     · type=tts: HTTP 501 (previsto para Fase 4)     │
└─────────────────────────────────────────────────────┘
        │ arquivo não encontrado → HTTP 400
        │ TTS → HTTP 501
        ▼
┌─────────────────────────────────────────────────────┐
│  6. Originação via AMI                              │
│     · Action: Originate (Async)                     │
│     · Channel: Local/{dial_string}@from-internal    │
│     · Context: call-api-playback / Exten: s         │
│     · Variable: __AUDIO_FILE e AUDIO_FILE={ref}     │
│     · CallerID: {company.name} <0000>               │
└─────────────────────────────────────────────────────┘
        │ erro AMI → HTTP 502
        ▼
┌─────────────────────────────────────────────────────┐
│  6b. No Asterisk (após HTTP 202)                    │
│     · Perna Local ;2: disca via from-internal       │
│       (FreePBX roteia pelo dial_prefix → tronco)  │
│     · Quando o destino ATENDE: perna ;1 entra em    │
│       call-api-playback e executa Playback()        │
│     · Se ninguém atender: hangup cause 19, sem áudio│
└─────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  7. Log de Acesso (JSON)                            │
│     · Grava em ACCESS_LOG_PATH                      │
│     · IP real extraído de X-Forwarded-For           │
│       (injeta pelo NGINX Proxy Manager)             │
│     · Campos: ts, client_ip, client_id,             │
│       token_label, company_id, to_number,           │
│       dial_string, ami_result, uniqueid, call_id    │
└─────────────────────────────────────────────────────┘
        │
        ▼
  HTTP 202 Accepted
  {
    "status": "queued",
    "call_id": "<uuid>",
    "uniqueid": "<asterisk-uniqueid>",
    "message": "Chamada encaminhada ao Asterisk."
  }
```

### Dialplan Asterisk (`call-api-playback`)

Quando o destino **atende** a ligação originada, a perna `Local/...;1` executa o contexto abaixo e reproduz o áudio para quem atendeu:

```ini
[call-api-playback]
exten => s,1,NoOp(Call API Playback - file=${AUDIO_FILE})
 same => n,Answer()
 same => n,Wait(1)
 same => n,Playback(${AUDIO_FILE})
 same => n,Hangup()
```

> **HTTP 202 ≠ chamada completada.** A API retorna `202 Accepted` assim que o Asterisk enfileira o Originate. O `uniqueid` pode vir vazio em originações assíncronas. A reprodução do áudio só ocorre após o atendimento no telefone de destino.

Referência completa em [`deploy/extensions_call-api.conf`](../deploy/extensions_call-api.conf).

---

## Modelo de dados

```
Client
├── id          INTEGER PK
├── name        TEXT
├── dial_prefix TEXT(4)   ← prefixo da rota de saída FreePBX
├── active      BOOLEAN
└── created_at  DATETIME

ClientToken
├── id               INTEGER PK
├── client_id        FK → Client
├── token_hash       TEXT UNIQUE  ← SHA-256 do token bruto
├── label            TEXT
├── active           BOOLEAN
├── calls_per_minute INTEGER
├── expires_at       DATETIME (nullable)
└── last_used_at     DATETIME

Company
├── id         INTEGER PK
├── client_id  FK → Client
├── company_id TEXT UNIQUE por client ← usado no payload da API
├── name       TEXT
└── active     BOOLEAN
```

**Hierarquia multi-tenant:**  
`Client` → possui `ClientToken`(s) e `Company`(s). Um token só pode usar `company_id` que pertença ao mesmo `Client`.

---

## Endpoints da API

### `POST /api/v1/call`

Origina uma chamada com reprodução de gravação.

**Headers obrigatórios:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Body:**
```json
{
  "to_number": "+5511999999999",
  "company_id": "empresa_abc",
  "audio_source": {
    "type": "recording",
    "content": "nome_do_arquivo_sem_extensao"
  }
}
```

**Respostas:**

| HTTP | Significado |
|---|---|
| 202 | Chamada aceita e encaminhada ao Asterisk |
| 400 | Número inválido ou arquivo de gravação não encontrado |
| 401 | Token ausente, inválido, expirado ou cliente inativo |
| 403 | Empresa não pertence ao cliente do token |
| 429 | Rate limit excedido |
| 501 | TTS solicitado (não implementado ainda) |
| 502 | Erro na comunicação com o AMI |
| 503 | AMI não configurado |

**Resposta 202 (exemplo):**

```json
{
  "status": "queued",
  "call_id": "12c99d67-6eef-44cf-812d-2b8aa644a42d",
  "uniqueid": "",
  "message": "Chamada encaminhada ao Asterisk."
}
```

O campo `uniqueid` pode vir vazio quando o Originate é assíncrono — isso não indica falha. Confirme o andamento nos logs do Asterisk ou atenda o telefone de destino.

### `GET /health`

Retorna `{"status": "ok"}` — usado por monitores e balanceadores.

### `GET /docs`

Swagger UI interativo com os endpoints **públicos** da API.  
As rotas do painel administrativo (`/adminAPI/*`) são excluídas do schema OpenAPI e não aparecem na documentação pública.

---

## Autenticação

Os tokens são gerados pelo painel administrativo (`/adminAPI`). O valor bruto do token é exibido **uma única vez** no momento da criação — não é armazenado, apenas seu hash SHA-256.

**Formato no header:**
```
Authorization: Bearer 4a7f3c1e9b2d...  (64 hex chars)
```

---

## Configuração

Variáveis de ambiente carregadas de `/etc/call-api/environment` (produção) ou `.env` (desenvolvimento):

| Variável | Padrão | Descrição |
|---|---|---|
| `DB_PATH` | `call_api.db` | Caminho do banco SQLite |
| `ACCESS_LOG_PATH` | `logs/access.log` | Log de acesso JSON |
| `AMI_HOST` | `127.0.0.1` | Host do AMI do Asterisk |
| `AMI_PORT` | `5038` | Porta do AMI |
| `AMI_USER` | — | Usuário AMI (`manager_custom.conf`) |
| `AMI_SECRET` | — | Senha do usuário AMI |
| `AMI_CONTEXT` | `call-api-playback` | Contexto do dialplan |
| `AMI_ORIGINATE_TIMEOUT_MS` | `30000` | Timeout da originação (ms) |
| `SOUNDS_BASE_DIR` | `/var/lib/asterisk/sounds` | Raiz dos sons do Asterisk |
| `RECORDINGS_BASE_PATH` | `custom` | Sub-caminho das gravações |
| `ADMIN_USER` | `admin` | Usuário do painel web |
| `ADMIN_PASSWORD` | — | Senha do painel web |
| `ADMIN_SECRET_KEY` | — | Chave de assinatura de sessão |

**Caminho das gravações:**  
`{SOUNDS_BASE_DIR}/{RECORDINGS_BASE_PATH}/{client_id}/{content}.wav`  
Exemplo: `/var/lib/asterisk/sounds/custom/1/aviso_feriado.wav`

O `{client_id}` é o **ID numérico do Cliente** no painel admin — **não** confundir com o `company_id` enviado no JSON da API.

**Formato obrigatório:** WAV mono, 8 kHz, 16-bit.

---

## Configuração Asterisk / FreePBX

### Usuário AMI

Em **Admin → Asterisk Manager Users**, crie um usuário (ex.: `call-api`) com permissões de leitura e escrita em **System**, **Call** e **Originate**. Configure `AMI_USER` e `AMI_SECRET` em `/etc/call-api/environment`.

### Dialplan customizado

Instale o contexto `call-api-playback` em `/etc/asterisk/extensions_custom.conf`:

```bash
# Copie o arquivo de referência do repositório
cp /opt/call-api/deploy/extensions_call-api.conf /etc/asterisk/extensions_custom.conf

# Valide e recarregue
asterisk -rx 'dialplan show call-api-playback'
asterisk -rx 'dialplan reload'
```

A saída de `dialplan show` **deve** exibir `Playback(${AUDIO_FILE})`. Se aparecer `Playback()` vazio, as variáveis foram removidas — veja [Troubleshooting](#troubleshooting).

> **Atenção:** não cole o bloco `[call-api-playback]` pela UI do FreePBX (módulo Custom Extensions). O painel costuma **remover** `${AUDIO_FILE}`, deixando `Playback()` sem argumento. Edite sempre o arquivo diretamente no servidor.

### Rota de saída

O `dial_prefix` do Cliente (4 dígitos) deve coincidir com o prefixo da **rota de saída** configurada no FreePBX. Ex.: prefixo `2002` → discagem `2002` + número nacional → tronco correspondente.

---

## Interface administrativa

Acessível em `/adminAPI/` — **não aparece no `/docs` público** (`include_in_schema=False`) e é bloqueada pelo Apache para IPs externos à rede interna.

| Seção | Funcionalidade |
|---|---|
| Dashboard | Contadores: clientes ativos, tokens ativos, chamadas nas últimas 24h |
| Clientes | CRUD de clientes com `dial_prefix` |
| Detalhe do cliente | Geração e revogação de Bearer Tokens |
| Detalhe do cliente | CRUD de empresas autorizadas (criar, editar, excluir, ativar/desativar) |
| Detalhe do cliente | Listagem das gravações WAV disponíveis (`custom/{client_id}/`) |
| Empresas | Upload de múltiplos arquivos WAV (convertidos para mono 8 kHz 16-bit) |
| Clientes | Criação automática da pasta `custom/{client_id}/` ao salvar novo cliente |
| Logs | Visualização paginada do log de acesso JSON |

**Acesso pela rede interna:**  
`http://10.1.1.50/adminAPI/`

**Acesso via SSH tunnel (fora da rede):**
```bash
ssh -L 9000:localhost:8000 root@10.1.1.50
# Depois: http://localhost:9000/adminAPI/
```

> **Segurança do cookie de sessão:** quando a requisição chega via HTTPS (header `X-Forwarded-Proto: https` injetado pelo NPM), o cookie de sessão recebe automaticamente o atributo `Secure`, impedindo transmissão em HTTP.

---

## Segurança e proxy reverso

A API foi projetada para operar atrás de um proxy reverso (NGINX Proxy Manager → Apache). Comportamentos específicos para esse cenário:

| Aspecto | Comportamento |
|---|---|
| **IP real do chamador** | Lido do header `X-Forwarded-For` injetado pelo NPM; registrado em todos os logs de acesso |
| **Cookie de sessão admin** | Recebe `Secure=True` automaticamente quando `X-Forwarded-Proto: https` está presente |
| **Documentação pública (`/docs`)** | Exibe apenas endpoints da API (`/api/v1/*`, `/health`); rotas `/adminAPI/*` são excluídas do schema OpenAPI |
| **Painel admin (`/adminAPI`)** | Bloqueado pelo Apache para IPs externos; acessível apenas na rede interna (10.x, 192.168.x, 172.16.x) |
| **AMI** | Escuta exclusivamente em `127.0.0.1:5038`; nunca exposto à rede |

---

## Deploy em produção

### Serviço systemd

```
/etc/systemd/system/call-api.service
```

```bash
systemctl status call-api    # verificar estado
systemctl restart call-api   # reiniciar após atualizações
journalctl -u call-api -f    # acompanhar logs em tempo real
```

### Atualizar o código

```bash
# Na máquina de desenvolvimento
pscp -r app/ root@10.1.1.50:/opt/call-api/app/
pscp deploy/extensions_call-api.conf root@10.1.1.50:/opt/call-api/deploy/
ssh root@10.1.1.50 "systemctl restart call-api"
```

Se o dialplan também foi alterado no repositório, copie e recarregue:

```bash
ssh root@10.1.1.50 "cp /opt/call-api/deploy/extensions_call-api.conf /etc/asterisk/extensions_custom.conf && asterisk -rx 'dialplan reload'"
```

### Instalar / atualizar o dialplan

```bash
cp /opt/call-api/deploy/extensions_call-api.conf /etc/asterisk/extensions_custom.conf
asterisk -rx 'dialplan reload'
```

### Adicionar gravações

**Via painel admin (recomendado):** ao cadastrar ou editar uma empresa, envie um ou mais arquivos WAV. O sistema converte automaticamente para **mono 8 kHz 16-bit** (requer `ffmpeg` instalado no servidor) e salva em:

```
/var/lib/asterisk/sounds/custom/{client_id}/nome_arquivo.wav
```

**Manualmente no servidor:** copie arquivos WAV (8 kHz, mono) para o mesmo caminho acima.

O `{client_id}` é o ID numérico do **Cliente** cadastrado no painel admin (coluna `id`, não o `company_id`).

Use o nome do arquivo **sem extensão** como `audio_source.content` na API (ex.: `boas_vindas.wav` → `"content": "boas_vindas"`).

**Dependência de sistema:** `ffmpeg` (`apt install ffmpeg` no Debian/FreePBX).

**Permissões da pasta de gravações:**

```bash
mkdir -p /var/lib/asterisk/sounds/custom
chown -R call-api:asterisk /var/lib/asterisk/sounds/custom
chmod 775 /var/lib/asterisk/sounds/custom
```

O usuário do serviço `call-api` precisa de permissão de escrita; o Asterisk precisa de leitura nos arquivos `.wav`.

---

## Troubleshooting

### API retorna 202, mas o telefone não toca ou não reproduz áudio

| Sintoma | Causa provável | O que verificar |
|---|---|---|
| Telefone não toca | Rota de saída / tronco / prefixo | `dial_prefix` do cliente vs rota FreePBX; log: `Dial(PJSIP/...@tronco)` |
| Toca, mas sem áudio | Destino não atendeu | Hangup cause **19** (no answer) — atenda a ligação para ouvir o playback |
| Toca e atende, sem áudio | Dialplan quebrado | `asterisk -rx 'dialplan show call-api-playback'` — deve ter `Playback(${AUDIO_FILE})` |
| HTTP 400 `recording_not_found` | WAV no caminho errado | Arquivo em `custom/{client_id}/`, não `custom/{company_id}/` |
| HTTP 403 | Empresa errada | `company_id` do JSON deve existir no mesmo Cliente do token |
| HTTP 502 `ami_error` | AMI indisponível ou credenciais | `journalctl -u call-api -f`; testar usuário AMI no FreePBX |

### Comandos úteis no servidor FreePBX

```bash
# Logs da API
journalctl -u call-api -f
tail -f /var/log/call-api/access.log

# Logs do Asterisk (filtrar chamadas da API)
tail -f /var/log/asterisk/full | grep -iE 'call-api-playback|Playback|Local/2002'

# Validar dialplan e arquivo de áudio
asterisk -rx 'dialplan show call-api-playback'
file /var/lib/asterisk/sounds/custom/1/seu_arquivo.wav
soxi /var/lib/asterisk/sounds/custom/1/seu_arquivo.wav
```

### Dialplan com `Playback()` vazio

Se `extensions_custom.conf` contiver `Playback()` sem `${AUDIO_FILE}`, restaure a partir de `deploy/extensions_call-api.conf` e recarregue o dialplan. Esse problema ocorre quando o bloco é editado pelo painel web do FreePBX.

---

## Estrutura de arquivos

```
asterisk-api-call/
├── app/
│   ├── main.py          # Aplicação FastAPI, lifespan, endpoint /api/v1/call
│   ├── admin.py         # Painel administrativo (/adminAPI)
│   ├── config.py        # Configurações via variáveis de ambiente
│   ├── models.py        # Modelos SQLAlchemy (Client, ClientToken, Company)
│   ├── database.py      # Engine e sessão SQLite
│   ├── crud.py          # Operações CRUD e estatísticas
│   ├── schemas.py       # Modelos Pydantic (request/response)
│   ├── deps.py          # Dependências FastAPI (DB, AMI, settings)
│   ├── ami.py           # Cliente AMI via panoramisk
│   ├── audio.py         # Resolução e validação de arquivos de áudio
│   ├── phone.py         # Validação e normalização E.164 Brasil
│   ├── rate_limit.py    # Rate limiting in-memory por token
│   ├── access_log.py    # Log de acesso JSON
│   └── templates/       # Templates Jinja2 (Bootstrap 5)
├── deploy/
│   ├── call-api.service           # Unit systemd
│   ├── call-api.apache.conf       # Config proxy Apache (FreePBX)
│   └── extensions_call-api.conf   # Dialplan call-api-playback (Asterisk)
├── docs/
│   ├── README.md        # Este arquivo
│   └── ROADMAP.md       # Plano de desenvolvimento e fases
├── scripts/
│   └── migrate_yaml_to_db.py # Migração YAML → SQLite (uso único)
├── tests/
│   ├── conftest.py      # Fixtures pytest
│   ├── test_auth.py     # Testes de autenticação
│   ├── test_call.py     # Testes do endpoint /api/v1/call
│   ├── test_ami.py      # Testes do cliente AMI (resposta async)
│   ├── test_phone.py    # Testes de validação de número
│   └── test_audio.py    # Testes de resolução de áudio
├── env.example          # Exemplo de variáveis de ambiente
└── requirements.txt     # Dependências Python
```
