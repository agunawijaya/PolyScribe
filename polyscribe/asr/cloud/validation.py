"""Validasi ukuran/durasi audio SEBELUM pipeline jalan.

Kenapa terpisah dari transcribe(): kalau divalidasi di dalam adapter, user
menatap "Memuat model" 30 detik lalu error muncul — pengalaman jelek. Divalidasi
di sini, pesan muncul instan di GUI/CLI sebelum apa pun dimulai.

Kontrak: `validate_audio(provider_key, audio_path) -> Verdict`. Verdict punya:
- ok: bool. False = HARUS TOLAK, jangan mulai run.
- error: str. Pesan yg tampil sbg dialog error (kalau ok=False).
- warning: str. Pesan peringatan yg BUKAN blocker (kalau ok=True tapi ada risiko).

Ukuran = ukuran WAV 16k mono yg akan dihasilkan decoder kita (bukan file input
asli). WAV 16k mono PCM 16-bit = 32 KB/detik = ~1.92 MB/menit — dihitung dari
DURASI audio, bukan diukur (karena decode belum jalan pada titik validasi).
"""

from dataclasses import dataclass
from pathlib import Path

from .registry import get_provider_info


# WAV 16k mono PCM 16-bit: 16000 sample/dtk × 2 byte = 32000 byte/dtk.
_WAV_BYTES_PER_SECOND = 32000
_WAV_MB_PER_HOUR = (_WAV_BYTES_PER_SECOND * 3600) / (1024 * 1024)   # ~110 MB/jam


@dataclass
class Verdict:
    ok: bool
    error: str = ""
    warning: str = ""


def validate_audio(provider_key: str, audio_path: str) -> Verdict:
    """Cek ukuran+durasi audio terhadap batas provider. Kembalikan Verdict.

    Batas TIDAK divalidasi kalau provider tak dikenal — kembalikan ok=True
    dgn peringatan (kasus tak diharapkan; selector akan melempar sendiri).
    File tak ada -> ok=False dgn pesan filesystem.
    """
    info = get_provider_info(provider_key)
    if info is None:
        return Verdict(ok=True, warning=f"Provider '{provider_key}' tak dikenal "
                       "di registry — validasi ukuran/durasi dilewati.")

    path = Path(audio_path)
    if not path.exists():
        return Verdict(ok=False, error=f"File audio tak ditemukan: {audio_path}")

    duration_s = _estimate_duration(audio_path)
    if duration_s <= 0:
        # Gagal probe durasi (ffprobe tak ada / file rusak). JANGAN tolak — decode
        # akan gagal dgn pesan lebih baik. Cuma peringatan kalau provider punya
        # batas ketat.
        if info.max_duration_s > 0 and not info.auto_chunks:
            return Verdict(
                ok=True,
                warning=f"Tak bisa mengukur durasi file. Provider "
                f"'{info.display_name}' batas {_fmt_duration(info.max_duration_s)}. "
                "Kalau melebihi, run akan gagal di tengah."
            )
        return Verdict(ok=True)

    wav_mb = duration_s * _WAV_BYTES_PER_SECOND / (1024 * 1024)

    # HARD LIMIT: durasi per-file (kalau adapter tak auto-chunk).
    if info.max_duration_s > 0 and not info.auto_chunks:
        if duration_s > info.max_duration_s:
            return Verdict(
                ok=False,
                error=_error_duration(info, duration_s),
            )

    # HARD LIMIT: ukuran per-request. Kalau auto_chunks, batas ini per-chunk —
    # chunker sudah pastikan tak melewati. Kalau tidak, batas TOTAL file.
    if info.max_size_mb > 0 and not info.auto_chunks:
        if wav_mb > info.max_size_mb:
            return Verdict(
                ok=False,
                error=_error_size(info, wav_mb),
            )

    # SOFT WARNING: catatan dari registry (mis. rate limit share Google Web).
    warning = info.warn_notes
    # Google Web Speech: rate limit share dgn semua user library. File > 15 mnt
    # = > 30 chunk, sepertiga kuota harian sekali klik.
    if info.key == "google_web" and duration_s > 15 * 60:
        chunk_count = int(duration_s / 30) + 1
        warning = (
            f"File {_fmt_duration(duration_s)} = ~{chunk_count} request ke "
            "endpoint Google Web Speech. Rate limit ~50/hari DIBAGI dgn semua "
            "user library speech_recognition di dunia — kemungkinan besar akan "
            "kena limit di tengah jalan. Rekomendasi: pakai Groq atau Deepgram."
        )

    return Verdict(ok=True, warning=warning)


def _estimate_duration(audio_path: str) -> float:
    """Perkirakan durasi audio (detik) tanpa decode penuh.

    Strategi: pakai ffprobe (bawaan imageio-ffmpeg — sudah dep PolyScribe).
    Kalau ffprobe tak tersedia/gagal, kembalikan 0 (caller memutuskan gimana).
    """
    try:
        import subprocess
        from imageio_ffmpeg import get_ffmpeg_exe
        # ffprobe: some builds of imageio-ffmpeg tak menyertakannya. Coba ambil
        # dari path yg sama, tak apa-apa kalau gagal.
        ffmpeg = get_ffmpeg_exe()
        # ffmpeg juga bisa print durasi lewat stderr saat -i. Lebih portabel.
        cmd = [ffmpeg, "-nostdin", "-i", audio_path, "-hide_banner", "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        return _parse_ffmpeg_duration(r.stderr)
    except (OSError, subprocess.SubprocessError, ImportError):
        return 0.0


def _parse_ffmpeg_duration(stderr: str) -> float:
    """Cari 'Duration: HH:MM:SS.mm' di stderr ffmpeg. Kembalikan detik."""
    import re
    m = re.search(r"Duration:\s+(\d+):(\d+):(\d+(?:\.\d+)?)", stderr or "")
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} detik"
    if seconds < 3600:
        return f"{seconds / 60:.1f} menit"
    return f"{seconds / 3600:.2f} jam"


def _error_duration(info, actual_s: float) -> str:
    """Pesan error yg spesifik untuk kasus 'durasi > batas'. Sebutkan solusi."""
    if info.key == "google_cloud":
        return (
            f"'{info.display_name}' batas KERAS 60 detik (mode sinkron). File "
            f"kamu {_fmt_duration(actual_s)}. Untuk file lebih panjang, pilih "
            "provider lain — Google Cloud butuh setup GCS bucket yg belum "
            "didukung PolyScribe.\n\n"
            "Rekomendasi: Groq (murah, cepat), Deepgram (kualitas tertinggi)."
        )
    if info.key == "azure_speech":
        return (
            f"'{info.display_name}' batas 2 jam per file (Fast Transcription "
            f"API). File kamu {_fmt_duration(actual_s)}. Untuk file lebih "
            "panjang, potong dulu atau pakai provider lain.\n\n"
            "Rekomendasi: Deepgram (10 jam), AssemblyAI (10 jam)."
        )
    return (
        f"'{info.display_name}' batas {_fmt_duration(info.max_duration_s)} per "
        f"file. File kamu {_fmt_duration(actual_s)}. Potong dulu, atau pilih "
        "provider lain (Deepgram / AssemblyAI menerima sampai 10 jam)."
    )


def _error_size(info, actual_mb: float) -> str:
    if info.key == "google_cloud":
        return (
            f"'{info.display_name}' batas KERAS 10 MB (mode sinkron). Setelah "
            f"decode WAV 16k mono, file kamu ~{actual_mb:.1f} MB. Pilih "
            "provider lain."
        )
    return (
        f"'{info.display_name}' batas {info.max_size_mb:.0f} MB per file. "
        f"Setelah decode WAV 16k mono, file kamu ~{actual_mb:.1f} MB. Potong "
        "dulu atau pilih provider lain."
    )
