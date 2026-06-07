from __future__ import annotations

from typing import Generator

from fastapi import Request
from sqlalchemy.orm import Session


def get_db(request: Request) -> Generator[Session, None, None]:
    factory = request.app.state.session_factory
    db: Session = factory()
    try:
        yield db
    finally:
        db.close()


def get_ami(request: Request):
    return request.app.state.ami


def get_app_settings(request: Request):
    return request.app.state.settings
