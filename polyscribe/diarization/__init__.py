"""Pemilihan backend diarization.

Brief 37: default = "pyannote" (mode "Akurat"). Karena pyannote adalah plan B yang
dependency-nya (torch ~GB) & model-nya (ter-gate) HARUS dibundel manual, selector di
sini WAJIB jatuh aman ke "sherpa" bila pyannote tak siap — jangan pernah crash hanya
karena model plan B belum terpasang. UI (GUI/CLI) memakai `pyannote_availability()`
untuk menampilkan pesan ramah SEBELUM menjalankan; `select_diarizer()` mengulang cek
yang sama sebagai jaring pengaman terakhir (mis. dipanggil dari jalur non-UI).
"""

import importlib.util

from .base import Diarizer, SpeakerTurn
from ..progress import ProgressEvent


def pyannote_availability(config) -> tuple[bool, str]:
    """Apakah jalur pyannote siap dipakai? Kembalikan (siap, alasan_ramah).

    Dua syarat, dicek MURAH tanpa mengimpor torch (find_spec hanya cari modul, tak
    menjalankannya) atau memuat model:
      1. paket `torch` + `pyannote.audio` terpasang;
      2. model community-1 terbundel (config.yaml ada di models/diarization/pyannote/).
    Kalau salah satu gagal, `select_diarizer` jatuh ke sherpa & UI memakai `alasan`
    ini sebagai pesan. Saat siap, alasan = "" (string kosong)."""
    have_torch = importlib.util.find_spec("torch") is not None
    have_pyannote = importlib.util.find_spec("pyannote.audio") is not None
    if not (have_torch and have_pyannote):
        return False, ("Mode Akurat butuh PyTorch + pyannote.audio (dependency plan B, "
                       "~GB). Pasang: pip install -r requirements-pyannote.txt")

    config_yaml = config.diarization_dir / "pyannote" / "config.yaml"
    if not config_yaml.exists():
        return False, ("Mode Akurat butuh model pyannote yang belum terpasang. "
                       "Jalankan: python scripts/download_models.py --only pyannote "
                       "--hf-token <T> (sekali, terima lisensi di HF dulu).")

    return True, ""


def select_diarizer(config) -> Diarizer:
    choice = getattr(config, "diarizer_choice", "pyannote")

    if choice == "pyannote":
        ready, _reason = pyannote_availability(config)
        if ready:
            from .pyannote_backend import PyannoteDiarizer
            return PyannoteDiarizer(config)
        # Jaring pengaman: pyannote diminta tapi tak siap -> JANGAN crash, pakai
        # sherpa. UI idealnya sudah menukar & memberi tahu user lebih dulu; ini
        # menjaga jalur non-UI (CLI langsung / test) tetap jalan.

    from .sherpa_onnx_backend import SherpaOnnxDiarizer
    return SherpaOnnxDiarizer(config)


def load_diarizer_with_fallback(diarizer, config, sink=None) -> Diarizer:
    """Muat diarizer, tangkap kegagalan RUNTIME pyannote, jatuh anggun ke sherpa.

    KENAPA ADA (brief 43): `pyannote_availability()` cuma memastikan paket + model
    ADA — cek murah lewat find_spec, tak menjalankan apa pun. Itu LOLOS walau
    runtime-nya sebetulnya rusak (mis. lazy-import speechbrain menuntut k2 yang tak
    terpasang -> Pipeline.from_pretrained meledak). Kegagalan sejati baru muncul saat
    load() benar-benar memuat pipeline. Di sinilah kita menangkapnya.

    Aturan keras: aplikasi TAK BOLEH mati dengan dialog mentah karena bug pyannote.
    Maka APA PUN error saat memuat pyannote (ImportError, OSError, RuntimeError, ...)
    -> pesan ramah + fallback ke sherpa, supaya .txt tetap jadi. Ini menjaga app
    dari bug pyannote MASA DEPAN juga, bukan cuma P0 hari ini.

    Kembalikan diarizer yang BENAR-BENAR termuat (bisa jadi sudah ditukar ke sherpa)."""
    try:
        diarizer.load()
        return diarizer
    except Exception as exc:
        # Hanya pyannote (Akurat) yang punya cadangan Cepat. Kalau sherpa sendiri yang
        # gagal, tak ada jalan lain -> biarkan error naik (bukan kondisi yang bisa
        # "dianggunkan").
        if getattr(diarizer, "name", "") != "pyannote":
            raise

        detail = f"{type(exc).__name__}: {exc}"
        if len(detail) > 200:
            detail = detail[:197] + "..."
        note = ("Mode Akurat tak tersedia (gagal memuat pyannote), memakai mode Cepat. "
                f"[{detail}]")
        if sink is not None:
            # text_snippet supaya muncul di area teks GUI & baris cuplikan CLI; message
            # untuk pendengar yang membaca message.
            sink.emit(ProgressEvent(stage="load", fraction=0.0,
                                    message=note, text_snippet=note))

        from .sherpa_onnx_backend import SherpaOnnxDiarizer
        fallback = SherpaOnnxDiarizer(config)
        fallback.load()
        return fallback


__all__ = ["Diarizer", "SpeakerTurn", "select_diarizer", "pyannote_availability",
           "load_diarizer_with_fallback"]
