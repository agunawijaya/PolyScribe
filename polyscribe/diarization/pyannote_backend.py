"""Diarization plan B — pyannote.audio (overlap-aware, embedding lebih tajam).

Kenapa plan B (brief 36): sherpa (plan A) sudah mentok pada dua hal yang ternyata
SATU akar — plafon model:
  - #2 interjeksi cepat dilebur (sherpa tak overlap-aware);
  - Std-12 over-split (embedding CAMPPlus: peserta berbeda 0.573 vs pecahan orang
    sama 0.540 -> distribusinya bertumpang tindih, tak ada ambang yang memisahkan).
pyannote menyerang keduanya: segmentation overlap-aware + embedding WeSpeaker.

Kontrak SAMA dengan sherpa (Diarizer) — pipeline tak berubah, cukup ganti kelas.
Itulah gunanya arsitektur pluggable yang dijaga sejak awal.

BATASAN OFFLINE (keras): model pyannote di HF ter-gate. Token HANYA urusan BUILD
(scripts/download_models.py --only pyannote), sekali. Saat runtime kelas ini memuat
dari `models/diarization/pyannote/` dengan HF_HUB_OFFLINE=1 -> NOL jaringan, tanpa
token. Kalau folder itu tak ada, load() gagal dengan pesan jelas (bukan diam-diam
menembak ke internet).
"""

import os
from pathlib import Path

from .base import Diarizer, SpeakerTurn
from ..progress import ProgressEvent


# Model diarization pyannote 4.x = self-contained (segmentation + embedding + PLDA
# dalam SATU repo ter-gate). speaker-diarization-3.1 adalah model 3.x (tanpa PLDA)
# dan TAK kompatibel dengan kode pipeline 4.x — jadi kita pakai community-1.
PYANNOTE_REPO = "pyannote/speaker-diarization-community-1"


def _pick_pyannote_device(config, torch_mod):
    """Pilih device pyannote — CPU-aman default di GPU sempit.

    AKAR (bug user 2026-08): laptop NVIDIA RTX 4060 8 GB memberi CUDA OOM saat file
    1 jam. faster-whisper large-v3 float16 sudah duduk di GPU (~3,2 GB); sisa ~4 GB
    tak cukup untuk pyannote community-1 memuat model + memproses aktivasi file
    panjang. Kode lama tanpa syarat memilih CUDA bila tersedia -> selalu OOM di
    laptop dgn VRAM sedang. Sekarang tiga mode:
      - "cpu": paksa CPU. Aman, ~2,5x lebih lambat. Rekomendasi default kalau ragu.
      - "cuda": paksa CUDA. Dipakai bila GPU besar (>= ~12 GB) atau ASR di CPU/Vulkan.
      - "auto" (default): CUDA hanya bila torch.cuda.mem_get_info() melaporkan free
        >= config.pyannote_min_free_vram_gb (default 4 GB); kalau tidak, CPU. Cek
        DILAKUKAN SAAT LOAD (sebelum ASR CUDA menyedot VRAM), jadi ambang ini harus
        sudah memperhitungkan bahwa ASR akan menyita ~3,2 GB.
    Diarize() punya lapis kedua: try/except CUDA OOM -> retry CPU (jaring pengaman
    kalau estimasi VRAM meleset).
    """
    choice = str(getattr(config, "pyannote_device", "auto")).lower()
    if choice == "cpu":
        return torch_mod.device("cpu")
    if not torch_mod.cuda.is_available():
        return torch_mod.device("cpu")     # tak ada CUDA -> apa pun choice, CPU
    if choice == "cuda":
        return torch_mod.device("cuda")

    # "auto" — cek free VRAM. mem_get_info kembalikan (free, total) dalam bytes.
    try:
        free_bytes, _total = torch_mod.cuda.mem_get_info()
    except Exception:
        return torch_mod.device("cpu")     # gagal cek -> aman: CPU
    free_gb = free_bytes / (1024 ** 3)
    threshold = float(getattr(config, "pyannote_min_free_vram_gb", 4.0))
    return torch_mod.device("cuda" if free_gb >= threshold else "cpu")


def _turns_from_annotation(annotation) -> list[SpeakerTurn]:
    """Ubah pyannote Annotation -> daftar SpeakerTurn terurut, label distabilkan
    kontigu (SPEAKER_00, 01, ... sesuai urutan kemunculan).

    Dipisah jadi fungsi murni (tanpa torch/pyannote) supaya bisa diuji unit dengan
    Annotation palsu. `annotation.itertracks(yield_label=True)` menghasilkan
    (segment, track, label); segment punya .start & .end (detik)."""
    raw = []
    for segment, _track, label in annotation.itertracks(yield_label=True):
        s, e = float(segment.start), float(segment.end)
        if e > s:
            raw.append((s, e, str(label)))
    raw.sort(key=lambda t: t[0])

    # Nomori ulang label pyannote ("SPEAKER_00"/"SPEAKER_12"/...) jadi kontigu sesuai
    # kemunculan waktu — konsisten dengan janji "label stabil" & jalur sherpa.
    mapping: dict[str, str] = {}
    turns = []
    for s, e, lab in raw:
        if lab not in mapping:
            mapping[lab] = f"SPEAKER_{len(mapping):02d}"
        turns.append(SpeakerTurn(start=s, end=e, speaker=mapping[lab]))
    return turns


def _neutralize_speechbrain_lazy_landmines() -> None:
    """Cegah lazy-import speechbrain menggagalkan runtime pyannote di Windows.

    AKAR (P0 brief 43, lengkap). pyannote menarik speechbrain 1.1, yang menaruh
    banyak "LazyModule"/redirect di sys.modules untuk kompat mundur (mis.
    `speechbrain.k2_integration` -> `...integrations.k2_fsa`, dan redirect ke
    `...integrations.huggingface.wordemb`). Saat pyannote memuat checkpoint,
    Lightning memanggil `inspect.stack()`; `inspect.getmodule()` lalu MENYAPU
    sys.modules dan menjalankan `hasattr(m, '__file__')` pada tiap modul. Untuk
    sebuah LazyModule, probe itu MEMICU import target aslinya — dan target itu bisa
    butuh dependency opsional yang TAK kita pasang (k2; transformers via wordemb),
    sehingga meledak dan menyeret jatuh `Pipeline.from_pretrained`. Diarization
    sendiri TAK memakai k2 maupun transformers (embedding WeSpeaker cukup).

    Yang penting: speechbrain SUDAH punya penjaga untuk skenario ini — bila
    pemanggilnya `inspect.py`, `ensure_module` membatalkan diri dengan AttributeError
    (lihat importutils.py). TAPI cek-nya `filename.endswith("/inspect.py")` memakai
    garis miring DEPAN, jadi MELESET di Windows (path pakai backslash:
    `...\\Lib\\inspect.py`). Itulah kenapa bug ini muncul di laptop user (Windows)
    tapi tak di Linux. Non-deterministik pula: tergantung LazyModule mana yang ada
    di sys.modules saat inspect menyapu.

    Perbaikan (dua lapis, defensif):
      1. Stub `k2` kosong bila absen — menetralkan landmine k2 spesifik yang
         diverifikasi Architect (brief 43 §1a). Murah, dan tak memasang k2 yang berat.
      2. Tambal `LazyModule.__getattr__` dengan versi penjaga inspect.py yang
         LINTAS-PLATFORM: bila akses atribut datang dari `inspect.py` (introspeksi
         jinak seperti `hasattr(m,'__file__')`), tolak dengan AttributeError TANPA
         mengimpor. Ini persis niat speechbrain, cuma benar di Windows — dan menutup
         SELURUH kelas landmine sekaligus (k2, transformers, apa pun nanti). Akses
         atribut sungguhan (kelas/fungsi dari kode fungsional) tak terpengaruh.
    """
    import sys
    import types

    # Lapis 1: stub k2 (brief 43 §1a). Hormati k2 sungguhan bila user punya.
    if "k2" not in sys.modules:
        try:
            import k2  # noqa: F401
        except ImportError:
            _k2_stub = types.ModuleType("k2")
            _k2_stub.__version__ = "0.0.0-stub-polyscribe"
            sys.modules["k2"] = _k2_stub

    # Lapis 2: penjaga inspect.py lintas-platform untuk LazyModule speechbrain.
    try:
        from speechbrain.utils import importutils as _sb_iu
    except Exception:
        return  # speechbrain belum terpasang/berubah -> lapis 1 masih menutup P0.

    LazyModule = getattr(_sb_iu, "LazyModule", None)
    if LazyModule is None or getattr(LazyModule, "_polyscribe_guarded", False):
        return

    import os as _os

    _orig_getattr = LazyModule.__getattr__

    def _guarded_getattr(self, attr):
        # `hasattr`/`getattr` dari inspect.py = introspeksi, BUKAN pemakaian nyata.
        # Menambal di sini (bukan mengulang aritmatika stacklevel ensure_module)
        # membuatnya kokoh lintas-versi. sys._getframe(1) = pemanggil akses atribut
        # (hasattr builtin tak menaruh frame Python, jadi ini frame inspect.py).
        try:
            caller = sys._getframe(1)
            if _os.path.basename(caller.f_code.co_filename) == "inspect.py":
                raise AttributeError(attr)
        except AttributeError:
            raise
        except Exception:
            pass
        return _orig_getattr(self, attr)

    LazyModule.__getattr__ = _guarded_getattr
    LazyModule._polyscribe_guarded = True


class PyannoteDiarizer(Diarizer):
    name = "pyannote"

    def __init__(self, config):
        self.config = config
        self._pipeline = None
        self._device = None

    def _pipeline_dir(self) -> Path:
        """Folder model pyannote yang dibundel saat build (salinan file, bukan cache
        bersimlink). Berisi config.yaml + subfolder segmentation/embedding/plda; token
        `$model` di config di-resolve pyannote ke folder ini -> sepenuhnya lokal."""
        return Path(self.config.diarization_dir) / "pyannote"

    def load(self) -> None:
        # Import DI DALAM load(): torch/pyannote hanya perlu bila diarizer_choice
        # ="pyannote". Mengimpor modul ini (mis. untuk uji konversi) tak menyeret
        # PyTorch (~GB) ke proses yang tak memakainya.
        pdir = self._pipeline_dir()
        config_yaml = pdir / "config.yaml"
        if not config_yaml.exists():
            raise FileNotFoundError(
                f"Model pyannote tak ada di {pdir}. Ini plan B yang harus DIBUNDEL saat "
                f"build: `python scripts/download_models.py --only pyannote --hf-token <T>` "
                f"SEKALI (terima lisensi {PYANNOTE_REPO} di HF dulu). Runtime tak akan "
                f"mengunduh (janji offline)."
            )

        # Paksa offline SEBELUM pyannote di-import: apa pun yang coba menembak HF
        # gagal cepat, bukan diam-diam online.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

        # Netralkan landmine lazy-import speechbrain SEBELUM pyannote menyentuhnya
        # (P0 brief 43): stub k2 + penjaga inspect.py lintas-platform. Tanpa ini,
        # Pipeline.from_pretrained gagal di Windows walau `import pyannote` sukses.
        # Detail lengkap di docstring fungsi.
        _neutralize_speechbrain_lazy_landmines()

        try:
            import torch
            from pyannote.audio import Pipeline
        except ImportError as e:
            raise RuntimeError(
                "pyannote.audio / torch belum terpasang. Ini dependency plan B "
                "(PyTorch ~GB) — pasang `pip install -r requirements-pyannote.txt`. "
                f"Detail: {e}"
            )

        # Muat dari config.yaml LOKAL; pyannote me-resolve `$model` ke folder ini,
        # jadi segmentation/embedding/plda semuanya lokal (nol jaringan).
        pipeline = Pipeline.from_pretrained(str(config_yaml))
        if pipeline is None:
            raise RuntimeError(
                f"Pipeline.from_pretrained({config_yaml}) -> None — biasanya berarti "
                f"file model tak lengkap / lisensi belum diterima saat build. Cek {pdir}."
            )

        # Pilih device via heuristik (bug user 2026-08 CUDA OOM di RTX 4060 8 GB):
        # "auto" -> CUDA hanya bila free VRAM cukup sesudah ASR; "cpu"/"cuda" = paksa.
        self._device = _pick_pyannote_device(self.config, torch)
        pipeline.to(self._device)
        self._pipeline = pipeline

    def diarize(self, wav_16k_mono_path: str, progress,
                stereo_path: str | None = None) -> list[SpeakerTurn]:
        # stereo_path diabaikan: pyannote sudah overlap-aware, tak butuh isyarat ITD
        # (itu tambalan untuk kelemahan sherpa).
        if self._pipeline is None:
            self.load()

        progress.emit(ProgressEvent(stage="diarize", fraction=0.0,
                                    message=f"diarization (pyannote, {self._device})"))

        # Muat audio SENDIRI ke tensor in-memory & suapkan sebagai
        # {"waveform", "sample_rate"} — BUKAN path. Alasan: pemuat file bawaan
        # pyannote (torchcodec) butuh DLL FFmpeg yang sering tak ada di Windows;
        # jalur in-memory melewatinya total (lebih tahan-offline, tanpa dependensi
        # native tambahan). WAV sudah 16k mono dari pipeline.
        import soundfile as sf
        import torch

        samples, sr = sf.read(wav_16k_mono_path, dtype="float32", always_2d=False)
        if samples.ndim > 1:               # jaga-jaga kalau stereo lolos
            samples = samples[:, 0]
        waveform = torch.from_numpy(samples).unsqueeze(0)   # (channel=1, time)
        audio_in = {"waveform": waveform.to(self._device), "sample_rate": int(sr)}

        # Jumlah pembicara SELALU auto — TAK meneruskan num_speakers apa pun.
        from pyannote.audio.pipelines.utils.hook import ProgressHook

        def _run_pipeline(input_dict):
            try:
                with ProgressHook() as _hook:
                    return self._pipeline(input_dict, hook=_hook)
            except TypeError:
                # Versi pyannote yang API hook-nya beda -> jalan tanpa hook.
                return self._pipeline(input_dict)

        try:
            output = _run_pipeline(audio_in)
        except torch.cuda.OutOfMemoryError as oom:
            # Jaring pengaman: preflight VRAM meleset (mis. proses lain merebut GPU
            # setelah load). Pindah pipeline & waveform ke CPU, kosongkan cache,
            # retry SEKALI. Kalau retry masih gagal -> biar error naik ke user.
            progress.emit(ProgressEvent(
                stage="diarize", fraction=0.0,
                message=f"VRAM habis ({oom.__class__.__name__}), pindah ke CPU & retry",
                text_snippet="pyannote: CUDA OOM -> retry di CPU"))
            self._pipeline.to(torch.device("cpu"))
            self._device = torch.device("cpu")
            torch.cuda.empty_cache()
            audio_in = {"waveform": waveform.to("cpu"), "sample_rate": int(sr)}
            output = _run_pipeline(audio_in)

        # pyannote 4.x mengembalikan DiarizeOutput (bukan Annotation langsung).
        # Pakai `speaker_diarization` = versi OVERLAP-AWARE (dua orang bisa bicara
        # bersamaan -> dua turn) — inti serangan #2. Versi legacy/3.x langsung
        # Annotation, jadi getattr fallback ke object itu sendiri.
        annotation = getattr(output, "speaker_diarization", output)
        turns = _turns_from_annotation(annotation)
        progress.emit(ProgressEvent(stage="diarize", fraction=1.0,
                                    message="diarization selesai (pyannote)"))
        return turns
