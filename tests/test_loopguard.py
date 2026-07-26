"""Uji LoopDetector: HARUS memicu pada loop, TIDAK memicu pada rapat normal.

Loop palsu = kegagalan buruk (menuduh transkrip bagus rusak). Jadi tes false-
positive di sini penting: dijalankan pada transkrip Std-11 asli + teks penuh
backchannel ("Yeah. Okay. Yes.").
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polyscribe.loopguard import (
    LoopDetector, collapse_repeats, collapse_token_repeats)


def test_triggers_on_repeated_phrase_across_segments():
    # Kasus Std-12: frasa sama diulang sebagai segmen berturut-turut.
    d = LoopDetector()
    fired_at = None
    for i in range(20):
        if d.feed("So, we have NPR. Okay."):
            fired_at = i
            break
    assert fired_at is not None, "loop lintas-segmen tak terdeteksi"
    assert "NPR" in d.sample


def test_triggers_on_repeat_within_one_segment():
    # Satu segmen berisi frasa yang diulang di dalamnya.
    d = LoopDetector()
    text = "so we have npr okay " * 8
    assert d.feed(text) is True


def test_does_not_trigger_on_short_backchannels():
    # "Yeah. Okay. Yes." berulang TAK boleh memicu (unit < min_words).
    d = LoopDetector()
    fired = False
    for _ in range(40):
        for bc in ("Yeah.", "Okay.", "Yes.", "Mm-hmm."):
            fired = fired or d.feed(bc)
    assert not fired, "backchannel pendek memicu loop palsu"


def test_does_not_trigger_on_varied_meeting_text():
    # Kalimat rapat yang berbeda-beda (walau ada pengulangan kata umum) tak memicu.
    d = LoopDetector()
    lines = [
        "So what we think right now in the beginning, we will start it internally.",
        "We will provide through the website, then move to Dubai Now.",
        "No, they have a different team for those services.",
        "We are just supporting during the initial phase.",
        "Then we will hand it over to the Dubai Now team.",
        "We came actually to the services and the details.",
        "Because there is a workflow there for some services.",
        "Even the booking of the meeting rooms is handled differently.",
        "Some of them are paid by the company, others by the client.",
        "Let's say the schools, the university, it's different per floor.",
    ] * 3
    fired = any(d.feed(x) for x in lines)
    assert not fired, "teks rapat bervariasi memicu loop palsu"


# --- pemangkasan loop (brief 34): pangkas pengulangan, sisakan satu instans ---

def test_collapse_trims_intra_segment_loop():
    # Kasus nyata Std-12 (baris 77 std12_full_FINAL): frasa 6-kata diulang 11x
    # di dalam SATU segmen, lalu teks sah menyusul. Harus jadi SATU instans + sisa.
    phrase = "The stipulation I have from another. "
    text = phrase * 11 + "But for example if you have, the road is there."
    out, trimmed = collapse_repeats(text)
    assert trimmed is True
    # frasa hanya muncul sekali sekarang
    assert out.count("stipulation") == 1
    # ekor sah dipertahankan utuh
    assert out.endswith("But for example if you have, the road is there.")


def test_collapse_leaves_clean_text_untouched():
    text = ("So what we think right now, we will start it internally, then move "
            "to the Dubai Now team once the initial phase is done.")
    out, trimmed = collapse_repeats(text)
    assert trimmed is False
    assert out == " ".join(text.split())   # hanya normalisasi spasi, isi sama


def test_collapse_ignores_legit_backchannel():
    # "Okay. Okay. Yes." (pengulangan pendek < ambang) TAK boleh dipangkas.
    for text in ("Okay. Okay. Yes.", "Yeah. Yeah. Yeah.", "No, no, no."):
        out, trimmed = collapse_repeats(text)
        assert trimmed is False, f"backchannel sah terpangkas: {text!r}"


def test_collapse_below_threshold_not_trimmed():
    # Frasa diulang hanya 3x (< intra_repeat=6) — bukan loop, jangan disentuh.
    text = "this is not from the current. " * 3
    _, trimmed = collapse_repeats(text)
    assert trimmed is False


def test_collapse_token_repeats_preserves_first_instance_timestamps():
    # Level-kata: token berulang -> sisakan instans PERTAMA (dengan stempel waktunya).
    class W:
        def __init__(self, s, e, t):
            self.start, self.end, self.text = s, e, t
    words = []
    # "hello world" diulang 8x @ 0.5s per kata, lalu "done."
    for i in range(8):
        words.append(W(i * 1.0, i * 1.0 + 0.4, "hello"))
        words.append(W(i * 1.0 + 0.5, i * 1.0 + 0.9, "world"))
    words.append(W(8.0, 8.4, "done."))
    kept, trimmed = collapse_token_repeats(words, text_of=lambda w: w.text)
    assert trimmed is True
    assert [w.text for w in kept] == ["hello", "world", "done."]
    assert kept[0].start == 0.0 and kept[1].start == 0.5   # instans pertama


def _load_real_transcript():
    # Transkrip Std-11 5-menit asli (q5_0) bila ada di scratchpad — uji nyata.
    p = (r"C:\Users\aguna\AppData\Local\Temp\claude\C--Project-PolyScribe"
         r"\2bb02e6c-8801-4e60-a5cb-3fc859ca1556\scratchpad\q_bench\transcript_q5_0.txt")
    if os.path.exists(p):
        return [ln for ln in open(p, encoding="utf-8").read().splitlines() if ln.strip()]
    return None


def test_no_false_positive_on_real_std11():
    segs = _load_real_transcript()
    if segs is None:
        return  # transkrip tak tersedia di lingkungan ini — lewati diam-diam
    d = LoopDetector()
    fired = [s for s in segs if d.feed(s)]
    assert not fired, f"loop palsu di Std-11 asli: {fired[:2]}"


def test_recovers_and_can_refire():
    # Onset sekali; setelah pulih (teks beda), bisa memicu lagi di loop kedua.
    d = LoopDetector()
    onsets = 0
    stream = (["So, we have NPR. Okay."] * 8
              + ["Now let us discuss the actual project timeline in detail."] * 5
              + ["This is a totally different sentence about budgets and scope."] * 3
              + ["So, we have NPR. Okay."] * 8)
    for x in stream:
        if d.feed(x):
            onsets += 1
    assert onsets == 2, f"harusnya 2 onset (dua wilayah loop), dapat {onsets}"


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
