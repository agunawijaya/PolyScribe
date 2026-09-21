"""Backend: OpenAI Whisper API.

Endpoint: POST https://api.openai.com/v1/audio/transcriptions (multipart).
Model: whisper-1 (Whisper large-v2). Batas 25 MB per file -> chunker.

Bukan pilihan hemat (harga ~$0.36/jam vs Groq $0.04/jam untuk model
yg mirip), tapi disediakan karena banyak user sudah punya akun OpenAI.
"""

from pathlib import Path
from typing import Iterator

from .base import (
    CloudAsrBackend, CloudTransportError,
    AsrSegment, emit_progress, cancelled, chunk_wav,
)
from .groq import _raise_for_status


_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"


class OpenAIWhisperBackend(CloudAsrBackend):
    name = "cloud:openai_whisper"
    provider_key = "openai_whisper"
    needs_key = True
    has_diarization = False
    has_timestamps = True

    def transcribe(self, wav_16k_mono_path: str, progress,
                   cancel_event=None) -> Iterator[AsrSegment]:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError(
                "Backend OpenAI butuh library `requests`. "
                "Jalankan: pip install -r requirements-cloud.txt"
            ) from e

        lang = getattr(self.config, "primary_language", "en")
        lang_param = None if lang in ("auto", "", None) else lang

        chunks = chunk_wav(wav_16k_mono_path)
        total_chunks = len(chunks)

        for i, (offset, chunk_path) in enumerate(chunks):
            if cancelled(cancel_event):
                return

            data = {
                "model": "whisper-1",
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
            }
            if lang_param:
                data["language"] = lang_param

            with open(chunk_path, "rb") as f:
                files = {"file": (Path(chunk_path).name, f, "audio/wav")}
                headers = {"Authorization": f"Bearer {self._api_key}"}
                try:
                    r = requests.post(_ENDPOINT, headers=headers, data=data,
                                      files=files, timeout=900)
                except requests.RequestException as e:
                    raise CloudTransportError(
                        f"OpenAI: gagal menghubungi API — {e}"
                    ) from e

            _raise_for_status(r, "OpenAI")

            try:
                payload = r.json()
            except ValueError as e:
                raise CloudTransportError(
                    f"OpenAI: response bukan JSON valid — {r.text[:200]}"
                ) from e

            segs = payload.get("segments") or []
            detected_lang = payload.get("language", "") or lang_param or ""

            for s in segs:
                if cancelled(cancel_event):
                    return
                yield AsrSegment(
                    start=offset + float(s.get("start", 0.0)),
                    end=offset + float(s.get("end", 0.0)),
                    text=(s.get("text") or "").strip(),
                    language=detected_lang,
                    words=[],
                )
            emit_progress(progress, (i + 1) / total_chunks,
                          (segs[-1]["text"] if segs else "")[:60])
