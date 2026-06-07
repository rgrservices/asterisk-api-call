"""Testes de integração do endpoint POST /api/v1/call."""
from __future__ import annotations

import pytest


ENDPOINT = "/api/v1/call"


def _auth(raw_token: str) -> dict:
    return {"Authorization": f"Bearer {raw_token}"}


class TestSuccessfulCall:
    def test_returns_202(self, app_client, raw_token):
        http, _, client_obj, company_obj, _ = app_client
        body = {
            "to_number": "+5511999999999",
            "company_id": company_obj.company_id,
            "audio_source": {"type": "recording", "content": "mensagem_teste"},
        }
        r = http.post(ENDPOINT, json=body, headers=_auth(raw_token))
        assert r.status_code == 202

    def test_response_has_call_id_and_status(self, app_client, raw_token):
        http, _, client_obj, company_obj, _ = app_client
        body = {
            "to_number": "+5511999999999",
            "company_id": company_obj.company_id,
            "audio_source": {"type": "recording", "content": "mensagem_teste"},
        }
        r = http.post(ENDPOINT, json=body, headers=_auth(raw_token))
        data = r.json()
        assert "call_id" in data
        assert data["status"] == "queued"
        assert data["uniqueid"] == "test-uid-123"

    def test_ami_receives_correct_dial_string(self, app_client, raw_token):
        http, _, client_obj, company_obj, mock_ami = app_client
        body = {
            "to_number": "+5511999999999",
            "company_id": company_obj.company_id,
            "audio_source": {"type": "recording", "content": "mensagem_teste"},
        }
        r = http.post(ENDPOINT, json=body, headers=_auth(raw_token))
        assert r.status_code == 202
        call_kwargs = mock_ami.originate.call_args.kwargs
        # dial_prefix=2002 + national=11999999999
        assert call_kwargs["dial_string"] == "200211999999999"

    def test_ami_receives_correct_playback_ref(self, app_client, raw_token):
        http, _, client_obj, company_obj, mock_ami = app_client
        body = {
            "to_number": "+5511999999999",
            "company_id": company_obj.company_id,
            "audio_source": {"type": "recording", "content": "mensagem_teste"},
        }
        http.post(ENDPOINT, json=body, headers=_auth(raw_token))
        call_kwargs = mock_ami.originate.call_args.kwargs
        assert call_kwargs["playback_ref"] == f"custom/{client_obj.id}/mensagem_teste"


class TestValidationErrors:
    def test_invalid_number_format_returns_400(self, app_client, raw_token):
        http, _, _, company_obj, _ = app_client
        body = {
            "to_number": "abc123",
            "company_id": company_obj.company_id,
            "audio_source": {"type": "recording", "content": "mensagem_teste"},
        }
        r = http.post(ENDPOINT, json=body, headers=_auth(raw_token))
        assert r.status_code == 400

    def test_non_br_number_returns_400(self, app_client, raw_token):
        http, _, _, company_obj, _ = app_client
        body = {
            "to_number": "+14155551234",
            "company_id": company_obj.company_id,
            "audio_source": {"type": "recording", "content": "mensagem_teste"},
        }
        r = http.post(ENDPOINT, json=body, headers=_auth(raw_token))
        assert r.status_code == 400

    def test_missing_to_number_returns_400(self, app_client, raw_token):
        http, *_ = app_client
        body = {
            "company_id": "empresa_teste_01",
            "audio_source": {"type": "recording", "content": "mensagem_teste"},
        }
        r = http.post(ENDPOINT, json=body, headers=_auth(raw_token))
        assert r.status_code == 400

    def test_recording_not_found_returns_400(self, app_client, raw_token):
        http, _, _, company_obj, _ = app_client
        body = {
            "to_number": "+5511999999999",
            "company_id": company_obj.company_id,
            "audio_source": {"type": "recording", "content": "arquivo_inexistente"},
        }
        r = http.post(ENDPOINT, json=body, headers=_auth(raw_token))
        assert r.status_code == 400
        assert "recording_not_found" in r.json()["detail"]

    def test_tts_returns_501(self, app_client, raw_token):
        http, _, _, company_obj, _ = app_client
        body = {
            "to_number": "+5511999999999",
            "company_id": company_obj.company_id,
            "audio_source": {"type": "tts", "content": "Olá, este é um teste"},
        }
        r = http.post(ENDPOINT, json=body, headers=_auth(raw_token))
        assert r.status_code == 501


class TestCompanyNotAuthorized:
    def test_unknown_company_returns_403(self, app_client, raw_token):
        http, *_ = app_client
        body = {
            "to_number": "+5511999999999",
            "company_id": "empresa_desconhecida",
            "audio_source": {"type": "recording", "content": "mensagem_teste"},
        }
        r = http.post(ENDPOINT, json=body, headers=_auth(raw_token))
        assert r.status_code == 403
        assert r.json()["detail"] == "company_not_authorized"


class TestHealthCheck:
    def test_health_returns_200(self, app_client):
        http, *_ = app_client
        r = http.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
