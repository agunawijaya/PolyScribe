"""Backend: Groq — Whisper large-v3 via LPU (termurah + tercepat).

Groq punya endpoint OpenAI-compatible untuk transcription (POST multipart ke
/openai/v1/audio/transcriptions). Model: whisper-large-v3. Batas ukuran 25 MB
per request -> pakai chunker dari base.py.

Kenapa jadi rekomendasi utama:
- Model SAMA dgn PolyScribe offline (Whisper large-v3) jadi hasil bisa
  dibandingkan langsung dgn baseline lokal user;
- 200-300x realtime -> file 1 jam selesai dlm ~15-20 dtk;
- Harga ~$0.04/jam per September 2026 (paling murah dari 7 provider ini).
"""

import json
from pathlib import Path
from typing import Iterator

from .base import (
    CloudAsrBackend, CloudAuthError, CloudQuotaError, CloudTransportError,
    AsrSegment, Word, emit_progress, cancelled, chunk_wav,
)


_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
_MODEL = "whisper-large-v3"


class GroqWhisperBackend(CloudAsrBackend):
    name = "cloud:groq"
    provider_key = "groq"
    needs_key = True
    has_diarization = False
    has_timestamps = True

    def transcribe(self, wav_16k_mono_path: str, progress,
                   cancel_event=None) -> Iterator[AsrSegment]:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError(
                "Backend Groq butuh library `requests`. "
                "Jalankan: pip install -r requirements-cloud.txt"
            ) from e

        lang = getattr(self.config, "primary_language", "en")
        # Groq mengikuti kode Whisper (2-huruf) atau None untuk auto.
        lang_param = None if lang in ("auto", "", None) else lang

        chunks = chunk_wav(wav_16k_mono_path)
        total_chunks = len(chunks)

        for i, (offset, chunk_path) in enumerate(chunks):
            if cancelled(cancel_event):
                return

            data = {
                "model": _MODEL,
                "response_format": "verbose_json",   # supaya dapat segments
                "timestamp_granularities[]": "segment",
            }
            if lang_param:
                data["language"] = lang_param

            with open(chunk_path, "rb") as f:
                files = {"file": (Path(chunk_path).name, f, "audio/wav")}
                headers = {"Authorization": f"Bearer {self._api_key}"}
                try:
                    r = requests.post(_ENDPOINT, headers=headers, data=data,
                                      files=files, timeout=600)
                except requests.RequestException as e:
                    raise CloudTransportError(
                        f"Groq: gagal menghubungi API — {e}"
                    ) from e

            _raise_for_status(r, "Groq")

            try:
                payload = r.json()
            except ValueError as e:
                raise CloudTransportError(
                    f"Groq: response bukan JSON valid — {r.text[:200]}"
                ) from e

            segs = payload.get("segments") or []
            detected_lang = payload.get("language", "") or lang_param or ""

            if not segs and payload.get("text"):
                # Response tanpa segments (mode tertentu) -> satu segmen untuk
                # seluruh chunk. Kondisi jarang tapi cover-nya murah.
                yield AsrSegment(
                    start=offset, end=offset + 30.0,
                    text=payload["text"].strip(),
                    language=detected_lang, words=[],
                )
            for s in segs:
                if cancelled(cancel_event):
                    return
                yield AsrSegment(
                    start=offset + float(s.get("start", 0.0)),
                    end=offset + float(s.get("end", 0.0)),
                    text=(s.get("text") or "").strip(),
                    language=detected_lang,
                    words=[],   # Groq beri word timestamps lewat granularity
                                # terpisah — belum dipakai (perlu request kedua)
                )
            emit_progress(progress, (i + 1) / total_chunks,
                          (segs[-1]["text"] if segs else "")[:60])


def _raise_for_status(r, provider: str) -> None:
    """Petakan HTTP status ke exception PolyScribe yg pesannya ramah."""
    if 200 <= r.status_code < 300:
        return
    body = r.text[:400]
    if r.status_code == 401 or r.status_code == 403:
        raise CloudAuthError(
            f"{provider}: API key ditolak (HTTP {r.status_code}). Cek key di "
            f"GUI tab 'Backend & API Keys'. Detail: {body}"
        )
    if r.status_code == 429:
        raise CloudQuotaError(
            f"{provider}: rate limit / kuota habis (HTTP 429). Tunggu, "
            f"atau ganti backend. Detail: {body}"
        )
    if 500 <= r.status_code < 600:
        raise CloudTransportError(
            f"{provider}: server error (HTTP {r.status_code}). Coba lagi. "
            f"Detail: {body}"
        )
    raise CloudTransportError(
        f"{provider}: HTTP {r.status_code}. Detail: {body}"
    )
