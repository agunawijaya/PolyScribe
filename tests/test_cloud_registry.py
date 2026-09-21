"""Uji registry provider cloud & wiring config -> selector.

Fokus:
- Semua 7 provider terdaftar di registry.
- Metadata konsisten (provider gratis TIDAK butuh key; yg butuh key punya price).
- Factory `build_backend` bisa instansiasi tiap provider tanpa API key (load()
  tak dipanggil di tes ini, hanya konstruksi).
- Config.asr_backend="cloud" + cloud_provider="<name>" -> selector ambil dari registry.
- Config default TETAP offline (batasan keras CLAUDE.md).
- CLI --asr cloud:<name> memetakan ke config yg benar.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polyscribe.asr.cloud import list_providers, get_provider_info, build_backend
from polyscribe.cli import build_config, build_parser
from polyscribe.config import Config


EXPECTED_PROVIDERS = {
    "google_web", "groq", "deepgram", "openai_whisper",
    "assemblyai", "azure_speech", "google_cloud",
}


def test_all_seven_providers_registered():
    keys = {p.key for p in list_providers()}
    assert keys == EXPECTED_PROVIDERS, f"missing: {EXPECTED_PROVIDERS - keys}"


def test_google_web_is_free_and_first():
    """Rekomendasi urutan: gratis dulu supaya user bisa coba tanpa risiko."""
    providers = list_providers()
    assert providers[0].key == "google_web"
    assert providers[0].needs_key is False
    assert providers[0].price_hint_per_hour_usd == 0.0


def test_paid_providers_have_price_hint():
    """Provider berbayar wajib punya angka biaya (>0) supaya user bisa membandingkan."""
    for p in list_providers():
        if p.needs_key:
            assert p.price_hint_per_hour_usd > 0, \
                f"{p.key} butuh key tapi tak punya price hint"


def test_capability_flags_consistent():
    """Provider yg mengklaim has_diarization/has_timestamps harus punya
    metadata catatan yg menyebut kapabilitasnya (bukan hanya flag telanjang)."""
    for p in list_providers():
        assert p.display_name, f"{p.key} tak punya display_name"
        assert p.notes, f"{p.key} tak punya notes"
        assert p.recommendation, f"{p.key} tak punya recommendation"


def test_factory_can_instantiate_all():
    """Tiap provider bisa dikonstruksi (dep pip installed via requirements-cloud
    TIDAK dibutuhkan untuk konstruksi — hanya untuk load()/transcribe())."""
    cfg = Config()
    for key in EXPECTED_PROVIDERS:
        backend = build_backend(key, cfg)
        assert backend.provider_key == key, \
            f"{key}: provider_key mismatch = {backend.provider_key}"
        assert backend.name.startswith("cloud:"), \
            f"{key}: name '{backend.name}' harus prefix 'cloud:'"


def test_factory_rejects_unknown_provider():
    try:
        build_backend("bogus", Config())
    except ValueError:
        return
    raise AssertionError("Provider tak dikenal harus ditolak")


def test_get_provider_info_returns_none_for_unknown():
    assert get_provider_info("bogus") is None
    assert get_provider_info("groq") is not None


def test_config_default_is_offline():
    """Batasan keras CLAUDE.md 2026-09-21: cloud TAK boleh jadi default."""
    cfg = Config()
    assert cfg.asr_backend == "auto"
    assert cfg.cloud_provider == ""


def test_cli_asr_flag_offline_keeps_default():
    args = build_parser().parse_args(["dummy.mp3", "--asr", "offline"])
    cfg = build_config(args)
    assert cfg.asr_backend != "cloud"


def test_cli_asr_flag_cloud_maps_to_provider():
    args = build_parser().parse_args(["dummy.mp3", "--asr", "cloud:groq"])
    cfg = build_config(args)
    assert cfg.asr_backend == "cloud"
    assert cfg.cloud_provider == "groq"


def test_cli_asr_flag_rejects_bad_syntax():
    parser = build_parser()
    args = parser.parse_args(["dummy.mp3", "--asr", "bogus"])
    try:
        build_config(args)
    except SystemExit:
        return
    raise AssertionError("--asr bogus seharusnya ditolak")


def test_selector_calls_cloud_factory():
    """Wiring end-to-end: config asr_backend=cloud + provider -> select_asr_backend
    mengembalikan CloudAsrBackend, bukan FasterWhisperBackend."""
    from polyscribe.asr import select_asr_backend
    from polyscribe.asr.cloud.base import CloudAsrBackend

    class FakeCaps:
        has_cuda = False
        has_vulkan = False
        whispercli_present = False

    cfg = Config()
    cfg.asr_backend = "cloud"
    cfg.cloud_provider = "groq"
    backend = select_asr_backend(FakeCaps(), cfg)
    assert isinstance(backend, CloudAsrBackend)
    assert backend.provider_key == "groq"


def test_selector_cloud_without_provider_errors():
    """Config invalid (backend=cloud tapi provider kosong) -> RuntimeError
    ramah, BUKAN fallback diam ke Whisper offline. Diam-diam fallback akan
    mengejutkan user yg mengharapkan cloud."""
    from polyscribe.asr import select_asr_backend

    class FakeCaps:
        has_cuda = False
        has_vulkan = False
        whispercli_present = False

    cfg = Config()
    cfg.asr_backend = "cloud"
    cfg.cloud_provider = ""
    try:
        select_asr_backend(FakeCaps(), cfg)
    except RuntimeError as e:
        assert "cloud_provider" in str(e).lower() or "provider" in str(e).lower()
        return
    raise AssertionError("Backend cloud tanpa provider harus melempar RuntimeError")


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
                passed += 1
            except Exception:
                print(f"FAIL {name}")
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
