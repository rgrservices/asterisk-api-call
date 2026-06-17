from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.schemas import AudioSource, AudioSourceType

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ASTERISK_SAMPLE_RATE = 8000
ASTERISK_CHANNELS = 1
ASTERISK_SAMPLE_WIDTH = 2  # 16-bit

_FILENAME_RE = re.compile(r"[^a-z0-9_-]+")


class AudioUploadError(Exception):
    """Erro de validação ou processamento de upload de áudio."""


def client_recordings_dir(
    sounds_base_dir: Path,
    recordings_base_path: str,
    client_id: int,
) -> Path:
    return sounds_base_dir / recordings_base_path / str(client_id)


def ensure_client_recordings_dir(
    sounds_base_dir: Path,
    recordings_base_path: str,
    client_id: int,
) -> Path:
    path = client_recordings_dir(sounds_base_dir, recordings_base_path, client_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_client_recordings(
    sounds_base_dir: Path,
    recordings_base_path: str,
    client_id: int,
) -> list[str]:
    """Retorna os nomes de content (sem .wav) dos arquivos na pasta do cliente."""
    directory = client_recordings_dir(sounds_base_dir, recordings_base_path, client_id)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.wav") if p.is_file())


def sanitize_filename(name: str) -> str:
    """Normaliza o basename do arquivo para uso seguro no filesystem."""
    stem = Path(name).stem.strip().lower()
    stem = _FILENAME_RE.sub("_", stem)
    stem = stem.strip("_")
    if not stem:
        raise AudioUploadError("Nome de arquivo inválido ou vazio.")
    if ".." in name or "/" in name or "\\" in name:
        raise AudioUploadError("Nome de arquivo inválido.")
    return stem


def convert_and_save_wav(source: bytes, destination: Path) -> None:
    """
    Converte o áudio para WAV mono 8 kHz 16-bit (padrão Asterisk/FreePBX)
    e grava em destination.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".upload", delete=False) as src:
        src.write(source)
        src_path = Path(src.name)

    tmp_out = destination.with_suffix(".tmp.wav")
    try:
        if shutil.which("ffmpeg") is None:
            raise AudioUploadError(
                "ffmpeg não encontrado no servidor. Instale com: apt install ffmpeg"
            )

        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src_path),
                "-ac",
                str(ASTERISK_CHANNELS),
                "-ar",
                str(ASTERISK_SAMPLE_RATE),
                "-sample_fmt",
                "s16",
                str(tmp_out),
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip()
            raise AudioUploadError(f"Arquivo de áudio inválido: {stderr or 'ffmpeg falhou'}")

        tmp_out.replace(destination)
    finally:
        src_path.unlink(missing_ok=True)
        if tmp_out.exists() and not destination.exists():
            tmp_out.unlink(missing_ok=True)


def save_uploaded_recordings(
    files: list[tuple[str, bytes]],
    sounds_base_dir: Path,
    recordings_base_path: str,
    client_id: int,
) -> tuple[list[str], list[str]]:
    """
    Salva múltiplos uploads na pasta do cliente.

    Retorna (saved_contents, overwritten_contents).
    """
    directory = ensure_client_recordings_dir(
        sounds_base_dir, recordings_base_path, client_id
    )
    saved: list[str] = []
    overwritten: list[str] = []

    for original_name, data in files:
        if not data:
            continue
        if len(data) > MAX_UPLOAD_BYTES:
            raise AudioUploadError(
                f"Arquivo '{original_name}' excede o limite de 10 MB."
            )

        content = sanitize_filename(original_name)
        destination = directory / f"{content}.wav"

        if destination.exists():
            overwritten.append(content)

        convert_and_save_wav(data, destination)
        saved.append(content)

    return saved, overwritten


def resolve_audio(
    audio_source: AudioSource,
    client_id: int,
    sounds_base_dir: Path,
    recordings_base_path: str,
) -> str:
    """
    Valida o audio_source e retorna a referência Asterisk Playback (sem extensão).

    Para type='recording':
        - Monta o path completo: {sounds_base_dir}/{recordings_base_path}/{client_id}/{content}.wav
        - Verifica existência do arquivo .wav no disco
        - Retorna: '{recordings_base_path}/{client_id}/{content}'

    Para type='tts':
        - Levanta NotImplementedError (reservado para Fase 4 futura)

    Levanta:
        NotImplementedError  — type=tts (HTTP 501)
        FileNotFoundError    — arquivo .wav não encontrado (HTTP 400)
    """
    if audio_source.type == AudioSourceType.tts:
        raise NotImplementedError("tts_not_implemented")

    ref = f"{recordings_base_path}/{client_id}/{audio_source.content}"
    wav_path = sounds_base_dir / f"{ref}.wav"

    if not wav_path.exists():
        raise FileNotFoundError(f"recording_not_found: {audio_source.content}")

    return ref
