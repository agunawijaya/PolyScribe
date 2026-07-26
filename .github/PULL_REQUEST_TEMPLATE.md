## Ringkasan

<!-- 1-3 kalimat: apa yang berubah dan kenapa. -->

## Related issue

<!-- Fixes #NN / Closes #NN / Related to #NN — kalau ada. -->

## Jenis perubahan

- [ ] Bug fix (perubahan yang memperbaiki masalah tanpa mengubah API)
- [ ] Fitur baru (fungsi yang menambah kapabilitas)
- [ ] Perubahan yang break kompatibilitas (perlu diskusi PM)
- [ ] Dokumentasi / komentar / cleanup
- [ ] Backend baru (ASR / Diarizer)

## Testing yang dilakukan

<!-- Tunjukkan bukti. "Tested locally" tanpa detail = tidak cukup. -->

- [ ] `Get-ChildItem tests\test_*.py | ForEach-Object { & $py $_.FullName }` — semua lulus
  - Jumlah lulus: _/_
- [ ] Verifikasi manual dengan file audio (kalau menyentuh pipeline pemrosesan)
  - Durasi audio: _ menit
  - Mode: `pyannote` / `sherpa` / both
  - Hasil: <cuplikan yang menunjukkan tidak ada regresi>
- [ ] Cross-platform:
  - [ ] Windows AMD (Radeon iGPU) — atau **N/A** (jelaskan)
  - [ ] Windows NVIDIA (CUDA) — atau **N/A** (jelaskan)

## Checklist

- [ ] Kode mengikuti gaya "humanized" (komentar Bahasa Indonesia natural,
      nama variabel jelas, tidak over-engineering)
- [ ] Tidak menambah panggilan jaringan di jalur runtime (NFR-1)
- [ ] Tidak hardcode path absolut ke mesin lokal
- [ ] Tidak menambah dependency baru tanpa alasan kuat
- [ ] Documentation di-update kalau perlu (README, ARCHITECTURE, TROUBLESHOOTING)
- [ ] Tidak ada file audio / transkrip rapat asli yang ikut ter-commit
      (cek `git status`!)

## Screenshot / bukti

<!-- Untuk perubahan UI atau performance. -->

## Konteks tambahan

<!-- Design decisions, trade-offs, hal yang belum sempat dikerjakan, dsb. -->
