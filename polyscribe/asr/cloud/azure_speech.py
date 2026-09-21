"""Backend: Azure Speech (Batch Transcription API v3.2).

Azure BUKAN simple upload-and-transcribe seperti provider lain — flow-nya:
(1) unggah audio ke Azure Blob dulu, ATAU (2) pakai "transcriptions" endpoint
yg terima audio langsung via multipart. Kita pakai (2) — Fast Transcription API
(preview) yg async & tak butuh Blob Storage.

Endpoint: POST /speechtotext/v3.2/transcriptions:submit dgn multipart body
audio + JSON definition. Poll GET /speechtotext/v3.2/transcriptions/{id}.

Butuh dua field dari user: API key + REGION (mis. 'eastus', 'southeastasia').
Region disimpan di keystore sebagai key terpisah "azure_speech_region".
"""

import time
from pathlib import Path
from typing import Iterator

from .base import (
    CloudAsrBackend, CloudAuthError, CloudTransportError,
    AsrSegment, Word, emit_progress, cancelled,
)
from .groq import _raise_for_status


class AzureSpeechBackend(CloudAsrBackend):
    name = "cloud:azure_speech"
    provider_key = "azure_speech"
    needs_key = True
    has_diarization = True
    has_timestamps = True

    def __init__(self, config):
        super().__init__(config)
        self._region: str = ""
        self._cached_segments: list[AsrSegment] = []
        self._completed_ok = False

    def load(self) -> None:
        super().load()
        # Azure butuh region — disimpan di keystore sbg entri terpisah.
        from ... import keystore
        region = keystore.get_key("azure_speech_region")
        if not region:
            raise CloudAuthError(
                "Azure Speech butuh REGION selain API key. Pasang di GUI tab "
                "'Backend & API Keys' -> Azure Speech -> Region (mis. 'eastus')."
            )
        self._region = region.strip().lower()

    def transcribe(self, wav_16k_mono_path: str, progress,
                   cancel_event=None) -> Iterator[AsrSegment]:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError(
                "Backend Azure butuh library `requests`. "
                "Jalankan: pip install -r requirements-cloud.txt"
            ) from e

        self._cached_segments = []
        self._completed_ok = False

        lang = getattr(self.config, "primary_language", "en")
        # BCP-47 code untuk Azure.
        locale = _azure_locale(lang)

        base = f"https://{self._region}.api.cognitive.microsoft.com/speechtotext"
        endpoint = f"{base}/transcriptions:transcribe?api-version=2024-11-15"
        headers = {"Ocp-Apim-Subscription-Key": self._api_key}

        definition = {
            "locales": [locale] if locale else None,
            "diarizationEnabled": True,        # info saja; pipeline pakai lokal
            "profanityFilterMode": "None",
            "channels": [0],
        }
        # Kalau lang auto, hapus locales supaya Azure deteksi otomatis.
        if not locale:
            definition.pop("locales", None)
            definition["languageIdentification"] = {"candidateLocales":
                                                    ["en-US", "ar-EG", "id-ID"]}

        emit_progress(progress, 0.05, "Azure: mengunggah…")
        import json as _json
        with open(wav_16k_mono_path, "rb") as f:
            files = {
                "audio": (Path(wav_16k_mono_path).name, f, "audio/wav"),
                "definition": (None, _json.dumps(definition), "application/json"),
            }
            try:
                r = requests.post(endpoint, headers=headers, files=files,
                                  timeout=1800)
            except requests.RequestException as e:
                raise CloudTransportError(f"Azure: {e}") from e
        _raise_for_status(r, "Azure")

        try:
            data = r.json()
        except ValueError as e:
            raise CloudTransportError(
                f"Azure: response bukan JSON valid — {r.text[:200]}"
            ) from e

        # Response Fast Transcription = sinkron; berisi `combinedPhrases` &
        # `phrases[]` dgn offset/duration dalam milidetik/tick.
        phrases = data.get("phrases") or []
        detected_lang = ""
        if phrases:
            detected_lang = phrases[0].get("locale", "") or lang or ""

        total_dur = 0.0
        if phrases:
            last = phrases[-1]
            total_dur = (last.get("offsetMilliseconds", 0)
                         + last.get("durationMilliseconds", 0)) / 1000.0

        for i, ph in enumerate(phrases):
            if cancelled(cancel_event):
                return
            start = ph.get("offsetMilliseconds", 0) / 1000.0
            end = start + ph.get("durationMilliseconds", 0) / 1000.0
            text = (ph.get("text") or "").strip()
            if not text:
                continue
            # Word-level ada di ph.words[] dgn offset/duration ms.
            words = []
            for w in (ph.get("words") or []):
                w_start = w.get("offsetMilliseconds", 0) / 1000.0
                w_end = w_start + w.get("durationMilliseconds", 0) / 1000.0
                words.append(Word(start=w_start, end=w_end,
                                  text=w.get("text", "")))
            seg = AsrSegment(
                start=start, end=end, text=text,
                language=detected_lang, words=words,
            )
            self._cached_segments.append(seg)
            emit_progress(progress,
                          end / total_dur if total_dur else (i + 1) / len(phrases),
                          text[:60])
            yield seg

        self._completed_ok = True

    def refine_segments(self):
        if not self._completed_ok or not self._cached_segments:
            return None
        return list(self._cached_segments)


def _azure_locale(lang: str) -> str:
    """Peta bahasa PolyScribe -> BCP-47 Azure. Kosong = auto."""
    if lang in ("auto", "", None):
        return ""
    return {
        "en": "en-US",
        "ar": "ar-EG",
        "id": "id-ID",
    }.get(lang, lang)
