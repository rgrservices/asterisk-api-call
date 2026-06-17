"""Testes unitários para resolução e gestão de áudio (app/audio.py)."""
import io
import shutil
import wave
from pathlib import Path

import pytest

from app.audio import (
    AudioUploadError,
    client_recordings_dir,
    ensure_client_recordings_dir,
    list_client_recordings,
    resolve_audio,
    sanitize_filename,
    save_uploaded_recordings,
)
from app.schemas import AudioSource, AudioSourceType

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


def _make_source(type_: str, content: str) -> AudioSource:
    return AudioSource(type=AudioSourceType(type_), content=content)


def _make_wav_bytes(
    *,
    sample_rate: int = 8000,
    channels: int = 1,
    sample_width: int = 2,
    duration_frames: int = 800,
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00" * duration_frames * channels * sample_width)
    return buffer.getvalue()


class TestResolveAudio:
    def test_recording_found(self, tmp_path):
        sounds = tmp_path / "sounds"
        (sounds / "custom" / "1").mkdir(parents=True)
        (sounds / "custom" / "1" / "mensagem.wav").write_bytes(b"RIFF" + b"\x00" * 36)

        ref = resolve_audio(_make_source("recording", "mensagem"), 1, sounds, "custom")
        assert ref == "custom/1/mensagem"

    def test_recording_not_found_raises(self, tmp_path):
        sounds = tmp_path / "sounds"
        sounds.mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="recording_not_found"):
            resolve_audio(_make_source("recording", "inexistente"), 1, sounds, "custom")

    def test_tts_raises_not_implemented(self, tmp_path):
        with pytest.raises(NotImplementedError, match="tts_not_implemented"):
            resolve_audio(_make_source("tts", "Olá mundo"), 1, tmp_path, "custom")


class TestClientRecordingsDir:
    def test_client_recordings_dir(self, tmp_path):
        path = client_recordings_dir(tmp_path, "custom", 42)
        assert path == tmp_path / "custom" / "42"

    def test_ensure_client_recordings_dir_creates_and_is_idempotent(self, tmp_path):
        path = ensure_client_recordings_dir(tmp_path, "custom", 7)
        assert path.is_dir()
        again = ensure_client_recordings_dir(tmp_path, "custom", 7)
        assert again == path

    def test_list_client_recordings(self, tmp_path):
        directory = ensure_client_recordings_dir(tmp_path, "custom", 1)
        (directory / "alpha.wav").write_bytes(b"RIFF")
        (directory / "beta.wav").write_bytes(b"RIFF")
        (directory / "ignore.txt").write_text("x")

        assert list_client_recordings(tmp_path, "custom", 1) == ["alpha", "beta"]

    def test_list_client_recordings_empty_when_missing(self, tmp_path):
        assert list_client_recordings(tmp_path, "custom", 99) == []


class TestSanitizeFilename:
    def test_sanitize_lowercase_and_safe_chars(self):
        assert sanitize_filename("Boas-Vindas.WAV") == "boas-vindas"

    def test_sanitize_rejects_empty(self):
        with pytest.raises(AudioUploadError, match="inválido"):
            sanitize_filename("...")

    def test_sanitize_rejects_path_traversal(self):
        with pytest.raises(AudioUploadError, match="inválido"):
            sanitize_filename("../secret.wav")


@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg não instalado")
class TestSaveUploadedRecordings:
    def test_converts_stereo_to_mono_8khz(self, tmp_path):
        wav_data = _make_wav_bytes(sample_rate=44100, channels=2)
        saved, overwritten = save_uploaded_recordings(
            [("Mensagem Teste.wav", wav_data)],
            tmp_path,
            "custom",
            1,
        )
        assert saved == ["mensagem_teste"]
        assert overwritten == []

        output = tmp_path / "custom" / "1" / "mensagem_teste.wav"
        assert output.exists()
        with wave.open(str(output), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 8000
            assert wf.getsampwidth() == 2

    def test_overwrite_reports_existing_file(self, tmp_path):
        wav_data = _make_wav_bytes()
        save_uploaded_recordings([("aviso.wav", wav_data)], tmp_path, "custom", 1)
        _, overwritten = save_uploaded_recordings(
            [("aviso.wav", wav_data)], tmp_path, "custom", 1
        )
        assert overwritten == ["aviso"]

    def test_rejects_oversized_file(self, tmp_path):
        from app.audio import MAX_UPLOAD_BYTES

        huge = b"\x00" * (MAX_UPLOAD_BYTES + 1)
        with pytest.raises(AudioUploadError, match="10 MB"):
            save_uploaded_recordings([("big.wav", huge)], tmp_path, "custom", 1)
