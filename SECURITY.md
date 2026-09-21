# Security Policy

PolyScribe adalah aplikasi desktop **offline-first** dengan jalur cloud yg
**opt-in eksplisit**. Dokumen ini menjelaskan apa yang kami anggap kerentanan
keamanan, cara melaporkannya, dan apa yang berada di luar model ancaman kami.

Perbedaan penting antara dua mode operasi tercakup di setiap section.

---

## Model ancaman

### Jalur DEFAULT (offline)

**Yang PolyScribe janjikan untuk jalur default (dan wajib kami jaga):**
- **Tidak ada panggilan jaringan di jalur runtime default.** Audio & transkrip
  tidak dikirim ke server manapun. Jalur ini dipilih otomatis; user tak perlu
  melakukan apa pun untuk mendapatkannya.
- **Tidak ada token / kredensial** yang di-embed di aplikasi jalur default.
  Token HF hanya dipakai sekali saat setup opsional pyannote.
- **`.txt` output** ditulis hanya ke folder yang sama dengan file audio input —
  tidak ke lokasi lain.
- **`.gitignore`** menutup rekaman & transkrip rapat asli supaya tidak
  ter-commit tanpa sengaja.

### Jalur CLOUD (opt-in)

Ditambahkan 2026-09-21. User dapat secara EKSPLISIT memilih backend cloud
(7 provider: Google Web/Groq/OpenAI/Deepgram/AssemblyAI/Azure/Google Cloud)
untuk sebuah run. Jalur ini **tidak pernah dipilih otomatis**.

**Yang PolyScribe janjikan untuk jalur cloud:**
- **API key user disimpan HANYA di Windows Credential Manager** via library
  `keyring`. Tidak pernah tulis plaintext ke `%APPDATA%`, tidak pernah ke
  variable environment yg di-commit, tidak pernah ke log.
- **Key write-once di GUI:** setelah user simpan, kami TIDAK PERNAH menampilkannya
  kembali. Hanya masked `●●●●●●xxxx` untuk konfirmasi visual + tombol Ganti/Hapus.
- **Audio user hanya dikirim ke provider yang dipilih user itu** — tidak ke pihak
  ketiga lain. Kami tidak menyelipkan telemetri/analitik ke request.
- **Diarization tetap lokal** (pyannote/sherpa) untuk semua jalur cloud —
  cloud hanya menggantikan lapisan ASR (transkripsi teks). Speaker labels
  dihasilkan di laptop user.
- **Validasi ukuran & durasi** dijalankan sebelum pipeline mulai supaya audio
  tak sengaja dikirim ke provider dgn setup salah (mis. Google Cloud batas 60
  dtk).

**Yang PolyScribe TIDAK bisa janjikan untuk jalur cloud:**
- **Kebijakan retention/logging provider** — setelah audio sampai ke server
  Groq/Deepgram/dll, itu tunduk pada ToS masing-masing. Cek kebijakan mereka
  sebelum kirim rekaman sensitif.
- **Man-in-the-middle attack** di jalur HTTP — kami pakai HTTPS, TLS ditangani
  library `requests`, tapi kalau sertifikat root di laptop user dikompromikan,
  di luar kendali kami.
- **Endpoint tak resmi** — khususnya Google Web Speech memakai demo endpoint
  Google yang tak beri jaminan apa pun. Sengaja disediakan sbg pembanding,
  bukan produksi (didokumentasikan di GUI + CLAUDE.md).

### Di luar model ancaman kami

- Kualitas / bias / halusinasi model AI itu sendiri (Whisper, pyannote). Itu
  masalah upstream.
- Keamanan sistem operasi Windows tempat aplikasi berjalan (mis. malware yang
  membaca `.txt` dari disk, atau mengekstrak kredensial dari Credential Manager).
- Keamanan file audio sumber (kalau audio bocor lewat channel lain di luar
  PolyScribe, itu di luar kendali kami).
- Kebocoran karena user secara eksplisit mengunggah `.txt` output ke cloud /
  membagikan ke pihak lain.
- **Keputusan user memilih backend cloud untuk audio sensitif.** Kami memberi
  hint & warning di GUI (harga, kapabilitas, batas ukuran), tapi pilihan final
  ada di user.
- Kerentanan di paket pihak ketiga (`torch`, `pyannote.audio`, `keyring`,
  `requests`, dsb) — laporkan ke upstream. Kami akan meng-update ketergantungan
  bila ada perbaikan.

---

## Yang dianggap kerentanan keamanan

Contoh kondisi yang **wajib dilaporkan segera**:

- **Aplikasi mengirim audio / transkrip ke jaringan pada jalur DEFAULT (offline).**
  Ini melanggar janji utama produk. Kritis. (Untuk jalur cloud yg user pilih
  eksplisit, mengirim ke provider terpilih memang ekspektasi — bukan kerentanan.)
- **Audio / transkrip terkirim ke pihak ketiga selain provider yg user pilih.**
  Mis. saat user pilih Groq tapi request ternyata juga ke server lain.
- **API key user bocor:** tertulis ke disk plaintext, log, atau tampil di GUI
  setelah write-once seharusnya sudah masked selamanya.
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

1. **Untuk rapat sensitif, pakai jalur DEFAULT (offline).** Jangan aktifkan
   backend cloud untuk audio yg tak boleh keluar laptop. Jalur cloud butuh
   klik eksplisit di GUI — tak akan menyala sendiri.
2. **Jangan install ekstensi / paket asing** ke venv PolyScribe. Ekstensi
   pihak ketiga bisa "memperluas" scope aplikasi.
3. **Cek `.gitignore`** sebelum commit. `git status` tidak boleh menunjukkan
   `.mp3`/`.wav`/`.m4a`/`.txt` rapat asli.
4. **Simpan HF token dengan aman.** Setelah download model pyannote selesai,
   token tidak dibutuhkan lagi — bisa di-revoke di HF settings.
5. **Kalau pakai cloud, pilih provider yg policy retention-nya kamu setujui.**
   Groq, Deepgram, OpenAI, dll punya kebijakan retention/training data yg
   BERBEDA-BEDA — cek ToS mereka. Kami sengaja tak mengklaim tahu (bisa berubah).
6. **API key cloud**: jangan share screenshot GUI dgn tombol Set-Key terbuka
   (walau field masked, hindari kebiasaan). Simpan copy key di password manager
   kamu sendiri kalau butuh backup — kami tak bisa recover key yg hilang.
7. **Enkripsi disk laptop** (BitLocker) — kami tidak mengenkripsi file output
   secara terpisah. Windows Credential Manager (tempat API key disimpan) ikut
   terlindungi BitLocker.
8. **Verifikasi outbound traffic** (kalau paranoid, mode default): jalankan di
   lingkungan tanpa internet atau monitor dgn Wireshark. Jalur default seharusnya
   tak ada traffic saat runtime. Jalur cloud MEMANG ada traffic ke provider
   terpilih — itu ekspektasi.

---

## Riwayat

Tidak ada CVE terbuka untuk PolyScribe saat ini. Riwayat akan didaftar di
sini setelah rilis pertama yang tag-nya bernomor versi.
