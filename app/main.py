from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app import crud
from app.access_log import setup_access_logging, write_access_record
from app.ami import AmiClient
from app.audio import resolve_audio
from app.config import get_settings
from app.crud import hash_token
from app.database import create_db_engine, create_session_factory, init_db
from app.deps import get_ami, get_app_settings, get_db
from app.phone import normalize_e164_input, to_trunk_dial_string, validate_e164
from app.rate_limit import is_allowed
from app.schemas import CallAccepted, CallRequest

security = HTTPBearer(auto_error=False)


# ─── Auth result ──────────────────────────────────────────────────────────────

@dataclass
class AuthResult:
    token_id: int
    client_id: int
    dial_prefix: str
    token_label: str
    calls_per_minute: int


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_access_logging(settings.access_log_path)

    engine = create_db_engine(str(settings.db_path))
    init_db(engine)
    session_factory = create_session_factory(engine)

    ami = AmiClient(
        host=settings.ami_host,
        port=settings.ami_port,
        username=settings.ami_user,
        secret=settings.ami_secret,
        context=settings.ami_context,
        timeout_ms=settings.ami_originate_timeout_ms,
    )

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.ami = ami

    yield

    await ami.close()
    engine.dispose()


# ─── Application ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Call origination API",
    description=(
        "API para originação de chamadas via Asterisk/FreePBX. "
        "Suporta gravações de áudio (WAV 8 kHz). "
        "TTS previsto para versão futura."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

# Admin UI
from app.admin import router as admin_router  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from app.admin import AdminAuthMiddleware  # noqa: E402

app.add_middleware(AdminAuthMiddleware)
app.include_router(admin_router)


# ─── Exception handlers ───────────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


# ─── Bearer auth dependency ───────────────────────────────────────────────────

def require_bearer(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[Session, Depends(get_db)],
) -> AuthResult:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(status_code=401, detail="missing_or_invalid_authorization")

    raw_token = creds.credentials
    token_entry = crud.get_token_by_hash(db, hash_token(raw_token))

    if token_entry is None:
        raise HTTPException(status_code=401, detail="invalid_token")

    if not token_entry.active:
        raise HTTPException(status_code=401, detail="token_revoked")

    now = datetime.now(UTC)
    if token_entry.expires_at is not None:
        exp = token_entry.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if exp < now:
            raise HTTPException(status_code=401, detail="token_expired")

    if not token_entry.client.active:
        raise HTTPException(status_code=401, detail="client_inactive")

    crud.touch_token(db, token_entry)

    return AuthResult(
        token_id=token_entry.id,
        client_id=token_entry.client_id,
        dial_prefix=token_entry.client.dial_prefix,
        token_label=token_entry.label,
        calls_per_minute=token_entry.calls_per_minute,
    )


# ─── Routes ───────────────────────────────────────────────────────────────────

def _real_ip(request: Request) -> str:
    """Retorna o IP real do cliente respeitando X-Forwarded-For do reverse proxy."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/health", tags=["Sistema"])
def health():
    return {"status": "ok"}


@app.post(
    "/api/v1/call",
    response_model=CallAccepted,
    status_code=202,
    tags=["Chamadas"],
    summary="Originar chamada",
    description=(
        "Valida Bearer token, empresa e número E.164 (Brasil). "
        "Resolve o arquivo de gravação e origina a chamada via AMI. "
        "Retorna 202 Accepted com o call_id e uniqueid do Asterisk."
    ),
    responses={
        202: {"description": "Chamada encaminhada ao Asterisk"},
        400: {"description": "Parâmetros inválidos ou gravação não encontrada"},
        401: {"description": "Token inválido, expirado ou revogado"},
        403: {"description": "Empresa não pertence a este cliente"},
        429: {"description": "Rate limit excedido"},
        501: {"description": "TTS não implementado nesta versão"},
        502: {"description": "Erro ao comunicar com o AMI"},
        503: {"description": "AMI não configurado"},
    },
)
async def originate_call(
    request: Request,
    body: CallRequest,
    auth: Annotated[AuthResult, Depends(require_bearer)],
    db: Annotated[Session, Depends(get_db)],
    ami: Annotated[AmiClient, Depends(get_ami)],
    settings=Depends(get_app_settings),
):
    client_ip = _real_ip(request)

    # Verificar AMI configurado
    if not ami.configured:
        raise HTTPException(status_code=503, detail="ami_not_configured")

    # Rate limit
    if not is_allowed(auth.token_id, auth.calls_per_minute):
        write_access_record(
            client_ip=client_ip,
            client_id=auth.client_id,
            token_label=auth.token_label,
            company_id=body.company_id,
            to_number=body.to_number,
            ami_result="rate_limited",
            uniqueid="",
            error="rate_limit_exceeded",
        )
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")

    # Autorização da empresa (deve pertencer ao mesmo cliente do token)
    company = crud.get_company_by_ids(db, body.company_id, auth.client_id)
    if company is None or not company.active:
        write_access_record(
            client_ip=client_ip,
            client_id=auth.client_id,
            token_label=auth.token_label,
            company_id=body.company_id,
            to_number=body.to_number,
            ami_result="N/A",
            uniqueid="",
            error="company_not_authorized",
        )
        raise HTTPException(status_code=403, detail="company_not_authorized")

    # Validação do número de telefone
    try:
        digits = normalize_e164_input(body.to_number)
        validate_e164(digits)
        dial_string = to_trunk_dial_string(digits, auth.dial_prefix)
    except ValueError as exc:
        write_access_record(
            client_ip=client_ip,
            client_id=auth.client_id,
            token_label=auth.token_label,
            company_id=body.company_id,
            to_number=body.to_number,
            ami_result="N/A",
            uniqueid="",
            error="validation_error",
            error_detail=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Resolução do áudio
    try:
        playback_ref = resolve_audio(
            body.audio_source,
            auth.client_id,
            settings.sounds_base_dir,
            settings.recordings_base_path,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        write_access_record(
            client_ip=client_ip,
            client_id=auth.client_id,
            token_label=auth.token_label,
            company_id=body.company_id,
            to_number=body.to_number,
            dial_string=dial_string,
            audio_type=body.audio_source.type.value,
            ami_result="N/A",
            uniqueid="",
            error=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Originação via AMI
    call_id = str(uuid.uuid4())
    try:
        ami_result = await ami.originate(
            dial_string=dial_string,
            playback_ref=playback_ref,
            caller_id=f"{company.name} <0000>",
        )
    except RuntimeError as exc:
        write_access_record(
            client_ip=client_ip,
            client_id=auth.client_id,
            token_label=auth.token_label,
            company_id=body.company_id,
            to_number=body.to_number,
            dial_string=dial_string,
            audio_type=body.audio_source.type.value,
            ami_result="error",
            uniqueid="",
            call_id=call_id,
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail="ami_error") from exc

    uniqueid = ami_result.get("uniqueid", "")

    write_access_record(
        client_ip=client_ip,
        client_id=auth.client_id,
        token_label=auth.token_label,
        company_id=body.company_id,
        to_number=body.to_number,
        dial_string=dial_string,
        audio_type=body.audio_source.type.value,
        ami_result=ami_result.get("status", "queued"),
        uniqueid=uniqueid,
        call_id=call_id,
    )

    return CallAccepted(
        call_id=call_id,
        uniqueid=uniqueid,
    )
