"""Backend: AssemblyAI Universal-2.

Flow: (1) upload audio ke /v2/upload -> upload_url, (2) POST /v2/transcript
dgn audio_url, (3) poll /v2/transcript/{id} sampai status = completed/error,
(4) parse hasil word-level + sentence-level.

Batas ukuran: praktis tak ada (upload URL support besar). Async model, jadi
kita tak yield segment progresif — semua langsung setelah completed. Progress
bar diupdate secara kasar (upload, processing, completed).
"""

import time
from typing import Iterator

from .base import (
    CloudAsrBackend, CloudTransportError,
    AsrSegment, Word, emit_progress, cancelled,
)
from .groq import _raise_for_status


_BASE = "https://api.assemblyai.com/v2"


class AssemblyAIBackend(CloudAsrBackend):
    name = "cloud:assemblyai"
    provider_key = "assemblyai"
    needs_key = True
    has_diarization = True
    has_timestamps = True

    def __init__(self, config):
        super().__init__(config)
        self._cached_segments: list[AsrSegment] = []
        self._completed_ok = False

    def transcribe(self, wav_16k_mono_path: str, progress,
                   cancel_event=None) -> Iterator[AsrSegment]:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError(
                "Backend AssemblyAI butuh library `requests`. "
                "Jalankan: pip install -r requirements-cloud.txt"
            ) from e

        self._cached_segments = []
        self._completed_ok = False

        lang = getattr(self.config, "primary_language", "en")
        headers = {"Authorization": self._api_key}

        # 1. Upload
        emit_progress(progress, 0.05, "AssemblyAI: mengunggah…")
        with open(wav_16k_mono_path, "rb") as f:
            try:
                r = requests.post(f"{_BASE}/upload", headers=headers,
                                  data=f, timeout=1800)
            except requests.RequestException as e:
                raise CloudTransportError(f"AssemblyAI upload: {e}") from e
        _raise_for_status(r, "AssemblyAI")
        upload_url = r.json().get("upload_url")

        # 2. Submit transcript
        body = {
            "audio_url": upload_url,
            "punctuate": True,
            "format_text": True,
        }
        if lang not in ("auto", "", None):
            body["language_code"] = lang
        else:
            body["language_detection"] = True

        try:
            r = requests.post(f"{_BASE}/transcript", headers=headers,
                              json=body, timeout=30)
        except requests.RequestException as e:
            raise CloudTransportError(f"AssemblyAI submit: {e}") from e
        _raise_for_status(r, "AssemblyAI")
        job_id = r.json().get("id")

        # 3. Poll
        emit_progress(progress, 0.15, "AssemblyAI: memproses…")
        deadline = time.time() + 3600   # 1 jam max
        while time.time() < deadline:
            if cancelled(cancel_event):
                return
            try:
                r = requests.get(f"{_BASE}/transcript/{job_id}",
                                 headers=headers, timeout=30)
            except requests.RequestException as e:
                raise CloudTransportError(f"AssemblyAI poll: {e}") from e
            _raise_for_status(r, "AssemblyAI")
            data = r.json()
            status = data.get("status")
            if status == "completed":
                break
            if status == "error":
                raise CloudTransportError(
                    f"AssemblyAI menolak file: {data.get('error', 'unknown error')}"
                )
            # `queued` / `processing` — tunggu.
            time.sleep(3.0)
        else:
            raise CloudTransportError(
                "AssemblyAI: timeout 1 jam menunggu transkrip selesai."
            )

        # 4. Parse
        detected_lang = data.get("language_code", "") or lang or ""
        all_words = data.get("words") or []
        # AssemblyAI beri sentences via endpoint terpisah kalau diminta, tapi
        # word-level cukup — kita kelompokkan per kalimat lewat tanda baca.
        sentences = _group_words_into_sentences(all_words)

        total_dur = 0.0
        if all_words:
            total_dur = float(all_words[-1].get("end", 0.0)) / 1000.0

        for i, sent_words in enumerate(sentences):
            if cancelled(cancel_event):
                return
            if not sent_words:
                continue
            start = float(sent_words[0].get("start", 0.0)) / 1000.0
            end = float(sent_words[-1].get("end", 0.0)) / 1000.0
            text = " ".join(w.get("text", "") for w in sent_words).strip()
            words = [
                Word(start=float(w.get("start", 0.0)) / 1000.0,
                     end=float(w.get("end", 0.0)) / 1000.0,
                     text=w.get("text", ""))
                for w in sent_words
            ]
            seg = AsrSegment(
                start=start, end=end, text=text,
                language=detected_lang, words=words,
            )
            self._cached_segments.append(seg)
            emit_progress(progress,
                          end / total_dur if total_dur else (i + 1) / len(sentences),
                          text[:60])
            yield seg

        self._completed_ok = True

    def refine_segments(self):
        if not self._completed_ok or not self._cached_segments:
            return None
        return list(self._cached_segments)


def _group_words_into_sentences(words: list[dict]) -> list[list[dict]]:
    """Kelompokkan kata per kalimat berdasarkan tanda baca akhir. Mengembalikan
    daftar-daftar kata; kalau tak ada tanda baca, seluruh kata jadi satu list."""
    if not words:
        return []
    sentences: list[list[dict]] = []
    current: list[dict] = []
    for w in words:
        current.append(w)
        text = w.get("text", "")
        # `_SENT_END` versi mini — konsisten dgn brief 53 (Arab).
        if text.endswith((".", "!", "?", "؟", "۔")):
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    return sentences
