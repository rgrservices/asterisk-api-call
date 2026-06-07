"""Testes de autenticação e autorização do endpoint /api/v1/call."""
from __future__ import annotations

import pytest

from app import crud


ENDPOINT = "/api/v1/call"

VALID_BODY = {
    "to_number": "+5511999999999",
    "company_id": "empresa_teste_01",
    "audio_source": {"type": "recording", "content": "mensagem_teste"},
}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestMissingAuth:
    def test_no_header_returns_401(self, app_client):
        http, *_ = app_client
        r = http.post(ENDPOINT, json=VALID_BODY)
        assert r.status_code == 401

    def test_wrong_scheme_returns_401(self, app_client):
        http, *_ = app_client
        r = http.post(ENDPOINT, json=VALID_BODY, headers={"Authorization": "Basic abc"})
        assert r.status_code == 401


class TestInvalidToken:
    def test_unknown_token_returns_401(self, app_client):
        http, *_ = app_client
        r = http.post(ENDPOINT, json=VALID_BODY, headers=_auth("token-invalido"))
        assert r.status_code == 401
        assert r.json()["detail"] == "invalid_token"

    def test_empty_bearer_returns_401(self, app_client):
        http, *_ = app_client
        r = http.post(ENDPOINT, json=VALID_BODY, headers={"Authorization": "Bearer "})
        assert r.status_code == 401


class TestRevokedToken:
    def test_revoked_token_returns_401(self, app_client, raw_token, db, token_obj):
        http, *_ = app_client
        crud.revoke_token(db, token_obj)
        r = http.post(ENDPOINT, json=VALID_BODY, headers=_auth(raw_token))
        assert r.status_code == 401
        assert r.json()["detail"] == "token_revoked"


class TestValidToken:
    def test_valid_token_with_valid_company_returns_202(self, app_client, raw_token):
        http, *_ = app_client
        r = http.post(ENDPOINT, json=VALID_BODY, headers=_auth(raw_token))
        assert r.status_code == 202

    def test_valid_token_unknown_company_returns_403(self, app_client, raw_token):
        http, *_ = app_client
        body = {**VALID_BODY, "company_id": "empresa_inexistente"}
        r = http.post(ENDPOINT, json=body, headers=_auth(raw_token))
        assert r.status_code == 403
        assert r.json()["detail"] == "company_not_authorized"
