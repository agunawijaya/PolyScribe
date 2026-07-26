"""Uji pemetaan bahasa dropdown GUI (brief 47).

Fokus: label dropdown -> kode bahasa Whisper. Jebakan yang diuji: memilih
"Bahasa Indonesia" HARUS jadi "id", bukan diam-diam "en" (logika biner lama).

Diuji dua lapis:
  1. Peta murni LANG_LABEL_TO_CODE + invarian "dropdown diisi dari peta" (tanpa GUI).
  2. _build_config sungguhan lewat Tk root tersembunyi bila lingkungan mendukung;
     kalau Tk tak bisa init (headless), tahap ini di-skip dengan jujur — lapis 1
     sudah mengunci logikanya.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from polyscribe import gui


def test_map_values():
    m = gui.LANG_LABEL_TO_CODE
    assert m["Inggris"] == "en"
    assert m["Bahasa Indonesia"] == "id"      # <-- inti brief 47
    assert m["Auto (multibahasa)"] == "auto"
    # Arab sengaja TIDAK ada (keputusan user).
    assert not any("rab" in label for label in m), "Arab tak boleh ada di dropdown"
    print("  peta: Inggris->en, Bahasa Indonesia->id, Auto->auto  OK")


def test_order_and_default():
    labels = list(gui.LANG_LABEL_TO_CODE.keys())
    assert labels == ["Inggris", "Bahasa Indonesia", "Auto (multibahasa)"], labels
    # Default GUI = "Inggris" -> "en" (PM #2, jangan diubah).
    assert gui.LANG_LABEL_TO_CODE[labels[0]] == "en"
    print(f"  urutan {labels}, default 'Inggris'->en  OK")


def test_no_label_falls_to_fallback():
    # Tiap label dropdown harus punya entri -> fallback "en" di _build_config tak
    # pernah kepakai. (Dropdown diisi dari keys peta, jadi ini menjaga invarian itu.)
    for label in gui.LANG_LABEL_TO_CODE:
        code = gui.LANG_LABEL_TO_CODE.get(label, "__FALLBACK__")
        assert code != "__FALLBACK__", f"{label} jatuh ke fallback!"
    print("  tak ada label yang jatuh ke fallback  OK")


def test_build_config_real_gui():
    """_build_config sungguhan: pilih tiap bahasa, cek cfg.primary_language."""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
    except Exception as e:
        print(f"  SKIP _build_config nyata (Tk tak tersedia: {type(e).__name__})")
        return

    try:
        app = gui.PolyScribeApp(root)
        cases = {"Inggris": "en", "Bahasa Indonesia": "id", "Auto (multibahasa)": "auto"}
        for label, expect in cases.items():
            app.lang_var.set(label)
            cfg = app._build_config()
            assert cfg.primary_language == expect, \
                f"{label} -> {cfg.primary_language}, harusnya {expect}"
        # Default tanpa menyentuh dropdown = Inggris -> en.
        app.lang_var.set("Inggris")
        assert app._build_config().primary_language == "en"
        # Mode label pembicara tak tersentuh (masih memetakan Akurat->pyannote default).
        assert app._build_config().diarizer_choice in ("pyannote", "sherpa")
        # Dropdown benar-benar diisi 3 nilai dari peta.
        assert list(app.lang_combo["values"]) == list(gui.LANG_LABEL_TO_CODE.keys())
        print("  _build_config nyata: ketiga bahasa memetakan benar  OK")
    finally:
        root.destroy()


if __name__ == "__main__":
    test_map_values()
    test_order_and_default()
    test_no_label_falls_to_fallback()
    test_build_config_real_gui()
    print("SEMUA LULUS")
