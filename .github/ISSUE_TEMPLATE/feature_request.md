---
name: Feature request
about: Usulkan fitur atau perbaikan yang belum ada
title: '[FEATURE] '
labels: enhancement
assignees: ''
---

## Masalah yang mau diselesaikan
<!-- Apa yang tidak bisa / sulit dilakukan sekarang? Kenapa itu penting? -->

## Solusi yang diusulkan
<!-- Bagaimana kamu bayangkan ini bekerja dari sudut pandang user? -->

## Alternatif yang sudah dipertimbangkan
<!-- Cara lain yang bisa menyelesaikan masalah yang sama. Kenapa yang diusulkan
     lebih baik? -->

## Cocok dengan scope PolyScribe?

Sebelum submit, cek [PRODUCT_SPEC.md](../../docs/PRODUCT_SPEC.md):
- [ ] Bukan bagian dari [anti-features](../../docs/PRODUCT_SPEC.md#63-explicit-anti-features)
      (mis. jumlah speaker manual, cloud fallback, telemetri)
- [ ] Kompatibel dengan [NFR](../../docs/PRODUCT_SPEC.md#52-non-functional-requirements)
      (offline penuh, multi-hardware, tidak menambah dependency raksasa untuk fitur kecil)
- [ ] Kalau menambah backend hardware (ROCm, MPS, Intel Arc): siap
      mengimplementasi lewat interface `AsrBackend` / `Diarizer` tanpa
      menyentuh `polyscribe/pipeline.py`

## Konteks tambahan

<!-- Referensi, contoh dari tool lain, dsb. -->
