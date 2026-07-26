"""Ukur realtime factor (RTF) backend ASR, dan bandingkan Backend A vs B.

RTF = durasi_audio / waktu_proses. > 1.0 = lebih cepat dari realtime (bagus).

Contoh:
    # bandingkan A (CPU) vs B (Vulkan) di klip yang sama
    python scripts/benchmark_backends.py "rekaman.mp3" --seconds 300 --compare
    # satu backend saja
    python scripts/benchmark_backends.py "rekaman.mp3" --backend whispercpp
"""

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from polyscribe import audio
from polyscribe.asr import FasterWhisperBackend
from polyscribe.asr.whispercpp_backend import WhisperCppVulkanBackend
from polyscribe.asr import select_asr_backend
from polyscribe.config import Config
from polyscribe.hardware import detect, describe
from polyscribe.progress import NullSink


def clip_wav(src_wav: str, seconds: float) -> str:
    """Potong beberapa detik awal WAV untuk benchmark cepat (pakai ffmpeg)."""
    import subprocess
    from imageio_ffmpeg import get_ffmpeg_exe

    out = str(Path(tempfile.mkdtemp(prefix="bench_")) / "clip.wav")
    subprocess.run(
        [get_ffmpeg_exe(), "-nostdin", "-y", "-i", src_wav,
         "-t", str(seconds), "-c", "copy", out],
        capture_output=True, check=True,
    )
    return out


def _run_backend(backend, wav, dur):
    """Muat model + transkripsi, kembalikan (rtf, proc_s, load_s, n_seg)."""
    t0 = time.time()
    backend.load()
    load_s = time.time() - t0

    sink = NullSink()
    t0 = time.time()
    n_seg = sum(1 for _ in backend.transcribe(wav, sink))
    proc = time.time() - t0
    rtf = dur / proc if proc else 0.0
    return rtf, proc, load_s, n_seg


def _decode(src, seconds):
    work = Path(tempfile.mkdtemp(prefix="bench16k_"))
    wav = str(work / "audio_16k_mono.wav")
    audio.decode_to_16k_mono(src, wav)
    if seconds:
        wav = clip_wav(wav, seconds)
    return wav


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark RTF backend ASR (A vs B).")
    parser.add_argument("audio", help="path file audio nyata")
    parser.add_argument("--backend", default="auto",
                        choices=["auto", "faster-whisper", "whispercpp"])
    parser.add_argument("--seconds", type=float, default=None,
                        help="pakai N detik pertama saja (default: seluruh file)")
    parser.add_argument("--compare", action="store_true",
                        help="jalankan A (CPU) & B (Vulkan) di klip sama, cetak tabel")
    parser.add_argument("--language", default="en",
                        help="bahasa ASR ('en' default, 'auto' untuk multibahasa)")
    args = parser.parse_args(argv)

    caps = detect()
    print(f"Mesin: {describe(caps)}")

    cfg = Config()
    cfg.primary_language = args.language

    print("decode -> 16k mono ...")
    wav = _decode(args.audio, args.seconds)
    dur = audio.wav_duration_seconds(wav)
    print(f"durasi audio yang diuji: {dur:.1f}s ({dur/60:.1f} menit), bahasa={args.language}\n")

    if args.compare:
        rows = []
        # Backend A — faster-whisper CPU int8
        a = FasterWhisperBackend(cfg.faster_whisper_dir, device="cpu",
                                 compute_type="int8",
                                 primary_language=cfg.primary_language)
        print("Backend A (faster-whisper CPU int8) ...")
        rows.append(("A: faster-whisper CPU int8", *_run_backend(a, wav, dur)))

        # Backend B — whisper.cpp Vulkan
        b = WhisperCppVulkanBackend(cfg)
        print("Backend B (whisper.cpp Vulkan) ...")
        rows.append(("B: whisper.cpp Vulkan", *_run_backend(b, wav, dur)))

        print("\n=== A vs B (RTF = audio/proses; makin besar makin cepat) ===")
        print(f"{'backend':<28} {'RTF':>7} {'proc(s)':>9} {'load(s)':>9} {'seg':>5}")
        for name, rtf, proc, load_s, n in rows:
            print(f"{name:<28} {rtf:>6.2f}x {proc:>9.1f} {load_s:>9.1f} {n:>5}")
        if rows[0][1] and rows[1][1]:
            speedup = rows[1][1] / rows[0][1]
            print(f"\nVulkan (B) {speedup:.1f}x lebih cepat dari CPU (A) di klip ini.")
        print("Catatan: A tak menghitung load model sekali (~15s); B menyertakan "
              "load subprocess (~2s) tiap run.")
        return 0

    # Mode satu backend
    cfg.asr_backend = args.backend
    backend = select_asr_backend(caps, cfg)
    print(f"backend ASR: {backend.name}")
    rtf, proc, load_s, n_seg = _run_backend(backend, wav, dur)
    print("\n=== HASIL ===")
    print(f"segmen        : {n_seg}")
    print(f"load model    : {load_s:.1f}s")
    print(f"waktu proses  : {proc:.1f}s")
    print(f"realtime factor (audio/proses): {rtf:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
