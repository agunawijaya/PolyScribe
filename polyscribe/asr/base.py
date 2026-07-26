"""Kontrak transkripsi (ASR).

Backend CPU (faster-whisper) dan backend Vulkan (whisper.cpp) sama-sama ikut
kontrak ini, jadi pipeline tidak peduli yang mana yang dipakai. Ganti backend =
ganti satu kelas.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class AsrSegment:
    start: float
    end: float
    text: str
    language: str                 # hasil deteksi otomatis per segmen
    words: list[Word] = field(default_factory=list)   # boleh kosong -> fallback


class AsrBackend(ABC):
    """Kontrak transkripsi. Backend CPU dan backend Vulkan sama-sama ikut ini."""

    name: str = "asr"

    @abstractmethod
    def load(self) -> None:
        """Muat model sekali sebelum transcribe()."""

    @abstractmethod
    def transcribe(self, wav_16k_mono_path: str, progress,
                   cancel_event=None) -> Iterator[AsrSegment]:
        """
        Kembalikan segmen SATU PER SATU (generator), bukan sekaligus.
        Kenapa generator: biar UI bisa menampilkan teks & progress SELAGI
        transkripsi jalan, tidak menunggu sampai selesai. Tiap kali sebuah
        segmen dihasilkan, backend memanggil progress dengan posisi waktu
        terakhir (segment.end) supaya indikator bergerak.

        cancel_event: threading.Event opsional. Bila di-set di tengah jalan,
        backend berhenti secepatnya (backend subprocess mematikan prosesnya).
        Default None = tak bisa dibatalkan (perilaku lama, dipakai CLI).
        """
