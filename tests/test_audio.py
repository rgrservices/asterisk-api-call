"""Testes unitários para resolução de áudio (app/audio.py)."""
from pathlib import Path

import pytest

from app.audio import resolve_audio
from app.schemas import AudioSource, AudioSourceType


def _make_source(type_: str, content: str) -> AudioSource:
    return AudioSource(type=AudioSourceType(type_), content=content)


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
