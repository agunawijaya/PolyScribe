"""Backend ASR cloud (opt-in — jalur default tetap offline).

Semua adapter di sini mengikuti kontrak `AsrBackend` yang sama seperti backend
lokal, jadi `pipeline.py` tak sadar perbedaannya. Pemilihan lewat registry.

Provider yang tersedia dilihat via `list_providers()`; instance dibuat via
`build_backend(provider_name, config)`. Adapter mengambil API key sendiri dari
`polyscribe.keystore` saat `load()` — kalau tak ada, melempar RuntimeError yg
GUI/CLI tangkap dgn pesan "silakan set API key di tab Backend & API Keys".
"""

from .base import CloudAsrBackend
from .registry import (
    ProviderInfo, list_providers, get_provider_info, build_backend,
)
from .validation import Verdict, validate_audio

__all__ = [
    "CloudAsrBackend", "ProviderInfo",
    "list_providers", "get_provider_info", "build_backend",
    "Verdict", "validate_audio",
]
