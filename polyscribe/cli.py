"""Entry Milestone 1 — jalan dari command line.

Rangkai: audio -> asr -> diar -> merge -> .txt, dengan progress hidup di layar.
Progress "hidup" artinya satu baris yang di-update di tempat (carriage return),
menampilkan tahap + posisi waktu berjalan + cuplikan teks terbaru.

Contoh:
    python -m polyscribe.cli "rekaman rapat.mp3"
    python -m polyscribe.cli rapat.wav --cluster-threshold 0.6 --backend faster-whisper
"""

import argparse
import sys
import time

from .config import Config
from .diarization import pyannote_availability
from .hardware import detect, describe
from .pipeline import transcribe_file
from .progress import ProgressEvent, ProgressSink


# Nama tahap yang enak dibaca manusia untuk indikator.
STAGE_LABEL = {
    "load": "memuat model",
    "diarize_prep": "menyiapkan",
    "transcribe": "transkripsi",
    "diarize": "diarization",
    "merge": "menggabung",
    "done": "selesai",
}


class ConsoleSink(ProgressSink):
    """Cetak progress ke layar dalam satu baris yang bergerak."""

    def __init__(self):
        self._start = time.time()
        self._last_len = 0

    def emit(self, event: ProgressEvent) -> None:
        label = STAGE_LABEL.get(event.stage, event.stage)
        pct = int(event.fraction * 100)
        elapsed = time.time() - self._start

        # Cuplikan teks terbaru dipangkas biar tidak melebihi lebar terminal.
        snippet = event.text_snippet.strip().replace("\n", " ")
        if len(snippet) > 50:
            snippet = snippet[:47] + "..."

        line = f"[{elapsed:6.1f}s] {label:<12} {pct:3d}%"
        if snippet:
            line += f"  | {snippet}"
        elif event.message:
            # Untuk tahap bertahap-langkah tanpa snippet ASR (mis. load sub-message
            # "mendekode audio", "memuat ASR"), tampilkan message supaya user lihat
            # gerakan per langkah — bukan "memuat model 0%" bisu.
            line += f"  | {event.message}"

        # Timpa baris sebelumnya (carriage return + padding sisa).
        pad = max(0, self._last_len - len(line))
        sys.stdout.write("\r" + line + (" " * pad))
        sys.stdout.flush()
        self._last_len = len(line)

        # Tahap yang tuntas dapat baris sendiri supaya jejaknya kelihatan.
        if event.stage in ("load", "merge", "done") and event.fraction >= 1.0:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._last_len = 0


def build_config(args) -> Config:
    cfg = Config()
    if args.backend:
        cfg.asr_backend = args.backend
    # --asr cloud:<provider> (2026-09-21) — opt-in ke tumpukan cloud STT. Nilai
    # dipetakan ke asr_backend="cloud" + cloud_provider=<provider>. Tanpa flag ini,
    # jalur default TETAP offline (batasan keras CLAUDE.md).
    if getattr(args, "asr", None):
        val = args.asr.strip().lower()
        if val.startswith("cloud:"):
            cfg.asr_backend = "cloud"
            cfg.cloud_provider = val.split(":", 1)[1]
        elif val == "offline":
            pass    # tak mengubah — cfg.asr_backend sudah diisi --backend / default
        else:
            raise SystemExit(f"--asr harus 'offline' atau 'cloud:<provider>'. "
                             f"Dapat: {args.asr}")
    if args.cluster_threshold is not None:
        cfg.cluster_threshold = args.cluster_threshold
    if args.language:
        cfg.primary_language = args.language
    if args.no_vulkan:
        cfg.allow_vulkan = False
    if args.diarizer:
        cfg.diarizer_choice = args.diarizer
    # Knob kualitas ASR baru (brief 2026-08). --vad-on/--vad-off overrides default;
    # bila keduanya tak diset, default config yg dipakai.
    if getattr(args, "vad_on", False):
        cfg.vad_filter = True
    elif getattr(args, "vad_off", False):
        cfg.vad_filter = False
    if getattr(args, "initial_prompt", None):
        cfg.asr_initial_prompt = args.initial_prompt
    return cfg


def _force_utf8_console() -> None:
    # Konsol Windows default (cp1252) tak bisa mencetak Arab/karakter non-Latin
    # dan akan melempar UnicodeEncodeError saat kita menampilkan cuplikan teks.
    # Paksa stdout/stderr ke UTF-8; kalau terminal tetap tak sanggup, ganti
    # karakter yang bermasalah alih-alih menghentikan pipeline.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="polyscribe",
        description="Transkripsi + diarization audio rapat, offline (Milestone 1 CLI).",
    )
    parser.add_argument("audio", help="path file audio (WAV/MP3/…)")
    parser.add_argument(
        "--backend", choices=["auto", "faster-whisper", "whispercpp"],
        default="auto", help="pilih backend ASR offline (default: auto)",
    )
    parser.add_argument(
        "--asr", default=None,
        help="'offline' (default, sama dgn --backend) atau 'cloud:<provider>'. "
             "Provider cloud: google_web | groq | deepgram | openai_whisper | "
             "assemblyai | azure_speech | google_cloud. Butuh API key di GUI dulu.",
    )
    parser.add_argument(
        "--cluster-threshold", type=float, default=None,
        help="knob auto speaker-count diarization (default dari config: 0.9)",
    )
    parser.add_argument(
        "--language", default=None,
        help="bahasa utama ASR: 'en' (default, stabil di awal file) atau "
             "'auto' untuk file multibahasa (mis. SIRA). Kode ISO lain juga boleh.",
    )
    parser.add_argument(
        "--no-vulkan", action="store_true",
        help="paksa CPU di AMD (matikan jalur Vulkan)",
    )
    parser.add_argument(
        "--diarizer", choices=["pyannote", "sherpa"], default=None,
        help="mode pelabelan pembicara: 'pyannote' (Akurat, default — pisah "
             "pertukaran cepat, lebih lambat) atau 'sherpa' (Cepat). Kalau model "
             "pyannote tak terpasang, otomatis jatuh ke sherpa.",
    )
    # VAD toggle (brief 2026-08 kualitas teks): default sudah False untuk audio
    # rapat. Sediakan kedua arah agar user bisa override di sisi mana pun.
    vad = parser.add_mutually_exclusive_group()
    vad.add_argument(
        "--vad-off", action="store_true",
        help="matikan VAD filter (default; terbukti lebih baik untuk audio rapat "
             "ber-overlap tinggi — Whisper dapat konteks utuh -> punctuation muncul).",
    )
    vad.add_argument(
        "--vad-on", action="store_true",
        help="nyalakan VAD filter (buang keheningan; lebih cepat untuk audio "
             "single-speaker bersih, tapi kadang chop mid-sentence).",
    )
    parser.add_argument(
        "--initial-prompt", default=None, dest="initial_prompt",
        help="teks yg di-prepend ke Whisper untuk 'nudge' output — mis. daftar "
             "nama peserta & istilah teknis (\"Meeting with Jaffar Labs, MBRL. "
             "Discussing Symphony, Summon.\"). Bisa halusinasi kalau prompt "
             "tak match audio; isi hanya bila Anda tahu isinya.",
    )
    return parser


def main(argv=None) -> int:
    _force_utf8_console()
    args = build_parser().parse_args(argv)

    caps = detect()
    print(f"PolyScribe — {describe(caps)}")

    cfg = build_config(args)

    # Fallback aman (brief 37): kalau mode Akurat (pyannote) diminta tapi paket/model
    # belum terpasang, beri tahu & jatuh ke Cepat (sherpa) — selaras dengan GUI.
    if cfg.diarizer_choice == "pyannote":
        ready, reason = pyannote_availability(cfg)
        if not ready:
            print(f"Catatan: {reason}\n  -> memakai mode Cepat (sherpa) untuk run ini.")
            cfg.diarizer_choice = "sherpa"

    # Validasi batas ukuran/durasi cloud SEBELUM mulai (gagal cepat, bukan setelah
    # loader model berjalan 30 detik). Berlaku hanya untuk backend cloud.
    if cfg.asr_backend == "cloud" and cfg.cloud_provider:
        from .asr.cloud import validate_audio
        verdict = validate_audio(cfg.cloud_provider, args.audio)
        if not verdict.ok:
            print(f"\nError validasi cloud:\n{verdict.error}", file=sys.stderr)
            return 2
        if verdict.warning:
            print(f"\nPeringatan: {verdict.warning}\n", file=sys.stderr)

    sink = ConsoleSink()

    try:
        result = transcribe_file(args.audio, cfg, sink)
    except FileNotFoundError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"\nGagal: {e}", file=sys.stderr)
        return 1

    print(f"\nDurasi audio : {result.duration:.1f}s")
    print(f"Pembicara    : {len(result.speakers)} ({', '.join(result.speakers)})")
    print(f"Output       : {result.txt_path}")
    if result.loop_detected:
        stamps = ", ".join(f"{int(t)//60:02d}:{int(t)%60:02d}"
                           for t in (result.loop_times or []))
        print("\n*** PERINGATAN: kemungkinan loop/halusinasi ASR terdeteksi ***")
        print(f"    Titik: {stamps}. Periksa bagian bertanda '=== PERINGATAN'")
        print("    di dalam .txt — teks di sekitar situ mungkin rusak/berulang.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
