# Security Policy

PolyScribe adalah aplikasi desktop offline. Dokumen ini menjelaskan apa yang
kami anggap kerentanan keamanan, cara melaporkannya, dan apa yang berada di
luar model ancaman kami.

---

## Model ancaman

**Yang PolyScribe janjikan (dan wajib kami jaga):**
- **Tidak ada panggilan jaringan di jalur runtime.** Audio & transkrip tidak
  pernah dikirim ke server manapun.
- **Tidak ada token / kredensial** yang di-embed di aplikasi jalur utama.
  Token HF hanya dipakai sekali saat setup opsional pyannote.
- **`.txt` output** ditulis hanya ke folder yang sama dengan file audio input —
  tidak ke lokasi lain.
- **`.gitignore`** menutup rekaman & transkrip rapat asli supaya tidak
  ter-commit tanpa sengaja.

**Yang berada di luar model ancaman kami:**
- Kualitas / bias / halusinasi model AI itu sendiri (Whisper, pyannote). Itu
  masalah upstream.
- Keamanan sistem operasi Windows tempat aplikasi berjalan (mis. malware yang
  membaca `.txt` dari disk).
- Keamanan file audio sumber (kalau audio bocor lewat channel lain di luar
  PolyScribe, itu di luar kendali kami).
- Kebocoran karena user secara eksplisit mengunggah `.txt` output ke cloud /
  membagikan ke pihak lain.
- Kerentanan di paket pihak ketiga (`torch`, `pyannote.audio`, dsb) — laporkan
  ke upstream. Kami akan meng-update ketergantungan bila ada perbaikan.

---

## Yang dianggap kerentanan keamanan

Contoh kondisi yang **wajib dilaporkan segera**:

- **Aplikasi mengirim audio / transkrip ke jaringan** — ini melanggar janji
  utama produk. Kritis.
- **Token HF tersimpan ke disk / log dalam bentuk plaintext** setelah setup
  selesai.
- **`.txt` output tertulis ke lokasi selain sebelah file audio input** tanpa
  disengaja user.
- **Dependency dengan kerentanan yang bisa dieksploitasi** dari file audio
  yang di-craft khusus (mis. buffer overflow di decoder audio yang dipakai).
- **Injection attack** di path input yang menyebabkan eksekusi kode tak
  terduga.
- **Kegagalan sanitasi** yang menyebabkan output menulis di luar folder yang
  seharusnya.

Kalau ragu apakah suatu masalah termasuk kerentanan atau bug biasa: laporkan
sebagai kerentanan dan biarkan kami putuskan.

---

## Cara melaporkan

**JANGAN** buka public GitHub issue untuk laporan kerentanan.

**Gunakan salah satu channel privat:**

1. **GitHub Security Advisory** (direkomendasikan):
   <https://github.com/agunawijaya/PolyScribe/security/advisories/new>
   — end-to-end di GitHub, dengan tracking dan koordinasi disclosure.

2. **Email** ke maintainer (lihat commit history untuk kontak yang aktif).
   Subject prefix: `[SECURITY]`. Kalau perlu enkripsi, sebutkan di email pertama
   dan kami akan pertukarkan PGP key.

**Yang tolong disertakan:**
- Deskripsi kerentanan yang jelas
- Langkah reproduksi (kalau bisa)
- Dampak (apa yang bocor, apa yang bisa dieksploitasi)
- Versi PolyScribe (`git log -1`) + versi Python + OS
- Kalau kamu punya usulan perbaikan, sertakan (opsional)

---

## Proses & timeline

- **Acknowledge:** dalam 5 hari kerja.
- **Assessment:** dalam 2 minggu — kami tentukan severity dan buat rencana fix.
- **Fix + release:** tergantung severity. Kritis (mis. kebocoran jaringan):
  patch secepatnya. Non-kritis: masuk ke rilis reguler.
- **Public disclosure:** setelah fix tersedia, kami umumkan (dengan credit
  reporter kalau kamu setuju).

Kami tidak memberi **bug bounty** — proyek ini adalah tool pribadi yang
di-open-source, bukan produk komersial dengan anggaran.

---

## Best practices untuk pengguna

Untuk memaksimalkan privacy PolyScribe di lingkungan kamu:

1. **Jangan install ekstensi / paket asing** ke venv PolyScribe. Ekstensi
   pihak ketiga bisa "memperluas" scope aplikasi.
2. **Cek `.gitignore`** sebelum commit. `git status` tidak boleh menunjukkan
   `.mp3`/`.wav`/`.m4a`/`.txt` rapat asli.
3. **Simpan HF token dengan aman.** Setelah download model pyannote selesai,
   token tidak dibutuhkan lagi — bisa di-revoke di HF settings.
4. **Enkripsi disk laptop** (BitLocker) — kami tidak mengenkripsi file output
   secara terpisah.
5. **Verifikasi outbound traffic** (kalau paranoid): jalankan aplikasi di
   lingkungan tanpa internet, atau monitor dengan Wireshark. Aplikasi seharusnya
   tidak ada traffic saat runtime.

---

## Riwayat

Tidak ada CVE terbuka untuk PolyScribe saat ini. Riwayat akan didaftar di
sini setelah rilis pertama yang tag-nya bernomor versi.
