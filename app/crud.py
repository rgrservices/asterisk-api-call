from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Client, ClientToken, Company


def hash_token(raw: str) -> str:
    return sha256(raw.encode()).hexdigest()


# ─── Token auth ───────────────────────────────────────────────────────────────

def get_token_by_hash(db: Session, token_hash: str) -> Optional[ClientToken]:
    return (
        db.query(ClientToken)
        .join(ClientToken.client)
        .filter(ClientToken.token_hash == token_hash)
        .first()
    )


def touch_token(db: Session, token: ClientToken) -> None:
    token.last_used_at = datetime.now(UTC)
    db.commit()


# ─── Client CRUD ──────────────────────────────────────────────────────────────

def list_clients(db: Session) -> list[Client]:
    return db.query(Client).order_by(Client.name).all()


def get_client(db: Session, client_id: int) -> Optional[Client]:
    return db.query(Client).filter(Client.id == client_id).first()


def create_client(db: Session, name: str, dial_prefix: str) -> Client:
    client = Client(name=name, dial_prefix=dial_prefix)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def update_client(db: Session, client: Client, **fields) -> Client:
    for key, value in fields.items():
        setattr(client, key, value)
    db.commit()
    db.refresh(client)
    return client


# ─── Token CRUD ───────────────────────────────────────────────────────────────

def list_tokens(db: Session, client_id: int) -> list[ClientToken]:
    return (
        db.query(ClientToken)
        .filter(ClientToken.client_id == client_id)
        .order_by(ClientToken.created_at.desc())
        .all()
    )


def get_token(db: Session, token_id: int) -> Optional[ClientToken]:
    return db.query(ClientToken).filter(ClientToken.id == token_id).first()


def create_token(
    db: Session,
    client_id: int,
    raw_token: str,
    label: str,
    calls_per_minute: int = 5,
    expires_at: Optional[datetime] = None,
) -> ClientToken:
    token = ClientToken(
        client_id=client_id,
        token_hash=hash_token(raw_token),
        label=label,
        calls_per_minute=calls_per_minute,
        expires_at=expires_at,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def revoke_token(db: Session, token: ClientToken) -> ClientToken:
    token.active = False
    db.commit()
    return token


# ─── Company CRUD ─────────────────────────────────────────────────────────────

def list_companies(db: Session, client_id: int) -> list[Company]:
    return (
        db.query(Company)
        .filter(Company.client_id == client_id)
        .order_by(Company.name)
        .all()
    )


def get_company_by_ids(db: Session, company_id: str, client_id: int) -> Optional[Company]:
    return (
        db.query(Company)
        .filter(Company.company_id == company_id, Company.client_id == client_id)
        .first()
    )


def get_company_by_pk(db: Session, company_pk: int) -> Optional[Company]:
    return db.query(Company).filter(Company.id == company_pk).first()


def create_company(db: Session, client_id: int, company_id: str, name: str) -> Company:
    company = Company(client_id=client_id, company_id=company_id, name=name)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def toggle_company(db: Session, company: Company) -> Company:
    company.active = not company.active
    db.commit()
    return company


# ─── Dashboard stats ──────────────────────────────────────────────────────────

def count_active_clients(db: Session) -> int:
    return db.query(func.count(Client.id)).filter(Client.active.is_(True)).scalar() or 0


def count_active_tokens(db: Session) -> int:
    return db.query(func.count(ClientToken.id)).filter(ClientToken.active.is_(True)).scalar() or 0
