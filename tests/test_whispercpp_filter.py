"""Uji filter segmen sampah whisper-cli (brief 24 #2): buang murni-simbol,
pertahankan apa pun yang mengandung huruf/angka."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polyscribe.asr.whispercpp_backend import _is_symbol_only, _words_from_tokens


def test_drops_dash_garbage():
    for junk in ["-", "- - -", "- - - - -", "...", ". . .", "—", "  -  ", "!?.,"]:
        assert _is_symbol_only(junk), f"seharusnya dibuang: {junk!r}"


def test_keeps_real_text():
    for keep in ["Okay.", "yes", "5,000", "F-1", "A", "so we have NPR", "Maryam Al-Ghaif"]:
        assert not _is_symbol_only(keep), f"seharusnya dipertahankan: {keep!r}"


def test_keeps_text_with_symbols_mixed():
    # Ada huruf/angka -> pertahankan walau banyak tanda hubung.
    assert not _is_symbol_only("well - maybe - yes")
    assert not _is_symbol_only("phase 1 - 2 - 3")


def _tok(text, a, b):
    return {"text": text, "offsets": {"from": a, "to": b}}


def test_words_from_tokens_grouping():
    # Token BPE -> kata; spasi awal = kata baru; tanda baca menempel; skip [_BEG_].
    tokens = [
        _tok("[_BEG_]", 0, 0),
        _tok(" You", 100, 300), _tok(" are", 300, 500), _tok(" not", 500, 700),
        _tok(" strategy", 700, 1200), _tok("?", 1200, 1250),
        _tok(" No", 1600, 1800), _tok(",", 1800, 1820),
        _tok(" IT", 1820, 2000), _tok(".", 2000, 2050),
    ]
    words = _words_from_tokens(tokens)
    assert [w.text for w in words] == ["You", "are", "not", "strategy?", "No,", "IT."]
    assert abs(words[0].start - 0.10) < 1e-6            # ms -> detik
    assert abs(words[3].end - 1.25) < 1e-6              # "strategy?" akhir token '?'
    assert abs(words[4].start - 1.60) < 1e-6            # "No," mulai
    assert abs(words[5].end - 2.05) < 1e-6              # "IT." akhir


def test_words_from_tokens_empty():
    assert _words_from_tokens([]) == []
    assert _words_from_tokens([_tok("[_BEG_]", 0, 0), _tok("[_TT_50]", 0, 0)]) == []


def _cmd(**overrides):
    """Baris perintah whisper-cli yang SEBENARNYA dibangun, dari Config asli."""
    from polyscribe.config import Config
    from polyscribe.asr.whispercpp_backend import WhisperCppVulkanBackend
    cfg = Config()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return WhisperCppVulkanBackend(cfg)._build_cmd("a.wav", "a", "en")


def test_cmd_uses_config_max_context():
    from polyscribe.config import Config
    cmd = _cmd()
    assert "-mc" in cmd
    assert cmd[cmd.index("-mc") + 1] == str(Config().whispercpp_max_context)


def test_cmd_passes_initial_prompt():
    """Regresi 2026-08-10: `asr_initial_prompt` hanya tersambung ke faster-whisper,
    jadi di laptop AMD (backend ini) knob-nya diam-diam mati. Sekarang dijaga tes."""
    cmd = _cmd(asr_initial_prompt="Halo. Ini contoh, dengan tanda baca.")
    assert "--prompt" in cmd
    assert cmd[cmd.index("--prompt") + 1] == "Halo. Ini contoh, dengan tanda baca."
    assert "--carry-initial-prompt" in cmd      # default: ulangi tiap jendela


def test_cmd_carry_can_be_disabled():
    cmd = _cmd(asr_initial_prompt="Contoh.", asr_carry_initial_prompt=False)
    assert "--prompt" in cmd and "--carry-initial-prompt" not in cmd


def test_default_prompt_only_for_english():
    """GERBANG KESELAMATAN (brief 51). Diukur di fixture Arab 90 detik:
      - prompt Inggris pada audio Arab -> whisper MENERJEMAHKAN (100% Arab -> 0%);
      - prompt Arab pada audio Arab -> output runtuh jadi 3 segmen identik.
    Jadi prompt default HANYA boleh menyala untuk bahasa yang sudah diukur (en).
    Kalau tes ini merah, transkrip Arab user rusak SENYAP — jangan dilonggarkan
    tanpa mengukur ulang di fixture Arab."""
    from polyscribe.config import Config
    en = Config()
    en.primary_language = "en"
    assert en.effective_initial_prompt(), "en harus dapat contoh tanda baca"
    for lang in ("ar", "id", "auto"):
        cfg = Config()
        cfg.primary_language = lang
        assert cfg.effective_initial_prompt() == "", f"{lang} tak boleh dapat prompt"
        cmd = _cmd(primary_language=lang)
        assert "--prompt" not in cmd, f"--prompt bocor ke bahasa {lang}"


def test_explicit_prompt_wins_over_language_default():
    # User yang sengaja mengisi prompt tetap dihormati, bahasa apa pun.
    cmd = _cmd(primary_language="ar", asr_initial_prompt="Contoh, dengan tanda baca.")
    assert cmd[cmd.index("--prompt") + 1] == "Contoh, dengan tanda baca."


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {name}"); passed += 1
            except Exception:
                print(f"FAIL {name}"); traceback.print_exc(); failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
