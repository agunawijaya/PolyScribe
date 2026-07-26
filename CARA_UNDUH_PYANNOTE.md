# Langkah Mengunduh Model pyannote (sekali saja)

Tujuan: mengunduh model pelabel-pembicara yang lebih pintar, supaya PolyScribe bisa
memisahkan pertukaran cepat seperti OPPO.

Model ini "terkunci" di situs Hugging Face — **hanya pemilik akun yang boleh
membukanya**, jadi langkah ini harus kamu lakukan sendiri.

Waktu: ~10 menit (+ unduhan ~2 GB).

---

## LANGKAH 1 — Buat akun Hugging Face (lewati kalau sudah punya)

1. Buka: https://huggingface.co/join
2. Daftar (gratis, cukup email).

---

## LANGKAH 2 — Buka kunci 3 model (klik "Agree" di tiap halaman)

Buka tiga tautan ini SATU PER SATU. Di tiap halaman akan ada kotak
"You need to agree to share your contact information to access this model".
Isi seadanya lalu klik tombol **Agree / Accept**.

1. https://huggingface.co/pyannote/speaker-diarization-3.1
2. https://huggingface.co/pyannote/segmentation-3.0
3. https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM

Kalau halaman sudah menampilkan daftar file (bukan tombol Agree), berarti
model itu sudah terbuka. Lanjut.

---

## LANGKAH 3 — Buat token (semacam kunci untuk mengunduh)

1. Buka: https://huggingface.co/settings/tokens
2. Klik **New token** (atau "Create new token").
3. Name: bebas, misal `polyscribe`.
4. Type/Role: pilih **Read** (cukup ini).
5. Klik **Create**.
6. **SALIN token yang muncul** (bentuknya seperti `hf_xxxxxxxxxxxxxxxx`).
   Simpan sementara di Notepad — token hanya ditampilkan sekali.

⚠️ Token ini seperti password. **Jangan tempel ke chat.** Cukup dipakai di
terminal kamu sendiri (Langkah 4).

---

## LANGKAH 4 — Jalankan 2 perintah di PowerShell

Buka PowerShell, lalu jalankan berikut satu per satu.

### 4a. Pasang PyTorch + pyannote (~2 GB, sekali saja)
Masuk dulu ke folder repo PolyScribe (apa pun path-nya di mesinmu), lalu:
```powershell
cd <path\ke\PolyScribe>
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install -r requirements-pyannote.txt
```
Tunggu sampai selesai (bisa beberapa menit).

### 4b. Unduh model pyannote
Ganti `hf_xxxxx` dengan token dari Langkah 3 (tetap di folder repo dari 4a):
```powershell
& $py scripts\download_models.py --only pyannote --hf-token hf_xxxxx
```

---

## LANGKAH 5 — Selesai, kabari

Kalau perintah 4b berakhir tanpa error, ketik saja **"sudah"** di chat.
Programmer akan menjalankan perbandingan: apakah pyannote bisa memisahkan
"Yeah." dan "Exactly." jadi dua orang — seperti OPPO.

---

## Kalau ada error

Salin **pesan errornya** ke chat (bukan tokennya). Beberapa yang umum:

| Pesan | Artinya |
|---|---|
| `401` / `Unauthorized` | Token salah, atau lisensi (Langkah 2) belum di-Agree |
| `403` / `gated repo` | Salah satu dari 3 model belum di-Agree. Ulangi Langkah 2 |
| `No module named torch` | Langkah 4a belum berhasil. Ulangi |

---

## Yang perlu kamu tahu

- Token **hanya dipakai sekali**, saat mengunduh. Setelah model tersimpan di
  `models\`, aplikasi berjalan **tanpa internet, tanpa akun** — selamanya.
  Janji "offline penuh" tetap utuh.
- Kalau ternyata pyannote **tidak** lebih baik dari yang sekarang, kita tetap
  memakai yang lama. Tidak ada yang rusak.
