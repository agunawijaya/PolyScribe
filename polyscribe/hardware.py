"""Deteksi kemampuan mesin — dipanggil sekali saat start.

Satu tempat untuk "mesin ini punya apa": CUDA, Vulkan, profil build, dan apakah
binary whisper-cli Vulkan ikut dibundel. Sengaja ringan & tahan-error: kalau
satu cek gagal, anggap fitur itu tidak ada — jangan sampai app-nya ikut mati.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .config import PROJECT_ROOT


@dataclass
class Capabilities:
    has_cuda: bool            # GPU NVIDIA + runtime CUDA siap dipakai
    has_vulkan: bool          # driver Vulkan ada (jalur iGPU AMD)
    build_profile: str        # "amd" | "nvidia" — ditanam saat build
    whispercli_present: bool  # binary whisper.cpp Vulkan ikut dibundel?


def detect() -> Capabilities:
    return Capabilities(
        has_cuda=_cuda_ready(),
        has_vulkan=_vulkan_ready(),
        build_profile=_read_build_profile(),
        whispercli_present=_whispercli_exists(),
    )


def _cuda_ready() -> bool:
    # Paling langsung: tanya CTranslate2 (sudah jadi dependency lewat
    # faster-whisper) berapa device CUDA yang terlihat. >0 berarti siap.
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _vulkan_ready() -> bool:
    # Kalau vulkan-1.dll ada, driver Vulkan terpasang. Ini syarat jalur
    # whisper.cpp + Vulkan. Kita tidak enumerasi device di sini supaya cek
    # tetap murah; gerbang bukti GPU dilakukan terpisah di benchmark.
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    dll = Path(system_root) / "System32" / "vulkan-1.dll"
    return dll.exists()


def _read_build_profile() -> str:
    # profile.json ditanam saat packaging (mis. {"profile": "amd"}). Di dev
    # boleh di-set manual. Default "amd" sesuai mesin M1.
    profile_file = PROJECT_ROOT / "profile.json"
    try:
        data = json.loads(profile_file.read_text(encoding="utf-8"))
        return str(data.get("profile", "amd"))
    except Exception:
        return "amd"


def _whispercli_exists() -> bool:
    exe = PROJECT_ROOT / "vendor" / "whisper-cli" / "whisper-cli.exe"
    return exe.exists()


def describe(caps: Capabilities) -> str:
    """Ringkasan satu baris untuk log/CLI."""
    bits = [f"profile={caps.build_profile}"]
    bits.append("CUDA" if caps.has_cuda else "no-CUDA")
    bits.append("Vulkan" if caps.has_vulkan else "no-Vulkan")
    if caps.whispercli_present:
        bits.append("whisper-cli")
    return ", ".join(bits)
