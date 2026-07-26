"""Decode + resample audio apa pun jadi satu WAV 16 kHz mono.

Satu WAV 16k inilah yang dipakai bersama ASR & diarization — hemat waktu decode,
dan (yang penting) input kedua modul identik jadi timestamp keduanya sinkron.

Kita pakai ffmpeg bawaan imageio-ffmpeg supaya tidak menuntut user memasang
ffmpeg sistem, dan gampang dibundel nanti.
"""

import subprocess
import wave
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe


TARGET_RATE = 16000
TARGET_CHANNELS = 1


def decode_to_16k_mono(src_path: str, out_wav_path: str) -> str:
    """Decode file audio apa pun ke WAV 16 kHz mono PCM 16-bit.

    Kembalikan path WAV hasil. Melempar error yang jelas kalau ffmpeg gagal
    (mis. file rusak / format tak dikenal).
    """
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"File audio tidak ditemukan: {src}")

    out = Path(out_wav_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-nostdin",
        "-y",                       # timpa output kalau sudah ada
        "-i", str(src),
        "-ac", str(TARGET_CHANNELS),  # mono
        "-ar", str(TARGET_RATE),      # 16 kHz
        "-vn",                        # buang video/cover-art bila ada
        "-c:a", "pcm_s16le",          # WAV PCM 16-bit
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        # Ambil beberapa baris terakhir stderr ffmpeg — di situ alasannya.
        tail = "\n".join(result.stderr.strip().splitlines()[-5:])
        raise RuntimeError(f"ffmpeg gagal men-decode {src.name}:\n{tail}")

    return str(out)


def wav_duration_seconds(wav_path: str) -> float:
    """Durasi WAV dalam detik — dibaca dari header, tanpa memuat sampelnya."""
    with wave.open(str(wav_path), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
        return frames / float(rate) if rate else 0.0


def decode_to_16k_stereo(src_path: str, out_wav_path: str):
    """Decode ke WAV 16 kHz STEREO untuk memanen isyarat arah (ILD/ITD).

    Kembalikan path WAV stereo bila sumbernya benar-benar stereo, atau **None**
    bila sumber mono / stereo palsu (dua kanal identik). Ini SUPLEMEN — jalur ASR
    & embedding tetap pakai mono dari decode_to_16k_mono; stereo hanya untuk fitur
    spasial. Kalau None, pemanggil wajib jatuh balik ke perilaku mono (jangan crash).

    Deteksi stereo-palsu lewat korelasi L/R (spatial.is_fake_stereo): ffmpeg -ac 2
    atas sumber mono menghasilkan dua kanal sama persis -> tak ada arah untuk dipanen.
    """
    import numpy as np
    from . import spatial

    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"File audio tidak ditemukan: {src}")

    out = Path(out_wav_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = get_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-nostdin",
        "-y",
        "-i", str(src),
        "-ac", "2",                   # stereo — pertahankan kedua kanal
        "-ar", str(TARGET_RATE),      # 16 kHz
        "-vn",
        "-c:a", "pcm_s16le",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-5:])
        raise RuntimeError(f"ffmpeg gagal men-decode {src.name} (stereo):\n{tail}")

    # Baca L/R, uji apakah benar-benar dua kanal berbeda.
    with wave.open(str(out), "rb") as w:
        n_ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    if n_ch < 2:
        out.unlink(missing_ok=True)
        return None
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    left, right = data[0::2], data[1::2]
    if spatial.is_fake_stereo(left, right):
        out.unlink(missing_ok=True)      # mono menyamar stereo — buang, pakai jalur mono
        return None

    return str(out)
