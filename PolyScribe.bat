@echo off
REM ============================================================
REM  PolyScribe - peluncur
REM  Tinggal klik dua kali file ini untuk membuka aplikasi.
REM  Tidak perlu mengetik perintah atau mengingat jalur apa pun.
REM ============================================================

title PolyScribe

REM Pindah ke folder proyek (/d supaya pindah drive pun aman),
REM jadi file ini tetap jalan walau diklik dari Desktop atau mana saja.
cd /d "C:\Project\PolyScribe"

REM Cek dulu Python di venv. Ini titik yang paling sering putus
REM kalau folder proyek dipindah atau venv terhapus.
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Tidak menemukan Python di:
    echo     %CD%\.venv\Scripts\python.exe
    echo.
    echo   Pastikan folder proyek masih di C:\Project\PolyScribe
    echo   dan folder .venv belum terhapus.
    echo.
    pause
    exit /b 1
)

echo.
echo   Membuka PolyScribe...
echo   (jendela hitam ini boleh dibiarkan; akan tertutup sendiri saat aplikasi ditutup)
echo.

".venv\Scripts\python.exe" -m polyscribe.gui

REM Kalau aplikasi berhenti karena error saat start (bukan ditutup normal),
REM tahan jendela supaya pesannya sempat kamu baca.
if errorlevel 1 (
    echo.
    echo   PolyScribe berhenti dengan error. Baca pesan di atas.
    pause
)

REM ------------------------------------------------------------
REM  Mau tanpa jendela hitam sama sekali? Ganti baris peluncur di
REM  atas dengan yang ini (hapus REM di depannya):
REM     start "" ".venv\Scripts\pythonw.exe" -m polyscribe.gui
REM  Konsekuensinya: kalau gagal saat start, errornya tak terlihat.
REM ------------------------------------------------------------
