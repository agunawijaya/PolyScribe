"""Kontrak diarization.

Plan A (sherpa-onnx) dan plan B (pyannote) sama-sama mewarisi ini, jadi pipeline
tidak peduli yang mana. Jumlah pembicara SELALU auto-detect — tidak ada argumen
jumlah speaker di kontrak ini, dan itu disengaja.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SpeakerTurn:
    """Satu potongan waktu di mana SATU orang bicara."""
    start: float          # detik
    end: float            # detik
    speaker: str          # label stabil, mis. "SPEAKER_00"


class Diarizer(ABC):
    name: str = "diarizer"     # untuk log & pemilihan di config

    @abstractmethod
    def load(self) -> None:
        """Muat model ke memori. Dipanggil sekali sebelum diarize()."""

    @abstractmethod
    def diarize(self, wav_16k_mono_path: str, progress,
                stereo_path: str | None = None) -> list[SpeakerTurn]:
        """
        Terima path WAV 16k mono, kembalikan daftar giliran bicara terurut.
        Jumlah pembicara DIDETEKSI OTOMATIS — tidak ada argumen jumlah speaker.

        stereo_path: WAV 16k STEREO opsional (brief 25). Bila diberi & backend
        mendukungnya, isyarat arah (ILD/ITD) dipakai untuk memperbaiki clustering.
        Backend yang tak peduli stereo boleh mengabaikannya — kontrak tetap sama.
        """
