@echo off
chcp 65001 > nul
title Build

echo.
echo  Building timestamp_hotkey.exe ...
echo.

pip install pynput obsws-python pyinstaller
if errorlevel 1 (
    echo.
    echo  [ERROR] pip failed. Is Python installed?
    echo  https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
echo  Running PyInstaller...
echo.

pyinstaller --onefile --windowed --uac-admin --name timestamp_hotkey --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 --hidden-import obsws_python --hidden-import websocket timestamp_hotkey.py

if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed.
    pause
    exit /b 1
)

copy /Y "dist\timestamp_hotkey.exe" "timestamp_hotkey.exe" > nul
rmdir /S /Q build > nul 2>&1
rmdir /S /Q dist  > nul 2>&1
del /Q "timestamp_hotkey.spec" > nul 2>&1

echo.
echo  ============================================
echo   Done!  timestamp_hotkey.exe is ready.
echo  ============================================
echo.
pause
