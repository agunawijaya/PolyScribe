"""Uji algoritma penggabungan by overlap waktu (merge.py) dengan data sintetis.

Kasus yang diuji: overlap normal, celah tanpa overlap, dan dua speaker dalam
satu segmen ASR panjang (kasus paling gampang salah kalau merge di level segmen).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polyscribe.asr.base import AsrSegment, Word
from polyscribe.diarization.base import SpeakerTurn
from polyscribe.merge import merge, StreamingMerger, relabel_turns_contiguous


def _seg(start, end, text, words):
    return AsrSegment(start=start, end=end, text=text, language="en",
                      words=[Word(*w) for w in words])


def test_basic_two_speakers():
    # Dua giliran bersih: 0-2 s SPEAKER_00, 2-4 s SPEAKER_01.
    turns = [
        SpeakerTurn(0.0, 2.0, "SPEAKER_00"),
        SpeakerTurn(2.0, 4.0, "SPEAKER_01"),
    ]
    segs = [
        _seg(0.0, 1.8, "hello there", [(0.0, 0.8, "hello"), (0.9, 1.8, "there")]),
        _seg(2.1, 3.9, "hi back", [(2.1, 2.8, "hi"), (3.0, 3.9, "back")]),
    ]
    lines = merge(segs, turns)
    assert len(lines) == 2
    assert lines[0].speaker == "SPEAKER_00"
    assert lines[0].text == "hello there"
    assert lines[1].speaker == "SPEAKER_01"
    assert lines[1].text == "hi back"


def test_two_speakers_in_one_segment():
    # Satu segmen ASR panjang menutupi dua speaker. Level-kata harus memecahnya
    # jadi dua baris; level-segmen akan salah melabeli separuh.
    turns = [
        SpeakerTurn(0.0, 1.0, "SPEAKER_00"),
        SpeakerTurn(1.0, 2.0, "SPEAKER_01"),
    ]
    segs = [
        _seg(0.0, 2.0, "yes no",
             [(0.1, 0.5, "yes"), (1.2, 1.8, "no")]),
    ]
    lines = merge(segs, turns)
    assert len(lines) == 2
    assert lines[0].speaker == "SPEAKER_00" and lines[0].text == "yes"
    assert lines[1].speaker == "SPEAKER_01" and lines[1].text == "no"


def test_word_in_gap_follows_previous():
    # Kata jatuh di celah diarization (tak ada turn yang overlap): harus ikut
    # speaker kata sebelumnya, bukan bikin label baru.
    turns = [SpeakerTurn(0.0, 1.0, "SPEAKER_00")]
    segs = [
        _seg(0.0, 3.0, "one two three",
             [(0.1, 0.5, "one"), (1.5, 1.8, "two"), (2.5, 2.8, "three")]),
    ]
    lines = merge(segs, turns)
    # Semua ikut SPEAKER_00 -> satu baris.
    assert len(lines) == 1
    assert lines[0].speaker == "SPEAKER_00"
    assert lines[0].text == "one two three"


def test_segment_fallback_without_words():
    # Backend tak memberi kata -> fallback level-segmen.
    turns = [
        SpeakerTurn(0.0, 2.0, "SPEAKER_00"),
        SpeakerTurn(2.0, 4.0, "SPEAKER_01"),
    ]
    segs = [
        AsrSegment(0.0, 1.9, "block a", "en", words=[]),
        AsrSegment(2.1, 3.9, "block b", "en", words=[]),
    ]
    lines = merge(segs, turns)
    assert [ln.speaker for ln in lines] == ["SPEAKER_00", "SPEAKER_01"]
    assert [ln.text for ln in lines] == ["block a", "block b"]


def _stream(turns, segs, **kw):
    relabel_turns_contiguous(turns)
    m = StreamingMerger(turns, **kw)
    out = []
    for s in segs:
        out.extend(m.feed(s))
    out.extend(m.finish())
    return out


def test_streaming_sentence_level_two_speakers():
    # Dua kalimat ber-tanda-baca, dua speaker -> dua baris.
    turns = [
        SpeakerTurn(0.0, 2.0, "SPEAKER_00"),
        SpeakerTurn(2.0, 4.0, "SPEAKER_01"),
    ]
    segs = [
        _seg(0.0, 1.8, "Hello there.", [(0.0, 0.8, "Hello"), (0.9, 1.8, "there.")]),
        _seg(2.1, 3.9, "Hi back.", [(2.1, 2.8, "Hi"), (3.0, 3.9, "back.")]),
    ]
    out = _stream(turns, segs)
    assert [(l.speaker, l.text) for l in out] == [
        ("SPEAKER_00", "Hello there."),
        ("SPEAKER_01", "Hi back."),
    ]


def test_sentence_not_split_across_speakers():
    # SATU kalimat menyentuh dua turn -> utuh ke speaker dominan (bukan terpecah).
    # Kalimat 0-4s: overlap SPEAKER_00 (0-1) = 1s, SPEAKER_01 (1-4) = 3s -> 01 dominan.
    turns = [
        SpeakerTurn(0.0, 1.0, "SPEAKER_00"),
        SpeakerTurn(1.0, 4.0, "SPEAKER_01"),
    ]
    segs = [_seg(0.0, 4.0, "one long unbroken sentence here.",
                 [(0.0, 0.5, "one"), (0.6, 1.2, "long"), (1.3, 2.0, "unbroken"),
                  (2.1, 3.0, "sentence"), (3.1, 4.0, "here.")])]
    out = _stream(turns, segs)
    assert len(out) == 1                       # tidak terpecah
    assert out[0].speaker == "SPEAKER_01"      # ke speaker dominan


def test_island_suppression_ABA():
    # A-[b]-A: blok speaker pendek di antara dua blok speaker SAMA -> jadi A.
    turns = [
        SpeakerTurn(0.0, 5.0, "SPEAKER_00"),
        SpeakerTurn(5.0, 7.0, "SPEAKER_01"),   # island pendek (2s)
        SpeakerTurn(7.0, 12.0, "SPEAKER_00"),
    ]
    segs = [
        _seg(0.0, 4.5, "First long part here now.", [(0.0,4.5,"First long part here now.")]),
        _seg(5.0, 6.8, "Short bit.", [(5.0, 6.8, "Short bit.")]),
        _seg(7.2, 11.5, "Third long part again now.", [(7.2,11.5,"Third long part again now.")]),
    ]
    out = _stream(turns, segs, island_max_s=4.0)
    # Semua jadi satu speaker (island dilebur) -> satu blok.
    assert {l.speaker for l in out} == {"SPEAKER_00"}


def test_island_suppression_keeps_ABAB_alternation():
    # A-B-A-B alternasi sah (pertukaran cepat) TIDAK boleh dilebur.
    turns = [
        SpeakerTurn(0.0, 2.0, "SPEAKER_00"),
        SpeakerTurn(2.0, 4.0, "SPEAKER_01"),
        SpeakerTurn(4.0, 6.0, "SPEAKER_02"),   # C, bukan A -> pola A-B-C
    ]
    segs = [
        _seg(0.0, 1.8, "You are not from strategy?", [(0.0,1.8,"You are not from strategy?")]),
        _seg(2.1, 3.8, "No, IT.", [(2.1,3.8,"No, IT.")]),
        _seg(4.1, 5.8, "You are from IT.", [(4.1,5.8,"You are from IT.")]),
    ]
    out = _stream(turns, segs, island_max_s=4.0)
    # Tiga speaker berbeda tetap terpisah (pertukaran cepat terjaga).
    assert [l.speaker for l in out] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]


def test_no_diarization_uses_placeholder():
    # Diarization kosong sama sekali: tetap keluar teks, pakai label placeholder.
    segs = [_seg(0.0, 1.0, "solo", [(0.0, 1.0, "solo")])]
    lines = merge(segs, [])
    assert len(lines) == 1
    assert lines[0].text == "solo"


def test_sentence_cap_breaks_long_blob_at_speaker_change():
    """Regresi bug user 2026-08 kualitas rendah: Whisper tanpa punctuation +
    audio ber-overlap -> tanpa cap, satu 'kalimat' 60 dtk menjelma paragraf
    raksasa yg ditugaskan ke SATU speaker. Cap memaksa break di batas speaker
    sehingga tiap orang dapat turn-nya sendiri.

    Skenario: 3 speaker turns berturut (A/B/A) 6 dtk masing-masing, 18 kata
    tanpa titik. Cap 3 dtk -> break diharapkan di transisi speaker (word 5->6
    A->B, word 11->12 B->A). Dominant per-bagian: A, B, A -> 3 blok (tanpa lebur)."""
    turns = [
        SpeakerTurn(0.0, 6.0, "SPEAKER_00"),
        SpeakerTurn(6.0, 12.0, "SPEAKER_01"),
        SpeakerTurn(12.0, 18.0, "SPEAKER_00"),
    ]
    # 18 kata @ 1 dtk, tanpa titik. Word i berada persis dalam turn floor(i/6).
    words = [(float(i), float(i) + 0.9, f"w{i}") for i in range(18)]
    segs = [_seg(0.0, 18.0, " ".join(w[2] for w in words), words)]
    # sentence_max_s=3 -> cap aktif sesudah span 3 dtk & break di transisi speaker
    out = _stream(turns, segs, sentence_max_s=3.0)
    speakers = [l.speaker for l in out]
    # Harus DUA speaker unik (SPEAKER_00 & SPEAKER_01) — tanpa cap semua akan lebur
    # ke satu blob 18 kata di SPEAKER_00 (dominan overlap 12/18 dtk).
    assert len(set(speakers)) == 2, (
        f"Expected multi-speaker attribution after speaker-cap break, got {speakers}")
    assert len(out) >= 3, (
        f"Expected >=3 blocks (A/B/A pattern), got {len(out)} blocks: {out}")


def test_sentence_cap_no_effect_on_short_sentence():
    """Cap TIDAK boleh mengganggu kalimat pendek yang normal-punctuated —
    hanya jaring pengaman untuk kasus patologis."""
    turns = [
        SpeakerTurn(0.0, 2.0, "SPEAKER_00"),
        SpeakerTurn(2.0, 4.0, "SPEAKER_01"),
    ]
    segs = [
        _seg(0.0, 1.8, "hello there.",
             [(0.0, 0.8, "hello"), (0.9, 1.7, "there.")]),
        _seg(2.1, 3.9, "hi back.",
             [(2.1, 2.8, "hi"), (3.0, 3.9, "back.")]),
    ]
    # sentence_max_s default 15 — kalimat pendek tak terpengaruh.
    out = _stream(turns, segs)
    assert len(out) == 2
    assert out[0].text == "hello there."
    assert out[1].text == "hi back."


def test_arabic_sentence_end_recognised():
    """Brief 53 — bug nyata: `_SENT_END` dulu hanya `[.!?]` (Latin). Transkrip Arab
    asli (fixture 120 dtk) keluar dengan `،` 7x dan `؟` 1x dan NOL titik Latin, jadi
    merger tak menemukan SATU PUN batas kalimat -> tak bisa memecah giliran ->
    120 detik jadi 3 baris. Di sini tanda bacanya ADA; kita yang buta."""
    from polyscribe.merge import _SENT_END
    for mark in ("؟", "۔", ".", "!", "?"):
        assert _SENT_END.search(f"كلمة{mark}"), f"tanda akhir kalimat {mark!r} tak dikenali"
    # Koma Arab BUKAN akhir kalimat — memecah di koma akan over-split.
    assert not _SENT_END.search("كلمة،")
    assert not _SENT_END.search("كلمة؛")


def test_arabic_turn_split_on_question_mark():
    """Dua pembicara, teks Arab, batas kalimat hanya `؟` — harus terpisah."""
    turns = [SpeakerTurn(0.0, 2.0, "SPEAKER_00"), SpeakerTurn(2.0, 4.0, "SPEAKER_01")]
    segs = [
        _seg(0.0, 1.8, "هل هذا صحيح؟",
             [(0.0, 0.8, "هل"), (0.9, 1.3, "هذا"), (1.4, 1.8, "صحيح؟")]),
        _seg(2.1, 3.9, "نعم، هذا صحيح۔",
             [(2.1, 2.6, "نعم،"), (2.7, 3.2, "هذا"), (3.3, 3.9, "صحيح۔")]),
    ]
    out = _stream(turns, segs)
    assert len(out) == 2, f"giliran Arab tak terpisah: {[(l.speaker, l.text) for l in out]}"
    assert out[0].speaker != out[1].speaker


def _monologue_segments(n_sentences=12, words_per=15):
    """Satu orang bicara panjang tanpa jeda — kasus yang memicu batas keterbacaan."""
    segs, t = [], 0.0
    for i in range(n_sentences):
        words = [f"kata{i}x{j}" for j in range(words_per - 1)] + [f"akhir{i}."]
        ws = [Word(t + k * 0.4, t + k * 0.4 + 0.35, w) for k, w in enumerate(words)]
        segs.append(AsrSegment(start=t, end=ws[-1].end, text=" ".join(words),
                               language="en", words=ws))
        t = ws[-1].end + 0.1
    return segs


def test_long_monologue_split_for_readability():
    """Brief 52: giliran panjang TETAP milik satu orang (memecah per-speaker akan
    salah — diarization membuktikan itu monolog asli), tapi 266 kata dalam satu
    baris tak terbaca. Jadi dipecah di BATAS KALIMAT, speaker sama."""
    segs = _monologue_segments()
    turns = [SpeakerTurn(0.0, 10_000.0, "SPEAKER_00")]
    out = _stream(list(turns), segs, block_max_words=40)
    assert len(out) > 1, "blok panjang tak dipecah"
    assert {ln.speaker for ln in out} == {"SPEAKER_00"}, "pemecahan mengubah speaker"
    # Tiap baris berakhir di batas kalimat — tak ada kalimat yang terbelah.
    for ln in out[:-1]:
        assert ln.text.rstrip().endswith("."), f"terpotong di tengah kalimat: {ln.text[-40:]}"


def test_readability_split_preserves_text_and_speaker():
    """Gerbang keselamatan: pemecahan ini KOSMETIK. Teks gabungan & label per-KATA
    harus identik dengan hasil tanpa pemecahan."""
    segs = _monologue_segments()
    turns = [SpeakerTurn(0.0, 10_000.0, "SPEAKER_00")]
    plain = _stream([SpeakerTurn(t.start, t.end, t.speaker) for t in turns], segs,
                    block_max_words=0)
    split = _stream([SpeakerTurn(t.start, t.end, t.speaker) for t in turns], segs,
                    block_max_words=40)
    assert " ".join(l.text for l in plain) == " ".join(l.text for l in split)
    per_word = lambda lines: [l.speaker for l in lines for _ in l.text.split()]
    assert per_word(plain) == per_word(split)
    times = [l.start for l in split]
    assert times == sorted(times), "timestamp mundur sesudah dipecah"


def test_readability_split_off_by_zero():
    segs = _monologue_segments()
    turns = [SpeakerTurn(0.0, 10_000.0, "SPEAKER_00")]
    out = _stream(list(turns), segs, block_max_words=0)
    assert len(out) == 1, "block_max_words=0 harus mengembalikan perilaku lama"


def test_short_turns_untouched_by_readability_cap():
    # Percakapan normal (baris pendek) tak boleh berubah sama sekali.
    turns = [SpeakerTurn(0.0, 2.0, "SPEAKER_00"), SpeakerTurn(2.0, 4.0, "SPEAKER_01")]
    segs = [_seg(0.0, 1.8, "hello there.", [(0.0, 0.8, "hello"), (0.9, 1.8, "there.")]),
            _seg(2.1, 3.9, "hi back.", [(2.1, 2.8, "hi"), (3.0, 3.9, "back.")])]
    a = _stream([SpeakerTurn(t.start, t.end, t.speaker) for t in turns], segs,
                block_max_words=0)
    b = _stream([SpeakerTurn(t.start, t.end, t.speaker) for t in turns], segs,
                block_max_words=120)
    assert [(l.speaker, l.text) for l in a] == [(l.speaker, l.text) for l in b]


if __name__ == "__main__":
    # Runner ringan tanpa pytest — biar bisa jalan di venv minimal.
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
