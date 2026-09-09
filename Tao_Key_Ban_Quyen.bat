@echo off
chcp 65001 >nul
title TRÌNH TẠO LICENSE KEY — HYPERMEDIA DOWNLOADER PRO (@NguyenThanhDuy42124)
color 0B

echo =====================================================================
echo    TRÌNH TẠO LICENSE KEY TỰ ĐỘNG — HYPERMEDIA DOWNLOADER PRO
echo    Tác giả: NguyenThanhDuy42124 (Nguyễn Thanh Duy) - Zalo: 0334674017
echo =====================================================================
echo.

if exist "env\Scripts\python.exe" (
    set "PY_EXE=env\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PY_EXE=venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

"%PY_EXE%" generate_key.py

echo.
echo =====================================================================
echo  Nhấn phím bất kỳ để tạo thêm Key khác hoặc đóng cửa sổ...
pause >nul
