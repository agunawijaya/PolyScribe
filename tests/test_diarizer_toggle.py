"""Uji toggle Cepat/Akurat (brief 37): selector + fallback aman + flag CLI.

Fokus di lapis UI/selector (bukan pipeline/ASR/kontrak Diarizer). Tanpa torch:
`pyannote_availability` & `select_diarizer` harus JATUH aman ke sherpa, bukan crash.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polyscribe.config import Config
from polyscribe.diarization import pyannote_availability, select_diarizer
from polyscribe.diarization.sherpa_onnx_backend import SherpaOnnxDiarizer
from polyscribe.cli import build_config, build_parser


def _cfg_without_pyannote_model():
    """Config yang diarahkan ke models_dir kosong -> config.yaml pyannote TAK ada."""
    cfg = Config()
    cfg.models_dir = Path(tempfile.mkdtemp(prefix="ps_nomodel_"))
    return cfg


def test_availability_false_when_model_absent():
    cfg = _cfg_without_pyannote_model()
    ready, reason = pyannote_availability(cfg)
    assert ready is False
    assert reason                      # ada pesan ramah, tak kosong


def test_select_falls_back_to_sherpa_when_pyannote_unavailable():
    # Diminta pyannote tapi model tak ada -> DAPAT sherpa, TIDAK crash.
    cfg = _cfg_without_pyannote_model()
    cfg.diarizer_choice = "pyannote"
    diar = select_diarizer(cfg)
    assert isinstance(diar, SherpaOnnxDiarizer)


def test_select_sherpa_when_asked():
    cfg = Config()
    cfg.diarizer_choice = "sherpa"
    assert isinstance(select_diarizer(cfg), SherpaOnnxDiarizer)


def test_default_choice_is_pyannote():
    # Default produk brief 37 = Akurat (pyannote).
    assert Config().diarizer_choice == "pyannote"


def test_cli_flag_sets_choice():
    args = _parse_cli(["dummy.mp3", "--diarizer", "sherpa"])
    assert build_config(args).diarizer_choice == "sherpa"
    args = _parse_cli(["dummy.mp3", "--diarizer", "pyannote"])
    assert build_config(args).diarizer_choice == "pyannote"


def test_cli_flag_absent_keeps_default():
    # Tanpa --diarizer, build_config tak menimpa default config (pyannote).
    args = _parse_cli(["dummy.mp3"])
    assert build_config(args).diarizer_choice == "pyannote"


def test_cli_rejects_bad_diarizer():
    try:
        _parse_cli(["dummy.mp3", "--diarizer", "bogus"])
    except SystemExit:
        return                          # argparse menolak pilihan tak sah
    raise AssertionError("--diarizer bogus seharusnya ditolak")


def test_tuning_preset_differs_per_diarizer():
    """Brief 50: knob cleanup/merge default = hasil tuning SHERPA. Mode Akurat
    (pyannote) harus memakai preset sendiri (tanpa perataan), bukan knob sherpa —
    kalau tidak, interjeksi cepat yang jadi alasan mode ini ada malah diratakan."""
    cfg = Config()
    sherpa = cfg.tuning_for_diarizer("sherpa")
    pyannote = cfg.tuning_for_diarizer("pyannote")
    assert sherpa == (cfg.diar_min_turn, cfg.diar_min_speaker_frac,
                      cfg.merge_island_max_s)
    assert pyannote == (0.0, 0.0, 0.0)
    assert sherpa != pyannote, "preset Akurat tak boleh sama dengan knob sherpa"


def test_tuning_follows_actual_diarizer_after_fallback():
    # Mode Akurat diminta tapi jatuh ke sherpa: knob yang dipakai HARUS knob sherpa.
    cfg = Config()
    cfg.diarizer_choice = "pyannote"
    assert cfg.tuning_for_diarizer("sherpa") == (cfg.diar_min_turn,
                                                 cfg.diar_min_speaker_frac,
                                                 cfg.merge_island_max_s)


def _parse_cli(argv):
    """Pakai parser CLI YANG ASLI (bukan tiruan) supaya tak bisa melenceng."""
    return build_parser().parse_args(argv)


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
