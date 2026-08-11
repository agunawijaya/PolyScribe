"""Ukur kualitas satu (atau beberapa) transkrip .txt PolyScribe.

Kenapa alat ini ada di `scripts/` dan bukan `prompts/scripts/`: `prompts/` masuk
.gitignore, jadi isinya tak ikut push/pull. Angka lintas-mesin (AMD vs NVIDIA vs
CPU-only) hanya bisa dibandingkan kalau kedua sisi memakai ALAT UKUR YANG SAMA —
maka alat itu harus ikut repo.

Yang diukur, dan alasannya (semua lahir dari bug nyata, bukan hiasan):

  gerbang tanda baca  jumlah [.?!,;:] per 100 kata. Ambang **>=15** (brief 39).
                      Merge memotong giliran berdasarkan tanda baca, jadi begitu
                      ASR berhenti memberi titik, semua ucapan melebur jadi satu
                      blok berisi banyak pembicara. Di bawah 15 = transkrip tak
                      layak dipakai memvonis kualitas diarization.

  profil per 5 menit  angka yang sama, dipecah per wilayah. WAJIB dilihat:
                      keruntuhan itu LOKAL. Rekaman 22 pernah rata-rata 13,1
                      padahal menit 5-35 sehat (16-20) dan menit 35-45 nol.
                      Rata-rata menyembunyikannya.

  blok >=60 detik     satu baris speaker yang membentang >=1 menit. Ini gejala
                      langsung dari tanda baca yang hilang, dan isinya hampir
                      selalu bercampur beberapa pembicara. Yang penting bukan
                      cuma jumlahnya tapi % KATA yang terperangkap di dalamnya.

  penanda loop        berapa kali loopguard menandai halusinasi berulang.

  ganti pembicara     kasar tapi berguna: granularitas giliran per 10 menit.

Pemakaian:
    python scripts/quality_report.py hasil.txt
    python scripts/quality_report.py amd.txt nvidia.txt      # berdampingan
"""

import re
import statistics
import sys
from pathlib import Path

# "[hh:mm:ss] SPEAKER_00:<LRM> teks" — LRM opsional (penulis menyisipkannya untuk
# teks Arab; jangan sampai regex gagal hanya karena karakter tak terlihat itu).
LINE = re.compile(r"\[(\d+):(\d+):(\d+)\]\s+(SPEAKER_\d+|SPEAKER_\?\?):‎?\s*(.*)")
NOTE = re.compile(r"\[(\d+):(\d+):(\d+)\]\s+===")

# Definisi gerbang brief 39, DIPERLUAS ke tanda baca Arab (brief 53). Versi Latin
# saja melaporkan 0,0 untuk transkrip Arab yang sebenarnya punya 8 tanda baca —
# kesalahan yang persis sama sudah pernah diakui Tester di brief 39. Alat ukur yang
# buta terhadap salah satu bahasa produk = alat ukur yang berbohong.
#   ، U+060C koma   ؛ U+061B titik koma   ؟ U+061F tanya   ۔ U+06D4 titik
PUNCT_GATE = re.compile(r"[.?!,;:،؛؟۔]")
BLOCK_SECONDS = 60                       # ambang "blok raksasa"
BIN_MINUTES = 5


def parse(path):
    """-> (rows, notes). rows = dict per baris transkrip; notes = waktu penanda."""
    text = Path(path).read_text(encoding="utf-8-sig")
    rows, notes = [], []
    for ln in text.splitlines():
        m = LINE.match(ln)
        if m:
            t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            body = m.group(5)
            rows.append({"t": t, "spk": m.group(4), "txt": body,
                         "w": len(body.split()),
                         "p": len(PUNCT_GATE.findall(body))})
            continue
        n = NOTE.match(ln)
        if n:
            notes.append(int(n.group(1)) * 3600 + int(n.group(2)) * 60 + int(n.group(3)))
    # Durasi baris = jarak ke baris berikutnya. Baris terakhir tak punya penerus;
    # pakai 30 dtk sebagai tebakan konservatif (jangan bikin ia lolos ambang blok).
    for i, r in enumerate(rows):
        r["dur"] = (rows[i + 1]["t"] - r["t"]) if i + 1 < len(rows) else 30
    return rows, notes


def summarize(path):
    rows, notes = parse(path)
    if not rows:
        return None
    words = sum(r["w"] for r in rows)
    punct = sum(r["p"] for r in rows)
    big = [r for r in rows if r["dur"] >= BLOCK_SECONDS]
    big_words = sum(r["w"] for r in big)
    changes = sum(1 for i in range(1, len(rows)) if rows[i]["spk"] != rows[i - 1]["spk"])
    span = rows[-1]["t"] + rows[-1]["dur"]
    return {
        "path": Path(path).name,
        "baris": len(rows),
        "kata": words,
        "speaker": len({r["spk"] for r in rows}),
        "gate": 100.0 * punct / max(words, 1),
        "blok60": len(big),
        "pct_blok60": 100.0 * big_words / max(words, 1),
        "loop": len(notes),
        "ganti_per_10m": 600.0 * changes / max(span, 1),
        "durasi_menit": span / 60.0,
        "dur_median": statistics.median([r["dur"] for r in rows]),
        "dur_max": max(r["dur"] for r in rows),
        "profil": profile(rows, span),
        "big": big,
    }


def profile(rows, span):
    """Tanda baca per 100 kata, per BIN_MINUTES menit."""
    out = []
    for b in range(0, int(span // 60) + 1, BIN_MINUTES):
        seg = [r for r in rows if b * 60 <= r["t"] < (b + BIN_MINUTES) * 60]
        w = sum(r["w"] for r in seg)
        p = sum(r["p"] for r in seg)
        out.append((b, 100.0 * p / w if w else None))
    return out


def main():
    paths = sys.argv[1:]
    if not paths:
        print(__doc__)
        return 2
    reports = [r for r in (summarize(p) for p in paths) if r]
    if not reports:
        print("Tak ada baris transkrip yang bisa dibaca.")
        return 1

    print("=" * 92)
    print(f"{'berkas':28} {'gerbang':>8} {'baris':>6} {'spk':>4} {'blok>=60s':>10} "
          f"{'%kata':>7} {'loop':>5} {'ganti/10m':>10} {'menit':>7}")
    print("=" * 92)
    for r in reports:
        flag = "" if r["gate"] >= 15 else "  <-- di bawah ambang 15"
        print(f"{r['path'][:28]:28} {r['gate']:>8.1f} {r['baris']:>6} {r['speaker']:>4} "
              f"{r['blok60']:>10} {r['pct_blok60']:>6.0f}% {r['loop']:>5} "
              f"{r['ganti_per_10m']:>10.1f} {r['durasi_menit']:>7.1f}{flag}")

    print("\ntanda baca per 100 kata, per 5 menit (rata-rata MENYEMBUNYIKAN "
          "keruntuhan lokal):")
    bins = max(len(r["profil"]) for r in reports)
    header = " ".join(f"{b*BIN_MINUTES:>5}" for b in range(bins))
    print(f"{'berkas':28} {header}")
    for r in reports:
        cells = []
        for _, v in r["profil"]:
            cells.append("    -" if v is None else f"{v:5.1f}")
        cells += ["     "] * (bins - len(cells))
        bad = [f"{b}-{b+BIN_MINUTES}" for b, v in r["profil"]
               if v is not None and v < 10]
        print(f"{r['path'][:28]:28} " + " ".join(cells) +
              ("   runtuh: " + ",".join(bad) if bad else ""))

    for r in reports:
        if not r["big"]:
            continue
        print(f"\nblok >=60 detik di {r['path']} "
              f"({r['pct_blok60']:.0f}% dari seluruh kata terperangkap di sini):")
        for b in r["big"]:
            hms = f"{b['t']//3600:02d}:{b['t']%3600//60:02d}:{b['t']%60:02d}"
            print(f"  [{hms}] {b['dur']:>4}s {b['w']:>4} kata  "
                  f"tanda baca {100*b['p']/max(b['w'],1):5.1f}/100  {b['spk']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
