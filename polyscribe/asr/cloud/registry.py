"""Katalog provider cloud + factory.

Kenapa registry alih-alih if-else di selector: (a) GUI perlu iterate metadata
(nama, harga, kapabilitas) untuk membangun dropdown & kartu info; (b) menambah
provider = tambah satu entri, tak menyentuh selector di beberapa tempat.

Harga per jam sengaja diletakkan di sini SEBAGAI HINT — bukan billing engine.
Nilai = perkiraan tier pay-as-you-go per September 2026; user harus verifikasi
di situs vendor sebelum memilih. Perubahan harga vendor tak akan memecahkan
apa pun, cuma menampilkan hint yang basi.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class ProviderInfo:
    """Metadata provider untuk GUI. Tak memuat state runtime."""
    key: str                              # slug utk keystore (mis. "deepgram")
    display_name: str                     # nama untuk dropdown UI
    needs_key: bool = True                # False = provider gratis (no auth)
    has_diarization: bool = False         # kapabilitas provider (INFO)
    has_timestamps: bool = True           # kalau False, PolyScribe generate pseudo
    price_hint_per_hour_usd: float = 0.0  # 0 = gratis / tak tahu
    languages: str = ""                   # ringkas: "EN/AR/ID" dll
    notes: str = ""                       # 1-2 kalimat tradeoff
    # Rekomendasi 1 kalimat untuk GUI: mengapa user pilih ini
    recommendation: str = ""
    # --- batas keras per-request (2026-09-21) ---
    # max_size_mb: 0 = tak dibatasi (upload utuh); >0 = batas TOTAL yg dilihat
    # provider. Adapter dgn `auto_chunks=True` otomatis pecah, jadi batas ini
    # tetap tercapai per-chunk & user tak perlu khawatir soal ukuran total.
    max_size_mb: float = 0.0
    # max_duration_s: 0 = tak dibatasi. Kalau adapter chunk otomatis, ini batas
    # per-CHUNK; kalau tidak, ini batas TOTAL file.
    max_duration_s: float = 0.0
    # True = adapter kita pecah file besar otomatis (Groq/OpenAI); False = upload
    # utuh, batas keras = batas provider (Deepgram/AssemblyAI/Azure/Google Cloud).
    auto_chunks: bool = False
    # Peringatan tambahan yang layak ditampilkan di GUI bahkan bila file sah
    # (mis. "endpoint tak resmi — kuota harian dibagi ke semua user library").
    warn_notes: str = ""


# Registry disusun urut rekomendasi: bebas biaya dulu (buat coba-coba), lalu
# murah-cepat, lalu premium. Tidak alfabetis — urutan ini yg tampil di dropdown.
_PROVIDERS: list[ProviderInfo] = [
    ProviderInfo(
        key="google_web",
        display_name="Google Web Speech (gratis, sama dgn markitdown)",
        needs_key=False,
        has_diarization=False,
        has_timestamps=False,
        price_hint_per_hour_usd=0.0,
        languages="EN (efektif)",
        notes=(
            "Endpoint demo tak resmi (dipakai library speech_recognition). "
            "Rate limit ~50 request/hari yg DIBAGI dgn semua user library di "
            "dunia, tak ada SLA, bisa dimatikan Google kapan saja. Tanpa "
            "timestamp/diarization -> merge PolyScribe pakai pseudo linear + "
            "diarization LOKAL. Kualitas rendah untuk non-Inggris/non-studio."
        ),
        recommendation=(
            "Coba HANYA untuk membuktikan bahwa markitdown/Google Web Speech "
            "kalah dari Whisper. Bukan untuk kerja serius."
        ),
        # Chunk 30 dtk otomatis; batas per-chunk ~1 mnt sebelum timeout.
        auto_chunks=True,
        max_duration_s=0,   # per-chunk 30 dtk aman; total bebas
        max_size_mb=0,
        warn_notes=(
            "Rate limit ~50 request/hari share ke semua user library "
            "speech_recognition di dunia. File > 15 menit = > 30 chunk = risiko "
            "kena limit tinggi. Pakai backend berbayar untuk file panjang."
        ),
    ),
    ProviderInfo(
        key="groq",
        display_name="Groq — Whisper large-v3 (termurah + tercepat)",
        needs_key=True,
        has_diarization=False,
        has_timestamps=True,
        price_hint_per_hour_usd=0.04,
        languages="EN/AR/ID + 96 bahasa",
        notes=(
            "Whisper large-v3 di LPU Groq — model yg SAMA dgn offline PolyScribe "
            "tapi jauh lebih cepat (200-300x realtime). Batas file 25 MB per "
            "request (chunker otomatis). Timestamp per-segmen, tanpa diarization "
            "(pakai lokal). Rekomendasi utama untuk kombinasi harga+kecepatan."
        ),
        recommendation="Pilih ini kalau ingin cepat & murah dgn kualitas Whisper.",
        # Chunk 5 mnt otomatis (WAV 16k mono ~1.9 MB/mnt = 9.6 MB, aman < 25 MB).
        auto_chunks=True,
        max_size_mb=25.0,     # batas Groq per request; chunker pastikan chunk < ini
        max_duration_s=0,     # per-chunk 5 mnt aman; total bebas
    ),
    ProviderInfo(
        key="deepgram",
        display_name="Deepgram Nova-3 (kualitas tertinggi, native diarization)",
        needs_key=True,
        has_diarization=True,
        has_timestamps=True,
        price_hint_per_hour_usd=0.26,
        languages="EN/AR/ID + 30+ bahasa",
        notes=(
            "Model Nova-3 milik Deepgram. Timestamp word-level & speaker labels "
            "native (kita tetap pakai diarization lokal untuk konsistensi output). "
            "Kredit gratis $200 saat daftar cukup untuk ~700 jam. Streaming + "
            "batch. WER seringkali menang di leaderboard 2025-2026."
        ),
        recommendation="Pilih ini kalau kualitas > biaya.",
        # Upload utuh, batas resmi Deepgram: 2 GB / 10 jam per file.
        auto_chunks=False,
        max_size_mb=2048.0,
        max_duration_s=36000.0,   # 10 jam
    ),
    ProviderInfo(
        key="openai_whisper",
        display_name="OpenAI Whisper API (reliable, kualitas dikenal)",
        needs_key=True,
        has_diarization=False,
        has_timestamps=True,
        price_hint_per_hour_usd=0.36,
        languages="EN/AR/ID + 99 bahasa",
        notes=(
            "Whisper large-v2 di cloud OpenAI. Batas file 25 MB (chunker "
            "otomatis). Timestamp per-segmen. Tanpa diarization. Reliable "
            "tapi mahal dibanding Groq untuk kualitas serupa."
        ),
        recommendation="Pilih ini kalau sudah punya akun OpenAI & mau simpel.",
        auto_chunks=True,
        max_size_mb=25.0,
        max_duration_s=0,
    ),
    ProviderInfo(
        key="assemblyai",
        display_name="AssemblyAI Universal-2 (setara Deepgram)",
        needs_key=True,
        has_diarization=True,
        has_timestamps=True,
        price_hint_per_hour_usd=0.37,
        languages="EN + 20+ bahasa (AR/ID terbatas)",
        notes=(
            "Universal-2 model. Upload + polling (tak streaming di adapter ini). "
            "Word timestamps + speaker labels native. Kualitas Arab lebih "
            "lemah dari Deepgram menurut benchmark komunitas 2025."
        ),
        recommendation="Alternatif Deepgram — komunitas lebih besar, doc lebih rapi.",
        # Batas resmi AssemblyAI: 5 GB / 10 jam per file.
        auto_chunks=False,
        max_size_mb=5120.0,
        max_duration_s=36000.0,
    ),
    ProviderInfo(
        key="azure_speech",
        display_name="Azure Speech (rekomendasi resmi markitdown)",
        needs_key=True,
        has_diarization=True,
        has_timestamps=True,
        price_hint_per_hour_usd=1.00,
        languages="EN/AR/ID + 100+ bahasa (paling luas)",
        notes=(
            "Yang direkomendasi dokumentasi markitdown sendiri untuk kerja "
            "serius. Butuh API key + REGION (mis. 'eastus'). Fast Transcription "
            "API (2024-11) sync — upload multipart, respons langsung. Mahal tapi "
            "dukungan bahasa paling luas."
        ),
        recommendation="Pilih ini kalau organisasimu memang di ekosistem Azure.",
        # Fast Transcription API: 200 MB / 2 jam per request.
        # Untuk file lebih besar butuh Batch Transcription (perlu Blob Storage) —
        # tak diimplementasi di adapter ini.
        auto_chunks=False,
        max_size_mb=200.0,
        max_duration_s=7200.0,    # 2 jam
    ),
    ProviderInfo(
        key="google_cloud",
        display_name="Google Cloud Speech chirp_2 (BEDA dari Google Web Speech)",
        needs_key=True,
        has_diarization=True,
        has_timestamps=True,
        price_hint_per_hour_usd=0.96,
        languages="EN/AR/ID + 125+ bahasa",
        notes=(
            "Model chirp_2 milik Google (bukan endpoint demo Web Speech). Butuh "
            "API key resmi dari Google Cloud Console. Timestamp word-level, "
            "diarization native. Kualitas Arab bagus. Setup akun Google Cloud "
            "cukup ribet (billing, project ID)."
        ),
        recommendation="Pilih ini kalau sudah pakai Google Cloud Platform.",
        # Batas KERAS API v2 recognize inline: 10 MB body / 60 dtk audio.
        # Untuk file lebih panjang HARUS pakai BatchRecognize + GCS URI —
        # tak diimplementasi (butuh Cloud Storage bucket + auth ADC).
        auto_chunks=False,
        max_size_mb=10.0,
        max_duration_s=60.0,
        warn_notes=(
            "PENTING: adapter ini pakai mode sinkron (inline) yg BATAS KERASNYA "
            "60 detik audio. Untuk file lebih panjang, pilih provider lain — "
            "Google Cloud batch async butuh setup GCS bucket yg belum kita "
            "dukung."
        ),
    ),
]

_PROVIDER_MAP = {p.key: p for p in _PROVIDERS}


def list_providers() -> list[ProviderInfo]:
    """Semua provider terdaftar, urutan rekomendasi (bukan alfabet)."""
    return list(_PROVIDERS)


def get_provider_info(key: str) -> Optional[ProviderInfo]:
    return _PROVIDER_MAP.get(key)


def build_backend(key: str, config):
    """Factory: instansiasi backend dari nama provider.

    Import ditunda ke sini supaya `import polyscribe` tak menyeret paket cloud
    (mis. speech_recognition) kalau tak dipakai. Kalau modul adapter gagal
    di-import (dep hilang), lempar RuntimeError dgn pesan yg jelas."""
    if key not in _PROVIDER_MAP:
        raise ValueError(f"Provider cloud tak dikenal: {key}")
    try:
        if key == "google_web":
            from .google_web import GoogleWebSpeechBackend
            return GoogleWebSpeechBackend(config)
        if key == "groq":
            from .groq import GroqWhisperBackend
            return GroqWhisperBackend(config)
        if key == "deepgram":
            from .deepgram import DeepgramNovaBackend
            return DeepgramNovaBackend(config)
        if key == "openai_whisper":
            from .openai_whisper import OpenAIWhisperBackend
            return OpenAIWhisperBackend(config)
        if key == "assemblyai":
            from .assemblyai import AssemblyAIBackend
            return AssemblyAIBackend(config)
        if key == "azure_speech":
            from .azure_speech import AzureSpeechBackend
            return AzureSpeechBackend(config)
        if key == "google_cloud":
            from .google_cloud import GoogleCloudSpeechBackend
            return GoogleCloudSpeechBackend(config)
    except ImportError as e:
        raise RuntimeError(
            f"Backend cloud '{key}' butuh dependency tambahan. "
            f"Jalankan: pip install -r requirements-cloud.txt\n\nDetail: {e}"
        )
    raise ValueError(f"Provider terdaftar tapi factory belum diimplementasi: {key}")


__all__ = ["ProviderInfo", "list_providers", "get_provider_info", "build_backend"]
