"""Backend: Google Cloud Speech-to-Text (chirp_2). BUKAN Google Web Speech.

Ini yang RESMI dari Google Cloud (butuh billing account & project). Sengaja
namanya dipisah supaya tak tertukar dgn `google_web` (endpoint demo tak resmi).

Flow: POST https://speech.googleapis.com/v2/projects/{project}/locations/global
/recognizers/_:recognize dgn body JSON berisi audio (base64) + config.

Butuh dua field dari user: API key + PROJECT ID. Project ID disimpan di keystore
sebagai entri terpisah "google_cloud_project".
"""

import base64
from typing import Iterator

from .base import (
    CloudAsrBackend, CloudAuthError, CloudTransportError,
    AsrSegment, Word, emit_progress, cancelled,
)
from .groq import _raise_for_status


class GoogleCloudSpeechBackend(CloudAsrBackend):
    name = "cloud:google_cloud"
    provider_key = "google_cloud"
    needs_key = True
    has_diarization = True
    has_timestamps = True

    def __init__(self, config):
        super().__init__(config)
        self._project: str = ""
        self._cached_segments: list[AsrSegment] = []
        self._completed_ok = False

    def load(self) -> None:
        super().load()
        from ... import keystore
        project = keystore.get_key("google_cloud_project")
        if not project:
            raise CloudAuthError(
                "Google Cloud Speech butuh PROJECT ID selain API key. Pasang di "
                "GUI tab 'Backend & API Keys' -> Google Cloud Speech -> Project ID."
            )
        self._project = project.strip()

    def transcribe(self, wav_16k_mono_path: str, progress,
                   cancel_event=None) -> Iterator[AsrSegment]:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError(
                "Backend Google Cloud butuh library `requests`. "
                "Jalankan: pip install -r requirements-cloud.txt"
            ) from e

        self._cached_segments = []
        self._completed_ok = False

        lang = getattr(self.config, "primary_language", "en")
        # chirp_2 mendukung banyak locale + auto detection kalau kita beri `["auto"]`.
        locales = _google_locales(lang)

        endpoint = (
            f"https://speech.googleapis.com/v2/projects/{self._project}"
            "/locations/global/recognizers/_:recognize"
        )
        params = {"key": self._api_key}

        emit_progress(progress, 0.05, "Google Cloud: mengunggah…")
        with open(wav_16k_mono_path, "rb") as f:
            audio_bytes = f.read()

        body = {
            "config": {
                "autoDecodingConfig": {},   # deteksi format dari header WAV
                "model": "chirp_2",
                "languageCodes": locales,
                "features": {
                    "enableAutomaticPunctuation": True,
                    "enableWordTimeOffsets": True,
                    "diarizationConfig": {   # info saja; pipeline pakai lokal
                        "minSpeakerCount": 1,
                        "maxSpeakerCount": 8,
                    },
                },
            },
            "content": base64.b64encode(audio_bytes).decode("ascii"),
        }

        try:
            r = requests.post(endpoint, params=params, json=body, timeout=1800)
        except requests.RequestException as e:
            raise CloudTransportError(f"Google Cloud: {e}") from e
        _raise_for_status(r, "Google Cloud")

        try:
            data = r.json()
        except ValueError as e:
            raise CloudTransportError(
                f"Google Cloud: response bukan JSON valid — {r.text[:200]}"
            ) from e

        results = data.get("results") or []
        detected_lang = ""
        if results:
            detected_lang = results[0].get("languageCode", "") or lang or ""

        # Google beri satu `result` per "utterance" dgn alternatives[0].transcript
        # dan alternatives[0].words[] (masing2 dgn startOffset/endOffset "1.23s").
        total_dur = 0.0
        for res in results:
            for w in ((res.get("alternatives") or [{}])[0].get("words") or []):
                t = _parse_offset(w.get("endOffset", "0s"))
                total_dur = max(total_dur, t)

        for i, res in enumerate(results):
            if cancelled(cancel_event):
                return
            alt = (res.get("alternatives") or [{}])[0]
            text = (alt.get("transcript") or "").strip()
            if not text:
                continue
            words_raw = alt.get("words") or []
            words = []
            for w in words_raw:
                words.append(Word(
                    start=_parse_offset(w.get("startOffset", "0s")),
                    end=_parse_offset(w.get("endOffset", "0s")),
                    text=w.get("word", ""),
                ))
            start = words[0].start if words else 0.0
            end = words[-1].end if words else start
            seg = AsrSegment(
                start=start, end=end, text=text,
                language=detected_lang, words=words,
            )
            self._cached_segments.append(seg)
            emit_progress(progress,
                          end / total_dur if total_dur else (i + 1) / len(results),
                          text[:60])
            yield seg

        self._completed_ok = True

    def refine_segments(self):
        if not self._completed_ok or not self._cached_segments:
            return None
        return list(self._cached_segments)


def _google_locales(lang: str) -> list[str]:
    if lang in ("auto", "", None):
        return ["en-US", "ar-EG", "id-ID"]   # kandidat auto-detect
    return {
        "en": ["en-US"],
        "ar": ["ar-EG"],
        "id": ["id-ID"],
    }.get(lang, [lang])


def _parse_offset(s: str) -> float:
    """Google beri durasi sebagai string '1.234s'. Kembalikan detik (float)."""
    if isinstance(s, (int, float)):
        return float(s)
    if not isinstance(s, str):
        return 0.0
    return float(s.rstrip("s") or 0)
