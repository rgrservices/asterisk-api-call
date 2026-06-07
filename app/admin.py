from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware

from app import crud
from app.deps import get_db

router = APIRouter(prefix="/adminAPI", tags=["Admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_SESSION_COOKIE = "call_api_session"
_SESSION_MAX_AGE = 86400  # 24 horas


# ─── Session helpers ──────────────────────────────────────────────────────────

def _serializer(settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.admin_secret_key)


def _sign_session(settings, username: str) -> str:
    return _serializer(settings).dumps(username)


def _verify_session(settings, token: str) -> Optional[str]:
    try:
        return _serializer(settings).loads(token, max_age=_SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def _get_admin(request: Request) -> Optional[str]:
    settings = request.app.state.settings
    cookie = request.cookies.get(_SESSION_COOKIE)
    if not cookie:
        return None
    return _verify_session(settings, cookie)


def _is_https(request: Request) -> bool:
    """Detecta HTTPS direto ou via header X-Forwarded-Proto do reverse proxy."""
    proto = request.headers.get("x-forwarded-proto", "")
    return proto.lower() == "https" or request.url.scheme == "https"


# ─── Middleware: protege /admin/* exceto /admin/login ─────────────────────────

class AdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/adminAPI") and path not in ("/adminAPI/login", "/adminAPI/login/"):
            settings = request.app.state.settings
            cookie = request.cookies.get(_SESSION_COOKIE)
            username = _verify_session(settings, cookie) if cookie else None
            if not username:
                return RedirectResponse("/adminAPI/login", status_code=302)
        return await call_next(request)


# ─── Auth routes ──────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(
        request, "admin/login.html", context={"error": error}
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    settings = request.app.state.settings
    if username == settings.admin_user and password == settings.admin_password:
        token = _sign_session(settings, username)
        response = RedirectResponse("/adminAPI/", status_code=302)
        response.set_cookie(
            _SESSION_COOKIE,
            token,
            max_age=_SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=_is_https(request),
        )
        return response
    return RedirectResponse("/adminAPI/login?error=Credenciais+inv%C3%A1lidas", status_code=302)


@router.post("/logout")
def logout(request: Request):
    response = RedirectResponse("/adminAPI/login", status_code=302)
    response.delete_cookie(_SESSION_COOKIE)
    return response


# ─── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    db = next(get_db(request))
    try:
        active_clients = crud.count_active_clients(db)
        active_tokens = crud.count_active_tokens(db)
        calls_24h = _count_calls_24h(request.app.state.settings.access_log_path)
    finally:
        db.close()
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        context={
            "active_clients": active_clients,
            "active_tokens": active_tokens,
            "calls_24h": calls_24h,
        },
    )


# ─── Client routes ────────────────────────────────────────────────────────────

@router.get("/clients", response_class=HTMLResponse)
def clients_list(request: Request, msg: str = "", msg_type: str = "success"):
    db = next(get_db(request))
    try:
        clients = crud.list_clients(db)
    finally:
        db.close()
    return templates.TemplateResponse(
        request,
        "admin/clients.html",
        context={"clients": clients, "msg": msg, "msg_type": msg_type},
    )


@router.get("/clients/new", response_class=HTMLResponse)
def client_new_form(request: Request, error: str = ""):
    return templates.TemplateResponse(
        request,
        "admin/client_form.html",
        context={"client": None, "error": error, "action": "/adminAPI/clients/new"},
    )


@router.post("/clients/new")
def client_create(
    request: Request,
    name: str = Form(...),
    dial_prefix: str = Form(...),
):
    if not dial_prefix.isdigit() or len(dial_prefix) != 4:
        return RedirectResponse(
            "/adminAPI/clients/new?error=O+prefixo+deve+ter+exatamente+4+d%C3%ADgitos",
            status_code=302,
        )
    db = next(get_db(request))
    try:
        crud.create_client(db, name=name.strip(), dial_prefix=dial_prefix)
    finally:
        db.close()
    return RedirectResponse(
        "/adminAPI/clients?msg=Cliente+criado+com+sucesso&msg_type=success", status_code=302
    )


@router.get("/clients/{client_id}", response_class=HTMLResponse)
def client_detail(request: Request, client_id: int):
    db = next(get_db(request))
    try:
        client = crud.get_client(db, client_id)
        if client is None:
            return RedirectResponse("/adminAPI/clients?msg=Cliente+n%C3%A3o+encontrado&msg_type=danger")
        tokens = crud.list_tokens(db, client_id)
        companies = crud.list_companies(db, client_id)
    finally:
        db.close()
    return templates.TemplateResponse(
        request,
        "admin/client_detail.html",
        context={
            "client": client,
            "tokens": tokens,
            "companies": companies,
        },
    )


@router.get("/clients/{client_id}/edit", response_class=HTMLResponse)
def client_edit_form(request: Request, client_id: int, error: str = ""):
    db = next(get_db(request))
    try:
        client = crud.get_client(db, client_id)
        if client is None:
            return RedirectResponse("/adminAPI/clients")
    finally:
        db.close()
    return templates.TemplateResponse(
        request,
        "admin/client_form.html",
        context={
            "client": client,
            "error": error,
            "action": f"/adminAPI/clients/{client_id}/edit",
        },
    )


@router.post("/clients/{client_id}/edit")
def client_update(
    request: Request,
    client_id: int,
    name: str = Form(...),
    dial_prefix: str = Form(...),
    active: Optional[str] = Form(default=None),
):
    if not dial_prefix.isdigit() or len(dial_prefix) != 4:
        return RedirectResponse(
            f"/adminAPI/clients/{client_id}/edit?error=O+prefixo+deve+ter+exatamente+4+d%C3%ADgitos",
            status_code=302,
        )
    db = next(get_db(request))
    try:
        client = crud.get_client(db, client_id)
        if client:
            crud.update_client(
                db,
                client,
                name=name.strip(),
                dial_prefix=dial_prefix,
                active=(active == "on"),
            )
    finally:
        db.close()
    return RedirectResponse(
        f"/adminAPI/clients/{client_id}?msg=Cliente+atualizado&msg_type=success", status_code=302
    )


# ─── Token routes ─────────────────────────────────────────────────────────────

@router.post("/clients/{client_id}/tokens/generate")
def token_generate(
    request: Request,
    client_id: int,
    label: str = Form(...),
    calls_per_minute: int = Form(default=5),
):
    raw_token = secrets.token_hex(32)
    db = next(get_db(request))
    try:
        crud.create_token(
            db,
            client_id=client_id,
            raw_token=raw_token,
            label=label.strip(),
            calls_per_minute=calls_per_minute,
        )
    finally:
        db.close()
    return templates.TemplateResponse(
        request,
        "admin/token_generated.html",
        context={
            "client_id": client_id,
            "label": label,
            "token_value": raw_token,
        },
    )


@router.post("/clients/{client_id}/tokens/{token_id}/revoke")
def token_revoke(request: Request, client_id: int, token_id: int):
    db = next(get_db(request))
    try:
        token = crud.get_token(db, token_id)
        if token and token.client_id == client_id:
            crud.revoke_token(db, token)
    finally:
        db.close()
    return RedirectResponse(
        f"/adminAPI/clients/{client_id}?msg=Token+revogado&msg_type=warning", status_code=302
    )


# ─── Company routes ───────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/companies/new", response_class=HTMLResponse)
def company_new_form(request: Request, client_id: int, error: str = ""):
    db = next(get_db(request))
    try:
        client = crud.get_client(db, client_id)
    finally:
        db.close()
    return templates.TemplateResponse(
        request,
        "admin/company_form.html",
        context={"client": client, "error": error},
    )


@router.post("/clients/{client_id}/companies/new")
def company_create(
    request: Request,
    client_id: int,
    company_id: str = Form(...),
    name: str = Form(...),
):
    db = next(get_db(request))
    try:
        crud.create_company(
            db,
            client_id=client_id,
            company_id=company_id.strip().lower(),
            name=name.strip(),
        )
    except IntegrityError:
        return RedirectResponse(
            f"/adminAPI/clients/{client_id}/companies/new?error=ID+j%C3%A1+existe+neste+cliente",
            status_code=302,
        )
    finally:
        db.close()
    return RedirectResponse(
        f"/adminAPI/clients/{client_id}?msg=Empresa+criada+com+sucesso&msg_type=success",
        status_code=302,
    )


@router.post("/clients/{client_id}/companies/{company_pk}/toggle")
def company_toggle(request: Request, client_id: int, company_pk: int):
    db = next(get_db(request))
    try:
        company = crud.get_company_by_pk(db, company_pk)
        if company and company.client_id == client_id:
            crud.toggle_company(db, company)
    finally:
        db.close()
    return RedirectResponse(
        f"/adminAPI/clients/{client_id}?msg=Empresa+atualizada&msg_type=info", status_code=302
    )


# ─── Logs ─────────────────────────────────────────────────────────────────────

@router.get("/logs", response_class=HTMLResponse)
def logs_view(request: Request, page: int = 1):
    log_path = request.app.state.settings.access_log_path
    entries = _read_log_entries(Path(log_path), n=500)
    per_page = 50
    total = len(entries)
    start = (page - 1) * per_page
    page_entries = entries[start : start + per_page]
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request,
        "admin/logs.html",
        context={
            "entries": page_entries,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _read_log_entries(log_path: Path, n: int = 500) -> list[dict]:
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        recent = lines[-n:] if len(lines) > n else lines
        entries: list[dict] = []
        for line in reversed(recent):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return entries
    except Exception:
        return []


def _count_calls_24h(log_path: Path) -> int:
    from datetime import UTC, timedelta

    entries = _read_log_entries(log_path, n=10000)
    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    return sum(1 for e in entries if e.get("ts", "") >= cutoff and "error" not in e)
