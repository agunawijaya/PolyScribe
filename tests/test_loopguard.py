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


def test_no_false_positive_on_real_std11():
    """Detektor di transkrip rapat NYATA. Dulu tes ini membaca path dari env var
    dan, kalau tak diset, `return` diam-diam — jadi selalu hijau tanpa menguji
    apa pun (ketahuan 2026-08-10). Sekarang memakai fixture yang ikut repo.

    Fixture memang memuat SATU halusinasi berulang, jadi detektor harus memicu
    tepat sekali — di situ — dan diam di seluruh ucapan lain."""
    from polyscribe.loopguard import _normalize
    segs = _std11_fixture_segments()
    assert segs, "fixture Std-11 hilang — gerbang tak boleh lewat diam-diam"
    d = LoopDetector()
    fired = [s.text for s in segs if d.feed(s.text)]
    assert len(fired) <= 1, f"loop palsu di ucapan nyata: {fired[:2]}"
    if fired:
        assert "still in progress" in _normalize(fired[0]), \
            f"memicu di ucapan yang salah: {fired[0][:80]}"


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


def _mkseg(start, text):
    """Segmen ASR dgn word-timestamp 1 kata/detik — cukup untuk uji pemangkasan."""
    from polyscribe.asr.base import AsrSegment, Word
    ws = [Word(start + i, start + i + 0.9, w) for i, w in enumerate(text.split())]
    return AsrSegment(start=start, end=ws[-1].end, text=text, language="en", words=ws)


def test_stream_collapse_catches_loop_split_across_segments():
    """Bug user 2026-08-10: whisper.cpp memuntahkan loop sebagai segmen ~1 detik
    berisi SATU instans, jadi pemangkas per-segmen buta terhadapnya."""
    from polyscribe.loopguard import collapse_stream_repeats

    segs = [_mkseg(0.0, "okay so tell me about the shelf numbering please")]
    segs += [_mkseg(10.0 + i, "What is it?") for i in range(9)]
    segs += [_mkseg(30.0, "it is the shelf number five")]

    # Per-segmen: tak ada yang terlihat (tiap segmen cuma 1 instans).
    for s in segs:
        _kept, trimmed = collapse_token_repeats(s.words, text_of=lambda w: w.text)
        assert not trimmed

    out, times = collapse_stream_repeats(segs)
    assert times, "pengulangan lintas-segmen tak terpangkas"
    total = sum(_normalized_count(s, "what is it") for s in out)
    assert total == 1, f"harus tersisa satu instans, dapat {total}"
    # Teks di sekitarnya tak boleh hilang.
    joined = " ".join(s.text for s in out)
    assert "shelf numbering" in joined and "shelf number five" in joined


def _normalized_count(seg, phrase):
    from polyscribe.loopguard import _normalize
    return _normalize(seg.text).count(phrase)


def test_stream_collapse_leaves_normal_backchannel_alone():
    # Rapat normal: "Okay."/"Yes." berulang tapi TAK berturut-turut identik 6x.
    from polyscribe.loopguard import collapse_stream_repeats
    texts = ["Okay.", "Yes I agree with that point.", "Okay.", "But the shelves change.",
             "Yes.", "We can update the map later.", "Okay.", "Right."]
    segs = [_mkseg(float(i * 5), t) for i, t in enumerate(texts)]
    out, times = collapse_stream_repeats(segs)
    assert times == [], f"backchannel wajar tak boleh dipangkas: {times}"
    assert [s.text for s in out] == texts


def _std11_fixture_segments():
    """Transkrip Std-11 5 menit dari `tests/fixtures` — rapat NYATA, ikut repo.

    Dipakai menggantikan `_load_real_transcript()` yang bergantung env var: kalau
    env var tak diset, tes itu lewat TANPA menguji apa pun (ketahuan 2026-08-10) —
    gerbang yang selalu hijau bukan gerbang. Fixture ini selalu ada."""
    import os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "fixtures", "std11_gt_5min.txt")
    if not os.path.exists(p):
        return None
    segs, t = [], 0.0
    with open(p, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln or ln.startswith("[") and "===" in ln:
                continue                      # lewati baris penanda, bukan ucapan
            segs.append(_mkseg(t, ln))
            t += len(ln.split()) + 1
    return segs


def test_stream_collapse_catches_real_loop_in_std11_fixture():
    """Gerbang POSITIF di loop ASR nyata yang tak kita buat sendiri: fixture Std-11
    memuat halusinasi "it's still in progress" berulang (file-nya sendiri menandainya
    PERINGATAN). Pemangkas WAJIB menangkapnya."""
    from polyscribe.loopguard import collapse_stream_repeats, _normalize
    segs = _std11_fixture_segments()
    assert segs, "fixture Std-11 hilang — gerbang ini tak boleh lewat diam-diam"
    before = sum(_normalize(s.text).count("it s still in progress") for s in segs)
    assert before >= 6, f"fixture berubah; pengulangan tinggal {before}"
    out, times = collapse_stream_repeats(segs)
    assert len(times) == 1, f"harus tepat 1 wilayah dipangkas, dapat {len(times)}"
    after = sum(_normalize(s.text).count("it s still in progress") for s in out)
    assert after < before, "pengulangan tak berkurang"


def test_stream_collapse_trims_only_the_loop_in_std11():
    """Gerbang NEGATIF: di 718 kata rapat NYATA, TEPAT SATU wilayah boleh dipangkas —
    halusinasi yang sudah dikenal. Sisa ucapan (basa-basi, kata terulang, "yes yes")
    tak boleh tersentuh. Ini pasangan negatif dari tes di atas; keduanya memakai
    korpus yang sama supaya tak ada celah 'lulus karena tak menguji apa-apa'."""
    from polyscribe.loopguard import collapse_stream_repeats, _normalize
    segs = _std11_fixture_segments()
    assert segs and sum(len(s.words) for s in segs) > 500, "korpus terlalu kecil"
    out, times = collapse_stream_repeats(segs)
    assert len(times) == 1, f"hanya wilayah loop yang boleh dipangkas: {times}"
    # Wilayah yang dipangkas memang wilayah halusinasi itu, bukan ucapan lain.
    hit = [s for s in segs if s.start <= times[0] <= s.end]
    assert hit and "still in progress" in _normalize(hit[0].text), \
        "yang dipangkas bukan wilayah loop yang dimaksud"
    # Kata di luar wilayah loop tak berkurang satu pun.
    def clean_words(ss):
        return sum(len(s.words) for s in ss
                   if "still in progress" not in _normalize(s.text))
    assert clean_words(out) == clean_words(segs), "ucapan non-loop ikut terpangkas"


class _FakeWriter:
    """Penulis palsu: rekam urutan baris & penanda persis seperti yang masuk .txt."""

    def __init__(self):
        self.out = []          # ("note", teks) | ("line", MergedLine)

    def write_note(self, text):
        self.out.append(("note", text))

    def write_line(self, line):
        self.out.append(("line", line))

    def reset(self):
        self.out = []


def _times_in_order(out):
    """Ambil timestamp tiap keluaran (detik) sesuai yang tampak di .txt."""
    times = []
    for kind, payload in out:
        if kind == "note":
            hms = payload[1:payload.index("]")]
            h, m, s = (int(x) for x in hms.split(":"))
            times.append(h * 3600 + m * 60 + s)
        else:
            times.append(payload.start)
    return times


def test_loop_note_lands_in_time_order():
    """Regresi bug user 2026-08-10 (`Standard recording 22.txt`): penanda loop
    muncul SEBELUM baris yang waktunya lebih awal ([00:10:12] di atas [00:09:12]).

    Akarnya: merger menahan baris (kalimat belum tuntas + lookahead), penanda tidak.
    Gerbang di sini: timestamp di keluaran TAK BOLEH mundur.
    """
    from polyscribe.asr.base import AsrSegment, Word
    from polyscribe.config import Config
    from polyscribe.diarization.base import SpeakerTurn
    from polyscribe.pipeline import _remerge_wordlevel

    def seg(start, text):
        # Satu kata per detik; tanpa titik supaya kalimat tertahan di merger →
        # persis kondisi yang bikin penanda mendahului baris.
        words = [Word(start + i, start + i + 0.9, w)
                 for i, w in enumerate(text.split())]
        return AsrSegment(start=start, end=words[-1].end, text=text,
                          language="en", words=words)

    loop_text = " ".join(["what is it"] * 8)     # memicu LoopDetector (intra-segmen)
    refined = [
        seg(0.0, "we are talking about the shelves in the library today"),
        seg(20.0, "and the numbers are printed on every single shelf here"),
        seg(40.0, loop_text),
        seg(80.0, "okay let us move on to the next topic please"),
        seg(100.0, "yes that sounds good to me as well thank you"),
    ]
    turns = [SpeakerTurn(0.0, 60.0, "SPEAKER_00"),
             SpeakerTurn(60.0, 200.0, "SPEAKER_01")]
    writer = _FakeWriter()
    lines, loop_times = _remerge_wordlevel(
        refined, turns, Config(), writer, detector_cls=LoopDetector)

    assert loop_times, "loop tak terdeteksi — fixture tes salah, bukan kodenya"
    assert any(k == "note" for k, _ in writer.out), "penanda tak ditulis"
    times = _times_in_order(writer.out)
    assert times == sorted(times), f"timestamp mundur di .txt: {times}"


def test_loop_note_at_tail_still_written():
    """Loop di ekor file: tak ada baris sesudahnya, penanda TETAP harus keluar."""
    from polyscribe.merge import MergedLine
    from polyscribe.pipeline import _ChronoWriter

    writer = _FakeWriter()
    chrono = _ChronoWriter(writer)
    chrono.line(MergedLine(0.0, 10.0, "SPEAKER_00", "halo semua"))
    chrono.note(120.0, "[00:02:00] === PERINGATAN ===")
    chrono.flush()
    assert [k for k, _ in writer.out] == ["line", "note"]


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
