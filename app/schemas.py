from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


class AudioSourceType(str, Enum):
    tts = "tts"
    recording = "recording"


class AudioSource(BaseModel):
    type: AudioSourceType
    content: str = Field(..., min_length=1)


class CallRequest(BaseModel):
    to_number: str = Field(
        ...,
        min_length=1,
        description="Número de destino em E.164 (ex.: +5511999999999 ou 5511999999999)",
    )
    company_id: str = Field(..., min_length=1, description="ID da empresa autorizada")
    audio_source: AudioSource

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "to_number": "+5511999999999",
                    "company_id": "cliente_alpha_01",
                    "audio_source": {
                        "type": "recording",
                        "content": "aviso_feriado_loja",
                    },
                }
            ]
        }
    }


class CallAccepted(BaseModel):
    status: str = "queued"
    call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    uniqueid: str = ""
    message: str = "Chamada encaminhada ao Asterisk."
