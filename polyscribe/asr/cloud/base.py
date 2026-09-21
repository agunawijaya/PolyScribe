"""Basis bersama untuk semua backend cloud.

Perbedaan utama dgn backend lokal:
- `load()` tak memuat model — cukup validasi API key ada (kecuali provider tanpa
  key seperti Google Web Speech).
- `transcribe()` mengirim audio ke HTTP endpoint, mem-parse hasil, meng-emit
  segmen. Chunking dilakukan di sini kalau provider punya batas ukuran.
- Rate limit / 401 / kuota habis dipetakan ke exception yg pesan-nya ramah GUI.
"""

from typing import Iterator, Optional

from .. import base as _base
from ..base import AsrBackend, AsrSegment, Word
from ...progress import ProgressEvent


class CloudAuthError(RuntimeError):
    """API key tak valid / hilang. Pesan-nya sudah siap-tampil untuk user."""


class CloudQuotaError(RuntimeError):
    """Rate limit / kuota habis. Pesan menyebut nama provider & saran."""


class CloudTransportError(RuntimeError):
    """Masalah jaringan / server / format response tak terduga."""


class CloudAsrBackend(AsrBackend):
    """Basis backend cloud.

    Subclass wajib override `name`, `provider_key` (nama utk keystore), dan
    `transcribe()`. Boleh override `load()` untuk validasi tambahan (mis. cek
    project ID di Google Cloud atau region di Azure).

    Field `has_diarization`/`has_timestamps` HANYA memberi tahu pemakai bahwa
    provider ini bisa/tak bisa; PolyScribe tetap pakai diarization LOKAL untuk
    speaker labels (lihat CLAUDE.md batasan 10). Timestamp cloud dipakai kalau
    ada — kalau tidak, pipeline generate pseudo-linear.
    """

    name: str = "cloud"
    provider_key: str = ""              # slug utk keystore (mis. "deepgram")
    needs_key: bool = True
    has_diarization: bool = False       # kapabilitas provider, INFO saja
    has_timestamps: bool = True         # kalau False, kita generate pseudo

    def __init__(self, config):
        self.config = config
        self._api_key: Optional[str] = None

    def load(self) -> None:
        """Validasi key ada di keystore. Backend gratis (Google Web Speech) tak
        perlu key -> override & tak melempar."""
        if not self.needs_key:
            return
        from ... import keystore
        key = keystore.get_key(self.provider_key)
        if not key:
            raise CloudAuthError(
                f"API key {self.provider_key} belum di-set. Buka GUI tab "
                "'Backend & API Keys' untuk memasangnya."
            )
        self._api_key = key

    def transcribe(self, wav_16k_mono_path: str, progress,
                   cancel_event=None) -> Iterator[AsrSegment]:
        raise NotImplementedError


def emit_progress(progress, fraction: float, snippet: str = "") -> None:
    """Helper: emit event 'transcribe' dgn fraction clamped [0, 1]."""
    progress.emit(ProgressEvent(
        stage="transcribe",
        fraction=max(0.0, min(1.0, fraction)),
        message="transkripsi (cloud)",
        text_snippet=snippet,
    ))


def cancelled(cancel_event) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def pseudo_segments_from_text(text: str, total_duration: float,
                              language: str = "") -> list[AsrSegment]:
    """Backend tanpa timestamp (Google Web Speech): pecah teks jadi segmen dgn
    waktu didistribusi linear. Bukan akurat, tapi cukup supaya merge.py bisa
    memetakan speaker turn -> teks. Ditandai dgn language yg apa adanya (kalau
    provider tak beri, kosong)."""
    text = (text or "").strip()
    if not text:
        return []
    # Pecah kasar per kalimat. `_SENT_END` mencakup titik/tanya/seru Latin dan
    # `؟ ۔` untuk Arab (dari brief 53). Kalau tak ada tanda baca, satu segmen
    # utuh — bukan kondisi bagus, tapi tidak crash.
    import re
    sentences = [s.strip() for s in re.split(r'(?<=[.!?؟۔])\s+', text) if s.strip()]
    if not sentences:
        sentences = [text]
    per = total_duration / max(1, len(sentences))
    segs = []
    for i, sent in enumerate(sentences):
        segs.append(AsrSegment(
            start=i * per,
            end=(i + 1) * per,
            text=sent,
            language=language,
            words=[],   # tanpa word-timestamp -> refine_segments tak jalan
        ))
    return segs


def chunk_wav(wav_path: str, max_bytes: int = 24 * 1024 * 1024,
              chunk_seconds: float = 300.0) -> list[tuple[float, str]]:
    """Pecah WAV panjang jadi potongan supaya lolos batas ukuran provider
    (mis. OpenAI/Groq 25 MB). Kembalikan list of (start_offset_seconds, path).

    Strategi sederhana: kalau file sudah <= max_bytes, kembalikan satu entri.
    Kalau tidak, potong per `chunk_seconds` di batas frame WAV. Batas kalimat
    diabaikan — cloud provider yg tak beri timestamp akan tetap dapat text
    utuh via concat; yg beri timestamp akan dapat offset yg benar (kita geser
    start/end tiap segmen dengan chunk offset).

    Bukan optimizer WAV cerdas; cukup untuk memenuhi batas. Kalau perlu VAD-aware
    chunk (potong di silence), bisa ditambah nanti.
    """
    import os
    import wave
    size = os.path.getsize(wav_path)
    if size <= max_bytes:
        return [(0.0, wav_path)]

    from pathlib import Path
    out_dir = Path(wav_path).parent
    stem = Path(wav_path).stem
    chunks: list[tuple[float, str]] = []

    with wave.open(wav_path, "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        n_frames = w.getnframes()
        frames_per_chunk = int(chunk_seconds * rate)
        i = 0
        offset = 0.0
        while offset < n_frames / rate:
            w.setpos(int(offset * rate))
            frames = w.readframes(min(frames_per_chunk, n_frames - int(offset * rate)))
            if not frames:
                break
            out_path = str(out_dir / f"{stem}_chunk{i:03d}.wav")
            with wave.open(out_path, "wb") as ow:
                ow.setnchannels(channels)
                ow.setsampwidth(sampwidth)
                ow.setframerate(rate)
                ow.writeframes(frames)
            chunks.append((offset, out_path))
            offset += chunk_seconds
            i += 1
    return chunks


__all__ = [
    "CloudAsrBackend", "CloudAuthError", "CloudQuotaError", "CloudTransportError",
    "emit_progress", "cancelled", "pseudo_segments_from_text", "chunk_wav",
    "AsrSegment", "Word",
]
