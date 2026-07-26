"""Unduh semua model PolyScribe SEKALI ke models/ (saat masih ada internet).

Setelah ini, runtime membaca dari models/ dengan local_files_only=True — tidak
ada akses jaringan di jalur utama. Jalankan dari root proyek:

    python scripts/download_models.py
    python scripts/download_models.py --only diarization   # sebagian saja

Yang diunduh:
  1. faster-whisper large-v3 (format CTranslate2) -> models/faster-whisper-large-v3/
  2. Diarization sherpa-onnx: segmentation (pyannote-3.0) + embedding (3D-Speaker)
     -> models/diarization/
"""

import argparse
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# hf_xet (backend Xet Hugging Face) sering menggantung tanpa token di mesin ini —
# proses jalan tapi 0 byte masuk ke disk. Paksa jalur HTTPS biasa yang stabil
# (~12 MB/s) dengan mematikan Xet sebelum huggingface_hub di-import.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"

# Model faster-whisper large-v3 dalam format CTranslate2 (siap dipakai backend A).
FASTER_WHISPER_REPO = "Systran/faster-whisper-large-v3"
FASTER_WHISPER_DIR = MODELS_DIR / "faster-whisper-large-v3"

# Model diarization dari halaman rilis sherpa-onnx (GitHub).
SEG_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
# Embedding 3D-Speaker (campplus, zh+en common) — cukup untuk suara campur.
EMB_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
)
DIAR_DIR = MODELS_DIR / "diarization"

# Model GGML untuk whisper.cpp (Backend B Vulkan). Format GGML beda dari
# CTranslate2 milik faster-whisper. Varian q5_0 dipilih: hemat memori & lebih
# cepat, akurasi hampir sama dengan large-v3 penuh untuk kasus rapat.
WHISPER_GGML_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
    "ggml-large-v3-q5_0.bin?download=true"
)
WHISPER_GGML_DIR = MODELS_DIR / "whisper"

# --- Diarization plan B: pyannote (brief 36). Model ter-GATE di HF -> butuh token
# + lisensi diterima, SEKALI, saat build. Dibundel sebagai CACHE HF ke
# models/diarization/pyannote/hub lalu runtime pakai HF_HOME lokal + HF_HUB_OFFLINE
# (nol jaringan/token). pyannote.audio 4.x = SATU repo self-contained (segmentation
# + embedding + PLDA); model 3.1 lama TAK kompatibel dengan kode pipeline 4.x. ---
PYANNOTE_REPO = "pyannote/speaker-diarization-community-1"
PYANNOTE_DIR = MODELS_DIR / "diarization" / "pyannote"
PYANNOTE_HUB = PYANNOTE_DIR / "hub"      # = HF_HOME/hub yang dibaca backend


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  unduh {url}")
    print(f"     -> {dest}")

    def _report(block, block_size, total):
        if total > 0:
            done = min(block * block_size, total)
            pct = done * 100 // total
            sys.stdout.write(f"\r     {pct:3d}%  ({done // (1024*1024)} MB)")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, dest, reporthook=_report)
    sys.stdout.write("\n")


def download_faster_whisper() -> None:
    print("[1/2] faster-whisper large-v3 (CTranslate2)")
    if (FASTER_WHISPER_DIR / "model.bin").exists():
        print("  sudah ada, lewati.")
        return
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("  huggingface_hub belum terpasang — install requirements dulu.")
        raise
    snapshot_download(
        repo_id=FASTER_WHISPER_REPO,
        local_dir=str(FASTER_WHISPER_DIR),
        # Ambil yang perlu saja untuk CTranslate2.
        allow_patterns=["*.bin", "*.json", "*.txt", "vocabulary*"],
    )
    print(f"  selesai -> {FASTER_WHISPER_DIR}")


def download_diarization() -> None:
    print("[2/2] diarization sherpa-onnx (segmentation + embedding)")
    DIAR_DIR.mkdir(parents=True, exist_ok=True)

    # --- Segmentation: tarball -> ekstrak model.onnx, beri nama ber-"segmentation" ---
    seg_out = DIAR_DIR / "sherpa-onnx-pyannote-segmentation-3-0.onnx"
    if seg_out.exists():
        print("  segmentation sudah ada, lewati.")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            tar_bz2 = tmp / "seg.tar.bz2"
            _download(SEG_URL, tar_bz2)
            # tarfile menangani bz2 langsung ("r:bz2") dan menutup file-nya
            # sendiri saat blok selesai — penting di Windows supaya temp dir
            # bisa dibersihkan tanpa "file masih dipakai".
            extract_dir = tmp / "extracted"
            with tarfile.open(tar_bz2, mode="r:bz2") as tf:
                tf.extractall(extract_dir)
            # Cari model.onnx di dalam hasil ekstrak, salin keluar SEBELUM temp
            # dir dihapus.
            found = next(extract_dir.rglob("model.onnx"), None)
            if found is None:
                raise RuntimeError("model.onnx tidak ditemukan di tarball segmentation.")
            shutil.copyfile(found, seg_out)
            print(f"  segmentation -> {seg_out}")

    # --- Embedding: file .onnx langsung ---
    emb_out = DIAR_DIR / Path(EMB_URL).name
    if emb_out.exists():
        print("  embedding sudah ada, lewati.")
    else:
        _download(EMB_URL, emb_out)
        print(f"  embedding -> {emb_out}")


def download_whisper_ggml() -> None:
    print("[3/3] whisper.cpp GGML large-v3 (q5_0) — untuk Backend B Vulkan")
    out = WHISPER_GGML_DIR / "ggml-large-v3-q5_0.bin"
    if out.exists() and out.stat().st_size > 500 * 1024 * 1024:
        print("  sudah ada, lewati.")
        return
    _download(WHISPER_GGML_URL, out)
    print(f"  selesai -> {out}")


def download_pyannote(token: str | None) -> None:
    """Unduh & bundel model pyannote (plan B) untuk pemakaian OFFLINE.

    Ter-gate di HF: butuh token + lisensi repo diterima di web SEKALI. Ini murni
    langkah BUILD; runtime tak pernah menyentuh jaringan/token. community-1 adalah
    SATU repo self-contained (segmentation + embedding + PLDA) untuk pyannote.audio
    4.x. Dibundel sebagai CACHE HF di models/diarization/pyannote/hub supaya
    referensi antar-subfolder resolve saat runtime offline (HF_HOME lokal)."""
    print(f"[pyannote] plan B — {PYANNOTE_REPO} (butuh token HF saat build)")
    token = (token or os.environ.get("HF_TOKEN")
             or os.environ.get("HUGGING_FACE_HUB_TOKEN"))
    if not token:
        raise SystemExit(
            "  BERHENTI: tak ada HF token. Model pyannote ter-gate. Terima lisensi di\n"
            f"    https://hf.co/{PYANNOTE_REPO}\n"
            "  lalu jalankan ulang dengan --hf-token <TOKEN> atau set HF_TOKEN.\n"
            "  (Token HANYA untuk build ini; runtime tetap offline tanpa token.)"
        )
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("  huggingface_hub belum terpasang — install requirements dulu.")
        raise

    PYANNOTE_DIR.mkdir(parents=True, exist_ok=True)
    # Unduh SELURUH repo ke local_dir (SALINAN file nyata, BUKAN cache bersimlink):
    # cache HF pakai symlink blobs->snapshots yang butuh privilege admin di Windows
    # (WinError 1314). local_dir menyalin file langsung -> aman tanpa admin, dan
    # semua subfolder (segmentation/embedding/plda) ada relatif di satu folder.
    snapshot_download(PYANNOTE_REPO, local_dir=str(PYANNOTE_DIR), token=token)
    cfg = PYANNOTE_DIR / "config.yaml"
    if cfg.exists():
        print(f"  selesai -> {PYANNOTE_DIR} (runtime: from_pretrained lokal + offline)")
    else:
        print(f"  PERINGATAN: {cfg} tak ada — cek lisensi/token.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Unduh model PolyScribe ke models/.")
    parser.add_argument(
        "--only",
        choices=["faster-whisper", "diarization", "whisper-ggml", "pyannote"],
        help="unduh sebagian saja (default: semua KECUALI pyannote plan B)",
    )
    parser.add_argument(
        "--hf-token", default=None,
        help="token HF untuk model pyannote ter-gate (hanya untuk --only pyannote)",
    )
    args = parser.parse_args(argv)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Target: {MODELS_DIR}\n")

    # pyannote (plan B) TIDAK diunduh secara default (butuh token + PyTorch besar);
    # hanya lewat --only pyannote yang eksplisit.
    if args.only == "pyannote":
        download_pyannote(args.hf_token)
        print("\npyannote plan B siap. Runtime offline (HF_HUB_OFFLINE).")
        return 0

    if args.only in (None, "faster-whisper"):
        download_faster_whisper()
    if args.only in (None, "diarization"):
        download_diarization()
    if args.only in (None, "whisper-ggml"):
        download_whisper_ggml()

    print("\nSemua model (plan A) siap. Runtime sekarang bisa jalan offline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
