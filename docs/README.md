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
- [Interface administrativa](#interface-administrativa)
- [Deploy em produção](#deploy-em-produção)
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
│       ex.: "9011" + "11999999999" → "901111999999999"│
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
│     · Context: call-api-playback                    │
│     · Variable: AUDIO_FILE={playback_ref}           │
│     · CallerID: {company.name} <0000>               │
└─────────────────────────────────────────────────────┘
        │ erro AMI → HTTP 502
        ▼
┌─────────────────────────────────────────────────────┐
│  7. Log de Acesso (JSON)                            │
│     · Grava em ACCESS_LOG_PATH                      │
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

### Dialplan Asterisk (`extensions_custom.conf`)

Quando o Asterisk recebe a chamada originada, executa:

```ini
[call-api-playback]
exten => s,1,NoOp(Call API Playback - file=${AUDIO_FILE})
 same => n,Answer()
 same => n,Wait(1)
 same => n,Playback(${AUDIO_FILE})
 same => n,Hangup()
```

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

### `GET /health`

Retorna `{"status": "ok"}` — usado por monitores e balanceadores.

### `GET /docs`

Swagger UI interativo com todos os endpoints documentados.

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

**Formato obrigatório:** WAV mono, 8 kHz, 16-bit.

---

## Interface administrativa

Acessível em `/adminAPI/` (somente rede interna — bloqueada pelo Apache para IPs externos).

| Seção | Funcionalidade |
|---|---|
| Dashboard | Contadores: clientes ativos, tokens ativos, chamadas nas últimas 24h |
| Clientes | CRUD de clientes com `dial_prefix` |
| Detalhe do cliente | Geração e revogação de Bearer Tokens |
| Detalhe do cliente | CRUD de empresas autorizadas |
| Logs | Visualização paginada do log de acesso JSON |

**Acesso pela rede interna:**  
`http://10.1.1.50/adminAPI/`

**Acesso via SSH tunnel (fora da rede):**
```bash
ssh -L 9000:localhost:8000 root@10.1.1.50
# Depois: http://localhost:9000/adminAPI/
```

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
ssh root@10.1.1.50 "systemctl restart call-api"
```

### Adicionar gravações

Copie arquivos WAV (8 kHz, mono) para:
```
/var/lib/asterisk/sounds/custom/{client_id}/nome_arquivo.wav
```

O `client_id` é o ID numérico do cliente cadastrado no painel admin.

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
│   ├── call-api.service      # Unit systemd
│   └── call-api.apache.conf  # Config proxy Apache (FreePBX)
├── docs/
│   ├── README.md        # Este arquivo
│   └── ROADMAP.md       # Plano de desenvolvimento e fases
├── scripts/
│   └── migrate_yaml_to_db.py # Migração YAML → SQLite (uso único)
├── tests/
│   ├── conftest.py      # Fixtures pytest
│   ├── test_auth.py     # Testes de autenticação
│   ├── test_call.py     # Testes do endpoint /api/v1/call
│   ├── test_phone.py    # Testes de validação de número
│   └── test_audio.py    # Testes de resolução de áudio
├── env.example          # Exemplo de variáveis de ambiente
└── requirements.txt     # Dependências Python
```
