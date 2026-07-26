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
