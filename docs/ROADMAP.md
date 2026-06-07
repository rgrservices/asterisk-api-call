# Roadmap de Desenvolvimento — asterisk-api-call

**Cliente:** Niva Tecnologia · **Proposta:** 0002-26 · **Valor:** R$ 7.500  
**Ambiente:** FreePBX 17.0.28 / Debian 12 / Asterisk 20-21 / AMI v3  
**PRD de referência:** `PRD_ API de Originação Híbrida (TTS e Gravações).pdf`

---

## Resumo de fases

| Fase | Descrição | Status |
|---|---|---|
| 1 | MVP: validação de token, empresa e número | ✅ Concluída |
| 2 | BD + AMI + Gravação (recording) | ✅ Concluída |
| 3 | Interface administrativa (GUI web) | ✅ Concluída |
| 4 | TTS (Text-to-Speech) | 🔜 Prevista |

---

## Fase 1 — MVP / Validação ✅

**Entregável:** validação end-to-end sem discagem real.

- Endpoint `POST /api/v1/call` com Bearer Token
- Autenticação via YAML (tokens + empresas como arquivos separados)
- Validação de número E.164 (somente Brasil, CC 55)
- Geração de `dial_string = {dial_prefix}{national_number}`
- Log de acesso JSON em `access.log`
- Deploy via systemd

**Arquivos:** `app/main.py`, `app/schemas.py`, `app/phone.py`, `app/registry.py`, `app/access_log.py`

---

## Fase 2 — BD + AMI + Gravação ✅

**Entregável:** chamadas reais originadas via AMI com arquivo de áudio WAV.

### 2a — Banco de dados + modelo multi-tenant

Substituição dos YAMLs por SQLite com hierarquia:

```
Client (id, name, dial_prefix, active)
  └── ClientToken (token_hash, label, active, expires_at, calls_per_minute)
  └── Company (company_id, name, active)
```

**Regra central:** um token só pode usar `company_id` do mesmo cliente.

**Novos arquivos:** `app/models.py`, `app/database.py`, `app/crud.py`, `scripts/migrate_yaml_to_db.py`

### 2b — Integração AMI (panoramisk)

- Conexão persistente ao AMI do FreePBX (127.0.0.1:5038)
- AMI Action `Originate` com:
  - `Channel: Local/{dial_string}@from-internal`
  - `Context: call-api-playback` (contexto no `extensions_custom.conf`)
  - `Variable: AUDIO_FILE={playback_ref}`
  - `Async: true`
- O FreePBX roteia pelo tronco correto via `dial_prefix` na rota de saída

**Pré-requisito no servidor FreePBX** — adicionar em `/etc/asterisk/extensions_custom.conf`:
```ini
[call-api-playback]
exten => s,1,NoOp(Call API - ${AUDIO_FILE})
 same => n,Answer()
 same => n,Wait(1)
 same => n,Playback(${AUDIO_FILE})
 same => n,Hangup()
```

**Novo arquivo:** `app/ami.py`

### 2c — Resolução de gravações (`recording`)

- `content` no JSON = nome do arquivo WAV (sem extensão)
- Caminho: `/var/lib/asterisk/sounds/{RECORDINGS_BASE_PATH}/{client_id}/{content}.wav`
- Formato: **WAV 8 kHz mono** (padrão Asterisk)
- Referência passada ao Asterisk (sem extensão): `{RECORDINGS_BASE_PATH}/{client_id}/{content}`
- `type: tts` retorna HTTP 501 (reservado Fase 4)

**Novo arquivo:** `app/audio.py`

### Mudanças na API (Fase 2)

| Cenário | HTTP antes | HTTP agora |
|---|---|---|
| Token inválido/ausente | 401 | 401 `invalid_token` |
| Empresa de outro cliente | 401 | **403** `company_not_authorized` |
| Token expirado | — | 401 `token_expired` |
| Token revogado | — | 401 `token_revoked` |
| Rate limit excedido | — | 429 |
| Gravação não encontrada | — | 400 `recording_not_found` |
| TTS | — | 501 `tts_not_implemented` |
| AMI indisponível | — | 502 `ami_error` |
| AMI não configurado | — | 503 `ami_not_configured` |
| Chamada aceita | 200 | **202 Accepted** |

---

## Fase 3 — Interface administrativa ✅

**Entregável:** painel web para gestão de clientes, tokens e empresas.

**Tecnologia:** Jinja2 + Bootstrap 5 (CDN), servido pelo FastAPI em `/admin/*`  
**Autenticação:** login com usuário/senha (`ADMIN_USER`, `ADMIN_PASSWORD`); cookie assinado com `itsdangerous`

### Páginas

| URL | Função |
|---|---|
| `/admin/login` | Login |
| `/admin/` | Dashboard: contadores e ações rápidas |
| `/admin/clients` | Lista de clientes |
| `/admin/clients/new` | Criar cliente |
| `/admin/clients/{id}` | Detalhe: tokens + empresas |
| `/admin/clients/{id}/edit` | Editar cliente |
| `/admin/clients/{id}/tokens/generate` | Gerar token (exibido uma única vez) |
| `/admin/clients/{id}/tokens/{tid}/revoke` | Revogar token |
| `/admin/clients/{id}/companies/new` | Adicionar empresa |
| `/admin/clients/{id}/companies/{pk}/toggle` | Ativar/desativar empresa |
| `/admin/logs` | Últimas 500 entradas do access.log |

**Novos arquivos:** `app/admin.py`, `app/templates/`

---

## Fase 4 — TTS (prevista) 🔜

> Corresponde à "Fase 2 do produto" mencionada pelo cliente Niva.

**Escopo a definir:**
- Engine TTS: `gTTS` (requer internet) ou `Coqui TTS` / `festival` (offline)
- `content` = texto pt-BR puro (máximo de caracteres a definir)
- Geração de WAV 8 kHz mono em `/tmp/call-api/tts_{call_id}.wav`
- Limpeza do arquivo temporário após a chamada
- O contexto `call-api-playback` no FreePBX já suporta TTS (usa `AUDIO_FILE`)
- Adicionar `TTS_ENGINE` em `app/config.py`

**Arquivo a criar:** lógica TTS em `app/audio.py` (stub já existe com HTTP 501)

---

## Configurações de produção

### Variáveis de ambiente (`.env`)

```env
DB_PATH=/opt/call-api/call_api.db
ACCESS_LOG_PATH=/var/log/call-api/access.log
AMI_HOST=127.0.0.1
AMI_PORT=5038
AMI_USER=call-api
AMI_SECRET=<senha-ami>
AMI_ORIGINATE_TIMEOUT_MS=30000
AMI_CONTEXT=call-api-playback
SOUNDS_BASE_DIR=/var/lib/asterisk/sounds
RECORDINGS_BASE_PATH=custom
ADMIN_USER=admin
ADMIN_PASSWORD=<senha-admin>
ADMIN_SECRET_KEY=<openssl rand -hex 32>
```

### Estrutura de diretórios de gravações

```
/var/lib/asterisk/sounds/custom/
└── {client_id}/          ← ID numérico do cliente no DB
    ├── boas_vindas.wav
    ├── aviso_feriado.wav
    └── confirmacao.wav
```

### Configuração AMI no FreePBX

Em **Admin → Asterisk Manager Users**, criar usuário `call-api` com permissões:
- `read`: System, Call, Originate
- `write`: System, Call, Originate

---

## Migração de instalação existente (YAML → SQLite)

```bash
cd /opt/call-api
source .venv/bin/activate
python scripts/migrate_yaml_to_db.py \
  --db call_api.db \
  --tokens /etc/call-api/tokens.yaml \
  --companies /etc/call-api/companies.yaml
```
