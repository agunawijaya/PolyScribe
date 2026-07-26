"""Pembersih pasca-diarization — jaring pengaman melawan over-split.

Independen dari diarizer (jalan untuk sherpa maupun pyannote). Idenya sederhana:
di file panjang, diarizer memuntahkan banyak "speaker" palsu dari potongan pendek
yang embedding-nya tak reliabel. Dua langkah menekannya:

  1. Lebur speaker "minor" — yang total bicaranya sangat kecil — ke tetangga
     mayor terdekat. Ini yang paling langsung memangkas jumlah label.
  2. Serap turn ultra-pendek yang tersisa ke speaker tetangga dominan.

Plus perapian: gabungkan turn berdampingan ber-speaker sama (menjembatani jeda
pendek). Semua ambang dari config, jadi bisa dituning tanpa mengubah kode.
"""

from .base import SpeakerTurn


def _coalesce(turns, bridge_gap):
    """Gabung turn berurutan ber-speaker sama; jembatani jeda <= bridge_gap."""
    out = []
    for t in sorted(turns, key=lambda x: x.start):
        if out and out[-1].speaker == t.speaker and (t.start - out[-1].end) <= bridge_gap:
            out[-1].end = max(out[-1].end, t.end)
        else:
            out.append(SpeakerTurn(t.start, t.end, t.speaker))
    return out


def _totals(turns):
    tot = {}
    for t in turns:
        tot[t.speaker] = tot.get(t.speaker, 0.0) + (t.end - t.start)
    return tot


def _nearest_speaker(turns, i, allowed):
    """Speaker dari turn terdekat (kiri/kanan) yang ada di himpunan `allowed`."""
    left = right = None
    for j in range(i - 1, -1, -1):
        if turns[j].speaker in allowed:
            left = (turns[i].start - turns[j].end, turns[j].speaker)
            break
    for j in range(i + 1, len(turns)):
        if turns[j].speaker in allowed:
            right = (turns[j].start - turns[i].end, turns[j].speaker)
            break
    cands = [c for c in (left, right) if c is not None]
    if not cands:
        return None
    # jarak waktu terkecil menang
    return min(cands, key=lambda c: c[0])[1]


def cleanup_turns(turns, min_turn=1.0, min_speaker_frac=0.015,
                  min_speaker_floor=3.0, bridge_gap=0.5):
    """Kembalikan daftar turn yang sudah dibersihkan (over-split ditekan).

    Ambang speaker-minor dibuat RELATIF terhadap total bicara
    (`min_speaker_frac`), bukan detik absolut — supaya adil untuk file panjang
    maupun klip pendek. Contoh: 1.5% dari total. `min_speaker_floor` = lantai
    detik minimal agar file sangat pendek tak kepruning berlebihan.
    """
    if not turns:
        return []

    turns = _coalesce(turns, bridge_gap)

    # --- Langkah 1: lebur speaker minor ke tetangga mayor ---
    totals = _totals(turns)
    total_speech = sum(totals.values())
    min_total = max(min_speaker_floor, min_speaker_frac * total_speech)
    major = {sp for sp, tot in totals.items() if tot >= min_total}
    if not major:
        # Semua kecil (mis. file sangat pendek): pertahankan speaker terbesar.
        major = {max(totals, key=totals.get)}

    for i, t in enumerate(turns):
        if t.speaker not in major:
            repl = _nearest_speaker(turns, i, major)
            if repl is not None:
                t.speaker = repl
    turns = _coalesce(turns, bridge_gap)

    # --- Langkah 2: serap turn ultra-pendek yang tersisa ke tetangga dominan ---
    # Ulangi sampai stabil supaya rantai turn pendek ikut terserap.
    changed = True
    while changed and len(turns) > 1:
        changed = False
        totals = _totals(turns)
        for i, t in enumerate(turns):
            if (t.end - t.start) < min_turn:
                # tetangga dengan total bicara terbesar = "dominan"
                neighbors = []
                if i > 0:
                    neighbors.append(turns[i - 1].speaker)
                if i < len(turns) - 1:
                    neighbors.append(turns[i + 1].speaker)
                if not neighbors:
                    continue
                dom = max(neighbors, key=lambda sp: totals.get(sp, 0.0))
                if dom != t.speaker:
                    t.speaker = dom
                    changed = True
        turns = _coalesce(turns, bridge_gap)

    return turns
