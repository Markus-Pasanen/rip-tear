@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: --- CONFIG ---
set "MAKEMKV=C:\Program Files (x86)\MakeMKV\makemkvcon64.exe"
set "RAW=%~dp0..\..\raw"
:: -------------

rmdir /s /q "%RAW%" 2>nul & mkdir "%RAW%"

cls
echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║   ██████╗ ██╗██████╗     ████████╗███████╗ █████╗ ██████╗  ║
echo  ║   ██╔══██╗██║██╔══██╗    ╚══██╔══╝██╔════╝██╔══██╗██╔══██╗ ║
echo  ║   ██████╔╝██║██████╔╝       ██║   █████╗  ███████║██████╔╝ ║
echo  ║   ██╔══██╗██║██╔═══╝        ██║   ██╔══╝  ██╔══██║██╔══██╗ ║
echo  ║   ██║  ██║██║██║            ██║   ███████╗██║  ██║██║  ██║ ║
echo  ║   ╚═╝  ╚═╝╚═╝╚═╝            ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝ ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

set /p "NAME=Movie name copied from TMDB (e.g. The Matrix (1999)): "

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║  RIPPING THE DISC FROM THE DEMON'S GRASP                 ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

"%MAKEMKV%" --cache=1024 --minlength=600 mkv disc:0 all "%RAW%"
if errorlevel 1 (
    echo  ╔══════════════════════════════════════════════════════════╗
    echo  ║  THE DISC RESISTED! RIP FAILED.                          ║
    echo  ╚══════════════════════════════════════════════════════════╝
    pause & exit /b 1
)

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║  ✅  RIP COMPLETE — READY FOR TEARING                    ║
echo  ║                                                          ║
echo  ║  %NAME%                                                  ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.
pause