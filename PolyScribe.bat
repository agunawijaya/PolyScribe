@echo off
REM ============================================================
REM  PolyScribe - peluncur
REM  Tinggal klik dua kali file ini untuk membuka aplikasi.
REM  Tidak perlu mengetik perintah atau mengingat jalur apa pun.
REM ============================================================

title PolyScribe

REM Pindah ke folder skrip ini sendiri (/d supaya pindah drive pun aman).
REM %~dp0 = drive+dir file .bat -> apa pun lokasi repo, launcher ini ikut.
cd /d "%~dp0"

REM Cek dulu Python di venv. Ini titik yang paling sering putus
REM kalau venv terhapus atau proyek belum di-setup.
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   Tidak menemukan Python di:
    echo     %CD%\.venv\Scripts\python.exe
    echo.
    echo   Setup venv dulu di folder proyek ini, lalu coba lagi.
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
