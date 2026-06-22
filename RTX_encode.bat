@echo off
setlocal enabledelayedexpansion

:: --- CONFIG ---
set "MAKEMKV=C:\Program Files (x86)\MakeMKV\makemkvcon64.exe"
set "RAW=%~dp0raw"
set "ENCODED=%~dp0encoded"
:: -------------

:: --- DRAG & DROP MODE ------------------------------------------------

if not "%~1"=="" (
    set "INPUT_MKV=%~1"
    set "DROPMODE=1"
    set "SKIP_CLEANUP=1"
    set "DEFAULT_NAME=%~n1"
    cls
    echo.
    echo  +==================================================================+
    echo  ^|                          R I P ^& T E A R                          ^|
    echo  ^|                     RTX ENCODE PIPELINE                           ^|
    echo  ^|              DRAG ^& DROP MODE  --  SKIP RIP                       ^|
    echo  +==================================================================+
    echo.
    echo  File:  %INPUT_MKV%
    echo.
    set /p "NAME=Movie name (leave empty for "%DEFAULT_NAME%"): "
    if "!NAME!"=="" set "NAME=!DEFAULT_NAME!"
    goto :encode
)

:: --- NORMAL MODE -----------------------------------------------------

cls
echo.
echo  +==================================================================+
echo  ^|                          R I P ^& T E A R                          ^|
echo  ^|                     RTX ENCODE PIPELINE                           ^|
echo  ^|            RIP -^> UPSCALE -^> DEBLUR -^> ENCODE -^> MUX            ^|
echo  +==================================================================+
echo.

set /p "NAME=Movie name copied from TMDB (e.g. The Matrix (1999)): "
if "!NAME!"=="" (
    echo  Name required.
    pause & exit /b 1
)

:: --- CHECK FOR EXISTING RAW -----------------------------------------

if exist "%RAW%\*.mkv" (
    echo.
    echo  +------------------------------------------------------------------+
    echo  ^|  [SKIP]  RAW FILES FOUND -- USING EXISTING RIP                    ^|
    echo  +------------------------------------------------------------------+
    goto :find_raw
)

:: --- RIP ------------------------------------------------------------

echo.
echo  +------------------------------------------------------------------+
echo  ^|  RIPPING THE DISC FROM THE DEMON'S GRASP                         ^|
echo  +------------------------------------------------------------------+
echo.

if not exist "%RAW%" mkdir "%RAW%"

"%MAKEMKV%" --cache=1024 --minlength=600 mkv disc:0 all "%RAW%"
if errorlevel 1 (
    echo  +------------------------------------------------------------------+
    echo  ^|  THE DISC RESISTED! RIP FAILED.                                  ^|
    echo  +------------------------------------------------------------------+
    pause & exit /b 1
)

echo.
echo  +------------------------------------------------------------------+
echo  ^|  [OK]  RIP COMPLETE -- READY FOR TEARING                          ^|
echo  +------------------------------------------------------------------+

:: --- FIND LARGEST MKV -----------------------------------------------

:find_raw
echo.

set "INPUT_MKV="
set "MAXSIZE=0"
for %%f in ("%RAW%\*.mkv") do (
    set "SZ=%%~zf"
    if !SZ! GTR !MAXSIZE! (
        set "MAXSIZE=!SZ!"
        set "INPUT_MKV=%%f"
    )
)

if not defined INPUT_MKV (
    echo  +------------------------------------------------------------------+
    echo  ^|  NO MKV FILES FOUND IN raw\ !                                    ^|
    echo  +------------------------------------------------------------------+
    pause & exit /b 1
)

echo  Raw file:   %INPUT_MKV%

:: --- ENCODE ---------------------------------------------------------

:encode

set "OUTDIR=%ENCODED%\%NAME%"
set "OUTPUT=%OUTDIR%\%NAME%.mkv"

echo  Output:     %OUTPUT%
echo.

echo  +------------------------------------------------------------------+
echo  ^|  TEARING THE FLESH FROM ITS BONES                                 ^|
echo  ^|  NV UPSCALE + DEBLUR + NVENC ENCODE + MUX                         ^|
echo  +------------------------------------------------------------------+
echo.

python "%~dp0lib\RTX_encode.py" -i "%INPUT_MKV%" -o "%OUTPUT%"
if errorlevel 1 (
    echo.
    echo  +------------------------------------------------------------------+
    echo  ^|  THE ENCODE RESISTED! RTX PIPELINE FAILED.                       ^|
    echo  ^|  RAW FILES PRESERVED FOR RETRY.                                  ^|
    echo  +------------------------------------------------------------------+
    pause & exit /b 1
)

:: --- VERIFY OUTPUT -------------------------------------------------

if not exist "%OUTPUT%" (
    echo.
    echo  +------------------------------------------------------------------+
    echo  ^|  OUTPUT FILE MISSING! ENCODE MAY HAVE SILENTLY FAILED.           ^|
    echo  ^|  RAW FILES PRESERVED FOR RETRY.                                  ^|
    echo  +------------------------------------------------------------------+
    pause & exit /b 1
)

:: --- CLEANUP --------------------------------------------------------

if not defined SKIP_CLEANUP (
    echo.
    echo  +------------------------------------------------------------------+
    echo  ^|  CLEANING UP RAW FILES                                           ^|
    echo  +------------------------------------------------------------------+
    rmdir /s /q "%RAW%" 2>nul
)

:: --- DONE -----------------------------------------------------------

echo.
echo  +==================================================================+
echo  ^|  [OK]  RTX PIPELINE COMPLETE!                                     ^|
echo  ^|                                                                   ^|
echo  ^|  %NAME%                                                           ^|
echo  ^|  %OUTPUT%                                                         ^|
echo  +==================================================================+
echo.
pause
