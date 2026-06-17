"""Testes das rotas admin de empresas e criação de cliente."""
from __future__ import annotations

import io
import shutil
import wave

import pytest

from app import crud

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def _admin_login(http) -> None:
    response = http.post(
        "/adminAPI/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def _make_wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"\x00" * 1600)
    return buffer.getvalue()


class TestAdminClientCreate:
    def test_creates_client_and_recordings_directory(self, app_client, tmp_path):
        http, _, _, _, _ = app_client
        _admin_login(http)

        response = http.post(
            "/adminAPI/clients/new",
            data={"name": "Novo Cliente", "dial_prefix": "3003"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/adminAPI/clients/" in response.headers["location"]

        client_id = response.headers["location"].rstrip("/").split("/")[-1].split("?")[0]
        recordings_dir = tmp_path / "sounds" / "custom" / client_id
        assert recordings_dir.is_dir()


class TestAdminCompanies:
    @pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg não instalado")
    def test_create_company_with_audio_upload(self, app_client, tmp_path, client_obj):
        http, _, client_obj, _, _ = app_client
        _admin_login(http)

        wav = _make_wav_bytes()
        response = http.post(
            f"/adminAPI/clients/{client_obj.id}/companies/new",
            data={
                "company_id": "nova_empresa",
                "name": "Nova Empresa",
            },
            files={"audio_files": ("boas_vindas.wav", wav, "audio/wav")},
            follow_redirects=False,
        )
        assert response.status_code == 302

        output = tmp_path / "sounds" / "custom" / str(client_obj.id) / "boas_vindas.wav"
        assert output.exists()

    def test_edit_company_updates_name(self, app_client, db_factory, company_obj, client_obj):
        http, _, client_obj, company_obj, _ = app_client
        _admin_login(http)

        response = http.post(
            f"/adminAPI/clients/{client_obj.id}/companies/{company_obj.id}/edit",
            data={"name": "Empresa Renomeada", "active": "on"},
            follow_redirects=False,
        )
        assert response.status_code == 302

        verify_db = db_factory()
        try:
            updated = crud.get_company_by_pk(verify_db, company_obj.id)
            assert updated.name == "Empresa Renomeada"
            assert updated.active is True
        finally:
            verify_db.close()

    def test_delete_company_removes_from_db(self, app_client, db_factory, company_obj, client_obj):
        http, _, client_obj, company_obj, _ = app_client
        _admin_login(http)
        company_pk = company_obj.id

        response = http.post(
            f"/adminAPI/clients/{client_obj.id}/companies/{company_pk}/delete",
            follow_redirects=False,
        )
        assert response.status_code == 302

        verify_db = db_factory()
        try:
            assert crud.get_company_by_pk(verify_db, company_pk) is None
        finally:
            verify_db.close()

    def test_client_detail_lists_recordings(self, app_client, client_obj, tmp_path):
        http, _, client_obj, _, _ = app_client
        sounds_dir = tmp_path / "sounds" / "custom" / str(client_obj.id)
        sounds_dir.mkdir(parents=True, exist_ok=True)
        (sounds_dir / "mensagem_teste.wav").write_bytes(b"RIFF")

        _admin_login(http)
        response = http.get(f"/adminAPI/clients/{client_obj.id}")
        assert response.status_code == 200
        assert b"mensagem_teste" in response.content
