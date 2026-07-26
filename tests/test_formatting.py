"""Uji penulisan .txt: encoding utf-8-sig, format baris, dan teks Arab utuh.

Fokusnya: Arab TIDAK boleh dibalik/rusak, BOM ada supaya Notepad kenal UTF-8,
dan prefiks [hh:mm:ss] LABEL: tetap benar.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polyscribe.merge import MergedLine
from polyscribe.formatting import (
    format_timestamp, format_line, render, write_txt, output_path_for,
    IncrementalTxtWriter,
)


ARABIC = "نعم، أوافق على ذلك."


def test_timestamp_format():
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(7) == "00:00:07"
    assert format_timestamp(3661) == "01:01:01"


def test_line_format_has_prefix():
    line = MergedLine(3.0, 5.0, "SPEAKER_00", "Oke, kita mulai.")
    out = format_line(line)
    assert out.startswith("[00:00:03] SPEAKER_00:")
    assert "Oke, kita mulai." in out


def test_arabic_not_reversed():
    line = MergedLine(12.0, 14.0, "SPEAKER_02", ARABIC)
    out = format_line(line)
    # Teks Arab harus muncul APA ADANYA, tidak dibalik.
    assert ARABIC in out


def test_write_utf8_sig_and_bom():
    lines = [
        MergedLine(3.0, 7.0, "SPEAKER_00", "So the main topic today is the budget."),
        MergedLine(12.0, 14.0, "SPEAKER_02", ARABIC),
    ]
    with tempfile.TemporaryDirectory() as d:
        audio_path = os.path.join(d, "rapat.mp3")
        txt_path = write_txt(lines, audio_path)

        # Ditulis di sebelah audio, ekstensi .txt.
        assert txt_path == str(output_path_for(audio_path))
        assert os.path.exists(txt_path)

        raw = open(txt_path, "rb").read()
        # BOM UTF-8 di awal.
        assert raw[:3] == b"\xef\xbb\xbf"

        # Baca balik sebagai utf-8-sig -> Arab utuh, tidak mojibake.
        text = open(txt_path, encoding="utf-8-sig").read()
        assert ARABIC in text
        assert "[00:00:03] SPEAKER_00:" in text


def test_render_ends_with_newline():
    lines = [MergedLine(0.0, 1.0, "SPEAKER_00", "hi")]
    assert render(lines).endswith("\n")
    assert render([]) == ""


def test_incremental_writes_to_part_then_commits():
    # Selama menulis, isi ada di .part; setelah close() jadi .txt (rename atomik).
    with tempfile.TemporaryDirectory() as d:
        audio = os.path.join(d, "rapat.wav")
        w = IncrementalTxtWriter(audio)
        w.write_line(MergedLine(0.0, 1.0, "SPEAKER_00", "baris satu"))
        assert os.path.exists(str(w.part_path))          # parsial di .part
        assert not os.path.exists(str(w.path))           # .txt belum ada
        w.close()
        assert os.path.exists(str(w.path))               # commit -> .txt
        assert not os.path.exists(str(w.part_path))      # .part sudah di-rename
        assert "baris satu" in open(w.path, encoding="utf-8-sig").read()


def test_incremental_no_lines_leaves_old_txt_intact():
    # BUG #1: run mati sebelum baris pertama tak boleh mengosongkan .txt lama.
    with tempfile.TemporaryDirectory() as d:
        audio = os.path.join(d, "rapat.wav")
        txt = str(output_path_for(audio))
        open(txt, "w", encoding="utf-8-sig").write("HASIL LAMA YANG BAGUS\n")
        w = IncrementalTxtWriter(audio)
        w.close()   # tak pernah write_line
        # .txt lama utuh, tak tersentuh.
        assert open(txt, encoding="utf-8-sig").read() == "HASIL LAMA YANG BAGUS\n"


def test_incremental_discard_preserves_old_txt():
    # Error di tengah: discard() tak menimpa .txt lama; parsial tetap di .part.
    with tempfile.TemporaryDirectory() as d:
        audio = os.path.join(d, "rapat.wav")
        txt = str(output_path_for(audio))
        open(txt, "w", encoding="utf-8-sig").write("HASIL LAMA\n")
        w = IncrementalTxtWriter(audio)
        w.write_line(MergedLine(0.0, 1.0, "SPEAKER_00", "parsial"))
        w.discard()
        assert open(txt, encoding="utf-8-sig").read() == "HASIL LAMA\n"   # utuh
        assert "parsial" in open(w.part_path, encoding="utf-8-sig").read()  # bisa diselamatkan


def test_incremental_context_manager_discards_on_error():
    # __exit__ dengan exception -> discard (jangan commit hasil setengah).
    with tempfile.TemporaryDirectory() as d:
        audio = os.path.join(d, "rapat.wav")
        txt = str(output_path_for(audio))
        open(txt, "w", encoding="utf-8-sig").write("LAMA\n")
        try:
            with IncrementalTxtWriter(audio) as w:
                w.write_line(MergedLine(0.0, 1.0, "SPEAKER_00", "x"))
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert open(txt, encoding="utf-8-sig").read() == "LAMA\n"   # tak tertimpa


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
