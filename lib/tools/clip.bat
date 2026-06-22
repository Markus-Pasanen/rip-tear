@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

if "%~1"=="" (
    echo Drag a raw MKV onto this script to get a 1-minute test clip.
    pause
    exit /b 1
)

set "INPUT=%~1"
set "NAME=%~n1"
set "OUTDIR=%~dp0test_clips"
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

:: Random start between 500 and 3000 seconds
set /a "START=%RANDOM% %% 2501 + 500"
set "OUTPUT=%OUTDIR%\test.mkv"

echo  ┌──────────────────────────────────────────────────────────┐
echo  │  EXTRACTING 1-MINUTE TEST CLIP                           │
echo  └──────────────────────────────────────────────────────────┘
echo.
echo  Input:  %NAME%
echo  Start:  %START%s
echo  Output: %OUTPUT%
echo.

ffmpeg -ss %START% -i "%INPUT%" -t 60 -c copy -y "%OUTPUT%"
if errorlevel 1 (
    echo ERROR: Clip extraction failed.
    pause
    exit /b 1
)

echo  ✅ Clip saved! %OUTPUT%
pause