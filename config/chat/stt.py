from __future__ import annotations

import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

import requests


class BaseSTTBackend(ABC):
    @abstractmethod
    def transcribe(self, audio_bytes: bytes, mime_type: str | None = None) -> str:
        raise NotImplementedError


class DeepgramSTTBackend(BaseSTTBackend):
    def __init__(self, api_key: str, model: str = "nova-3", language: str = "es"):
        self.api_key = api_key
        self.model = model
        self.language = language

    def transcribe(self, audio_bytes: bytes, mime_type: str | None = None) -> str:
        if not self.api_key:
            raise RuntimeError("Falta DEEPGRAM_API_KEY en las variables de entorno.")

        content_type = mime_type or "audio/webm"
        url = (
            "https://api.deepgram.com/v1/listen"
            f"?model={self.model}&language={self.language}&smart_format=true"
        )

        response = requests.post(
            url,
            headers={
                "Authorization": f"Token {self.api_key}",
                "Content-Type": content_type,
            },
            data=audio_bytes,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()

        try:
            return data["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Respuesta STT inesperada: {data}") from exc


class FasterWhisperSTTBackend(BaseSTTBackend):
    def __init__(self, model_size: str = "large-v3", language: str = "es"):
        from faster_whisper import WhisperModel

        self.language = language
        self.model = WhisperModel(
            model_size,
            device=os.getenv("FW_DEVICE", "cpu"),
            compute_type=os.getenv("FW_COMPUTE_TYPE", "int8"),
        )

    def transcribe(self, audio_bytes: bytes, mime_type: str | None = None) -> str:
        suffix = ".webm"
        if mime_type and "wav" in mime_type:
            suffix = ".wav"
        elif mime_type and "mp3" in mime_type:
            suffix = ".mp3"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            temp_path = Path(tmp.name)

        try:
            segments, _ = self.model.transcribe(
                str(temp_path),
                language=self.language,
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


def build_stt_backend() -> BaseSTTBackend:
    from django.conf import settings  # import aquí para evitar circular imports

    provider = os.getenv("STT_PROVIDER", "deepgram").lower()

    if provider == "deepgram":
        return DeepgramSTTBackend(
            api_key=getattr(settings, "DEEPGRAM_API_KEY", ""),
            model=os.getenv("DEEPGRAM_STT_MODEL", "nova-3"),
            language=os.getenv("DEEPGRAM_STT_LANGUAGE", "es"),
        )

    if provider == "faster_whisper":
        return FasterWhisperSTTBackend(
            model_size=os.getenv("FW_MODEL_SIZE", "large-v3"),
            language=os.getenv("FW_LANGUAGE", "es"),
        )

    raise RuntimeError(f"Proveedor STT no soportado: {provider}")
