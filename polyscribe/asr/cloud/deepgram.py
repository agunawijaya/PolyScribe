"""Backend: Deepgram Nova-3 (kualitas tertinggi, native diarization).

Endpoint: POST https://api.deepgram.com/v1/listen dgn body audio langsung (bukan
multipart). Model: nova-3. Deepgram tak punya batas ukuran ketat (up to 2 GB),
jadi kita kirim seluruh WAV tanpa chunker — mereka handle streaming di sisi
server.

Word-timestamp diberikan; speaker labels juga (kita mengabaikannya — pipeline
tetap pakai pyannote/sherpa lokal untuk konsistensi lintas-provider). Yang
kita ambil: paragraph.sentences dgn word-level timestamps -> AsrSegment +
list Word yg tepat -> pipeline._remerge_wordlevel dapat presisi kalimat.
"""

from typing import Iterator

from .base import (
    CloudAsrBackend, CloudTransportError,
    AsrSegment, Word, emit_progress, cancelled,
)
from .groq import _raise_for_status


_ENDPOINT = "https://api.deepgram.com/v1/listen"


class DeepgramNovaBackend(CloudAsrBackend):
    name = "cloud:deepgram"
    provider_key = "deepgram"
    needs_key = True
    has_diarization = True   # informational — pipeline tetap diarize lokal
    has_timestamps = True

    def __init__(self, config):
        super().__init__(config)
        # Cache untuk refine_segments() — sama pola dgn FasterWhisperBackend.
        self._cached_segments: list[AsrSegment] = []
        self._completed_ok = False

    def transcribe(self, wav_16k_mono_path: str, progress,
                   cancel_event=None) -> Iterator[AsrSegment]:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError(
                "Backend Deepgram butuh library `requests`. "
                "Jalankan: pip install -r requirements-cloud.txt"
            ) from e

        self._cached_segments = []
        self._completed_ok = False

        lang = getattr(self.config, "primary_language", "en")
        params = {
            "model": "nova-3",
            "smart_format": "true",     # tanda baca + kapitalisasi
            "punctuate": "true",
            "paragraphs": "true",       # butuh untuk struktur kalimat
            "utterances": "true",       # penanda giliran bicara
        }
        # Deepgram: language=multi = code-switching bebas; kalau user kunci
        # bahasa, kita hormati.
        if lang not in ("auto", "", None):
            params["language"] = lang
        else:
            params["language"] = "multi"

        emit_progress(progress, 0.0, "Deepgram: mengunggah…")

        with open(wav_16k_mono_path, "rb") as f:
            audio_bytes = f.read()

        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "audio/wav",
        }
        try:
            r = requests.post(_ENDPOINT, headers=headers, params=params,
                              data=audio_bytes, timeout=1800)
        except requests.RequestException as e:
            raise CloudTransportError(
                f"Deepgram: gagal menghubungi API — {e}"
            ) from e

        _raise_for_status(r, "Deepgram")

        try:
            data = r.json()
        except ValueError as e:
            raise CloudTransportError(
                f"Deepgram: response bukan JSON valid — {r.text[:200]}"
            ) from e

        results = data.get("results") or {}
        channel = (results.get("channels") or [{}])[0]
        alt = (channel.get("alternatives") or [{}])[0]
        detected_lang = channel.get("detected_language", "") or lang or ""

        # Struktur Deepgram: alternatives[0] punya `paragraphs.paragraphs[].sentences[]`
        # (dgn start/end per kalimat) dan `words[]` (dgn start/end/word per kata).
        # Pakai kalimat sebagai batas segment; ambil words yg overlap sbg Word list.
        sentences = _extract_sentences(alt)
        all_words = alt.get("words") or []

        total_dur = 0.0
        if all_words:
            total_dur = float(all_words[-1].get("end", 0.0))

        for i, sent in enumerate(sentences):
            if cancelled(cancel_event):
                return
            start = float(sent.get("start", 0.0))
            end = float(sent.get("end", start))
            text = (sent.get("text") or "").strip()
            if not text:
                continue
            # Ambil kata yg jatuh di dalam [start, end] — Deepgram tak me-link
            # langsung sentence -> words, jadi filter by overlap.
            words = [
                Word(start=float(w.get("start", 0.0)),
                     end=float(w.get("end", 0.0)),
                     text=str(w.get("punctuated_word") or w.get("word") or ""))
                for w in all_words
                if start - 0.05 <= float(w.get("start", 0.0)) <= end + 0.05
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
        """Sama kontrak dgn FasterWhisperBackend: dipanggil pipeline setelah
        stream selesai NORMAL. Deepgram beri word timestamps -> jalur word-level
        refine benar-benar bekerja (atribusi per-kalimat lebih presisi)."""
        if not self._completed_ok or not self._cached_segments:
            return None
        return list(self._cached_segments)


def _extract_sentences(alt: dict) -> list[dict]:
    """Terbitkan daftar {start, end, text} dari struktur Deepgram.

    Prioritas: alt.paragraphs.paragraphs[].sentences[] (yg sudah dipecah rapi).
    Fallback: alt.utterances[] atau satu segmen utuh dari alt.transcript.
    """
    paras = ((alt.get("paragraphs") or {}).get("paragraphs")) or []
    sentences = []
    for p in paras:
        for s in (p.get("sentences") or []):
            sentences.append(s)
    if sentences:
        return sentences

    # Fallback: utterances (per-giliran, tak selalu ada).
    for u in (alt.get("utterances") or []):
        sentences.append({
            "start": u.get("start"),
            "end": u.get("end"),
            "text": u.get("transcript") or "",
        })
    if sentences:
        return sentences

    # Terakhir: satu segmen utuh dari transcript flat.
    text = alt.get("transcript") or ""
    if text.strip():
        end = 0.0
        words = alt.get("words") or []
        if words:
            end = float(words[-1].get("end", 0.0))
        return [{"start": 0.0, "end": end, "text": text}]
    return []
