"""Saluran progress dari mesin ke UI.

Mesin tidak tahu siapa yang mendengar — CLI (cetak ke layar) atau GUI (gerakkan
progress bar). Dia cuma memanggil sink.emit(event). Kontrak ini sengaja tipis.
"""

from dataclasses import dataclass


# Tahap-tahap resmi. Dipakai konsisten oleh pipeline & sink.
STAGES = ("load", "transcribe", "diarize", "merge", "done")


@dataclass
class ProgressEvent:
    stage: str              # salah satu dari STAGES
    fraction: float         # 0.0..1.0 untuk tahap berjalan (mis. waktu audio / total)
    message: str = ""       # teks tahap, mis. "memuat model"
    text_snippet: str = ""  # cuplikan teks terbaru untuk ditampilkan


class ProgressSink:
    """
    Tujuan laporan progress. CLI mengisinya dengan print; GUI mengisinya dengan
    menaruh event ke queue.Queue yang dibaca thread UI.
    """

    def emit(self, event: ProgressEvent) -> None:
        raise NotImplementedError


class NullSink(ProgressSink):
    """Buang semua event — berguna untuk test/benchmark yang tak mau ramai."""

    def emit(self, event: ProgressEvent) -> None:
        pass
