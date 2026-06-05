from enum import Enum

from pydantic import BaseModel, Field


class AudioSourceType(str, Enum):
    tts = "tts"
    recording = "recording"


class AudioSource(BaseModel):
    type: AudioSourceType
    content: str = Field(..., min_length=1)


class CallRequest(BaseModel):
    to_number: str = Field(..., min_length=1, description="E.164 destination")
    company_id: str = Field(..., min_length=1)
    audio_source: AudioSource


class CallAcceptedPhase1(BaseModel):
    status: str = "validated"
    dial_string: str
    message: str
