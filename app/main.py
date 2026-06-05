from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.access_log import setup_access_logging, write_access_record
from app.config import get_settings
from app.phone import normalize_e164_input, to_trunk_dial_string, validate_e164
from app.registry import load_company_entries, load_token_entries
from app.schemas import CallAcceptedPhase1, CallRequest

security = HTTPBearer(auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_access_logging(settings.access_log_path)
    app.state.settings = settings
    app.state.tokens = load_token_entries(settings.call_api_tokens_file)
    app.state.companies = load_company_entries(settings.call_api_companies_file)
    yield


app = FastAPI(
    title="Call origination API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


def get_tokens(request: Request):
    return request.app.state.tokens


def get_companies(request: Request):
    return request.app.state.companies


def require_bearer(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> str:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization")
    return creds.credentials


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/call", response_model=CallAcceptedPhase1)
def originate_call(
    body: CallRequest,
    bearer_token: Annotated[str, Depends(require_bearer)],
    tokens: Annotated[dict, Depends(get_tokens)],
    companies: Annotated[dict, Depends(get_companies)],
):
    entry = tokens.get(bearer_token)
    if entry is None:
        write_access_record(
            company_id=body.company_id,
            to_number=body.to_number,
            ami_result="N/A",
            uniqueid="N/A",
            error="invalid_token",
        )
        raise HTTPException(status_code=401, detail="Invalid or unknown token")

    if body.company_id not in companies:
        write_access_record(
            company_id=body.company_id,
            to_number=body.to_number,
            ami_result="N/A",
            uniqueid="N/A",
            error="company_not_authorized",
        )
        raise HTTPException(status_code=401, detail="Company not authorized")

    dial_prefix = entry.dial_prefix

    try:
        digits = normalize_e164_input(body.to_number)
        validate_e164(digits)
        dial_string = to_trunk_dial_string(digits, dial_prefix)
    except ValueError as e:
        write_access_record(
            company_id=body.company_id,
            to_number=body.to_number,
            ami_result="N/A",
            uniqueid="N/A",
            error="validation_error",
            error_detail=str(e),
        )
        raise HTTPException(status_code=400, detail=str(e)) from e

    write_access_record(
        company_id=body.company_id,
        to_number=body.to_number,
        dial_string=dial_string,
        ami_result="N/A",
        uniqueid="N/A",
        phase=1,
        note="AMI originate not yet implemented",
    )

    return CallAcceptedPhase1(
        dial_string=dial_string,
        message="Validação concluída. Originação AMI na Fase 2.",
    )
