from __future__ import annotations

from pathlib import Path

from app.schemas import AudioSource, AudioSourceType


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
