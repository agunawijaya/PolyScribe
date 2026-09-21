"""Pemilihan backend ASR — factory kecil, bukan magic.

Urutan prioritas eksplisit: CUDA (paling cepat & simpel di NVIDIA) -> Vulkan
(jalur cepat AMD) -> CPU int8 (selalu bisa). `device='auto'` faster-whisper TIDAK
memilih Vulkan, jadi pemilihan Vulkan harus di sini, bukan diserahkan ke auto.
"""

from .base import AsrBackend, AsrSegment, Word
from .faster_whisper_backend import FasterWhisperBackend


def select_asr_backend(caps, config) -> AsrBackend:
    # Override eksplisit dari CLI menang atas deteksi otomatis.
    forced = getattr(config, "asr_backend", "auto")

    # Jalur cloud (2026-09-21 — opt-in, jangan pernah dipilih auto). Provider
    # dipilih di config.cloud_provider; kesalahan konfigurasi (kosong / tak
    # dikenal) melempar RuntimeError dgn pesan ramah supaya GUI/CLI tampilkan.
    if forced == "cloud":
        return _cloud(config)

    if forced == "faster-whisper":
        return _faster_whisper_for(caps, config)
    if forced == "whispercpp":
        return _whispercpp(config)

    # forced == "auto": ikuti tangga prioritas.
    if caps.has_cuda:
        # NVIDIA: faster-whisper langsung di CUDA. Backend B tak perlu.
        return _fw(config, device="cuda", default_compute="float16")

    if caps.has_vulkan and caps.whispercli_present and config.allow_vulkan:
        # AMD: whisper.cpp di iGPU. Kalau benchmark M1 membuktikan ini TIDAK
        # lebih cepat/stabil, set allow_vulkan=False -> otomatis turun ke CPU.
        return _whispercpp(config)

    # Fallback universal — tidak pernah gagal karena hardware.
    return _fw(config, device="cpu", default_compute="int8")


def _faster_whisper_for(caps, config) -> AsrBackend:
    # Dipaksa faster-whisper: tetap hormati CUDA bila ada, else CPU int8.
    if caps.has_cuda:
        return _fw(config, device="cuda", default_compute="float16")
    return _fw(config, device="cpu", default_compute="int8")


def _fw(config, device, default_compute) -> AsrBackend:
    """Bangun FasterWhisperBackend dengan setelan dari config (satu tempat)."""
    be = FasterWhisperBackend(
        config.faster_whisper_dir,
        device=device,
        compute_type=config.asr_compute_type or default_compute,
        primary_language=getattr(config, "primary_language", "en"),
    )
    # Knob kualitas (opt-in di config; default backward-compatible). Set sbg
    # atribut instance karena FasterWhisperBackend.__init__ tidak menerimanya —
    # transcribe() baca via getattr dgn default aman.
    be.vad_filter = bool(getattr(config, "vad_filter", True))
    be.initial_prompt = str(getattr(config, "asr_initial_prompt", "") or "")
    return be


def _whispercpp(config) -> AsrBackend:
    # Backend B (Vulkan) di-de-risk terpisah dan belum diintegrasi (post-M1c).
    # Beri pesan ramah alih-alih ImportError mentah bila modulnya belum ada.
    try:
        from .whispercpp_backend import WhisperCppVulkanBackend
    except ImportError:
        raise RuntimeError(
            "Backend B (whisper.cpp Vulkan) belum tersedia — masih di jalur CPU. "
            "Pakai --backend faster-whisper atau --backend auto."
        )
    return WhisperCppVulkanBackend(config)


def _cloud(config) -> AsrBackend:
    """Bangun backend cloud dari registry. Kesalahan konfigurasi (provider kosong
    atau tak dikenal) diangkat sbg RuntimeError dgn pesan yg GUI/CLI tampilkan."""
    provider = getattr(config, "cloud_provider", "") or ""
    if not provider:
        raise RuntimeError(
            "Backend cloud diminta tapi cloud_provider kosong. Pilih provider "
            "di GUI (tab 'Backend & API Keys') atau --asr cloud:<provider>."
        )
    from .cloud import build_backend
    return build_backend(provider, config)


__all__ = [
    "AsrBackend", "AsrSegment", "Word",
    "FasterWhisperBackend", "select_asr_backend",
]
