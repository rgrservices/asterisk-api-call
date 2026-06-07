"""
Fixtures compartilhadas pelos testes.

Estratégia:
- SQLite em memória isolado por teste (engine function-scoped).
- Após o lifespan, `app.state.session_factory` é substituído pelo factory do
  banco de teste para que `get_db` use a sessão correta.
- AMI mockado via `app.state.ami` (substituído após o lifespan).
"""
from __future__ import annotations

import os
import secrets
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import crud
from app.database import init_db


# ─── Engine in-memory por teste ───────────────────────────────────────────────
# StaticPool garante que todas as conexões usem o MESMO BD in-memory,
# evitando o problema de "no such table" em sessões separadas.

@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def set_pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    init_db(eng)
    return eng


@pytest.fixture
def db_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture
def db(db_factory):
    session = db_factory()
    try:
        yield session
    finally:
        session.close()


# ─── Seed de dados ────────────────────────────────────────────────────────────

@pytest.fixture
def client_obj(db):
    return crud.create_client(db, name="Cliente Teste", dial_prefix="2002")


@pytest.fixture
def raw_token():
    return secrets.token_hex(16)


@pytest.fixture
def token_obj(db, client_obj, raw_token):
    return crud.create_token(
        db,
        client_id=client_obj.id,
        raw_token=raw_token,
        label="Token Teste",
        calls_per_minute=60,
    )


@pytest.fixture
def company_obj(db, client_obj):
    return crud.create_company(
        db,
        client_id=client_obj.id,
        company_id="empresa_teste_01",
        name="Empresa Teste",
    )


# ─── Mock AMI ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_ami():
    ami = MagicMock()
    ami.configured = True
    ami.originate = AsyncMock(return_value={"status": "queued", "uniqueid": "test-uid-123"})
    return ami


# ─── App TestClient ───────────────────────────────────────────────────────────

@pytest.fixture
def app_client(db_factory, client_obj, token_obj, company_obj, mock_ami, tmp_path):
    """
    TestClient com:
    - app.state.session_factory → factory do banco in-memory de teste
    - app.state.ami → mock
    - Diretório de sons temporário com WAV de teste
    """
    env_backup: dict[str, str | None] = {}
    test_db_path = tmp_path / "lifespan_test.db"
    env_overrides = {
        "DB_PATH": str(test_db_path),
        "ADMIN_USER": "admin",
        "ADMIN_PASSWORD": "admin123",
        "ADMIN_SECRET_KEY": "test-secret-key-32-chars-minimum!",
        "ACCESS_LOG_PATH": str(tmp_path / "access.log"),
        "AMI_USER": "test",
        "AMI_SECRET": "test",
        "SOUNDS_BASE_DIR": str(tmp_path / "sounds"),
        "RECORDINGS_BASE_PATH": "custom",
    }
    for k, v in env_overrides.items():
        env_backup[k] = os.environ.get(k)
        os.environ[k] = v

    # Arquivo WAV de teste — path usa o client_id do banco in-memory de teste
    sounds_dir = tmp_path / "sounds" / "custom" / str(client_obj.id)
    sounds_dir.mkdir(parents=True, exist_ok=True)
    (sounds_dir / "mensagem_teste.wav").write_bytes(b"RIFF" + b"\x00" * 36)

    from app.main import app

    with TestClient(app, raise_server_exceptions=True) as http:
        # Após o lifespan, redireciona o session_factory para o banco in-memory de teste
        # (o get_db lê app.state.session_factory em cada requisição)
        app.state.session_factory = db_factory
        app.state.ami = mock_ami
        app.state.settings.sounds_base_dir = tmp_path / "sounds"

        yield http, token_obj, client_obj, company_obj, mock_ami

    # Restaurar env vars
    for k, original in env_backup.items():
        if original is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = original
