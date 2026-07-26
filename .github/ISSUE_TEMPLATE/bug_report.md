---
name: Bug report
about: Laporkan masalah dengan PolyScribe
title: '[BUG] '
labels: bug
assignees: ''
---

## Deskripsi
<!-- Apa yang terjadi. Sesingkat mungkin tapi lengkap. -->

## Yang kamu harapkan
<!-- Apa yang seharusnya terjadi kalau tidak ada bug. -->

## Cara reproduksi
<!-- Langkah-langkah persis. Kalau berkaitan dengan audio, sebutkan jenis
     (durasi, bahasa, mono/stereo) TAPI JANGAN LAMPIRKAN AUDIO RAPAT ASLI. -->

1.
2.
3.

## Perintah yang dijalankan
```powershell
# Persis apa yang kamu ketik
```

## Output error
```
# Salin lengkap, termasuk stack trace
```

## Lingkungan

- **OS:** Windows 10 / 11 (versi build?)
- **Python:** hasil `py -0p`
- **PolyScribe:** hasil `git log -1 --oneline`
- **GPU:** (kalau NVIDIA: hasil `nvidia-smi` baris pertama; kalau AMD:
  `dxdiag` → Display tab)
- **Mode:** default (pyannote) / `--diarizer sherpa` / lain?
- **Backend ASR:** `auto` / `faster-whisper` / `whispercpp`?
- **Bahasa audio:** EN / AR / ID / mixed?

## Yang sudah kamu coba

<!-- Sudah cek [TROUBLESHOOTING.md](../../TROUBLESHOOTING.md)? Sudah pull
     versi terbaru? Sudah re-download model? -->

- [ ] Sudah cek TROUBLESHOOTING.md
- [ ] Sudah pull versi terbaru dari main
- [ ] Bug reproducible (bukan intermittent)

## Konteks tambahan

<!-- Screenshot (kalau UI), log tambahan, hipotesis, dsb. -->
