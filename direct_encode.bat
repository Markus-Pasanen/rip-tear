@echo off
setlocal enabledelayedexpansion

:: --- CONFIG ---
set "MAKEMKV=C:\Program Files (x86)\MakeMKV\makemkvcon64.exe"
set "RAW=%~dp0raw"
set "ENCODED=%~dp0encoded"
:: Language filter (ISO 639-2) -- matching lib/configs/direct_config.yaml
::   Audio tracks outside these languages are skipped during mux.
::   Changing this requires editing the mux -map lines below.
set "AUDIO_LANGS=fin eng"
set "SUB_LANGS=fin eng"
:: -------------

:: --- DRAG & DROP MODE ------------------------------------------------

if not "%~1"=="" (
    set "INPUT_MKV=%~1"
    set "DROPMODE=1"
    set "DEFAULT_NAME=%~n1"
    cls
    echo.
    echo  +==================================================================+
    echo  ^|                          R I P ^& T E A R                          ^|
    echo  ^|                    DIRECT ENCODE PIPELINE                         ^|
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
echo  ^|                    DIRECT ENCODE PIPELINE                         ^|
echo  ^|              RIP -^> DEINTERLACE -^> ENCODE -^> MUX                ^|
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

set "DID_RIP=1"
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
echo  ^|  [OK]  RIP COMPLETE -- READY FOR ENCODING                         ^|
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

:: --- PROBE SOURCE ---------------------------------------------------

for /f "tokens=*" %%i in ('ffprobe -v error -select_streams v:0 -show_entries "stream=width,height,r_frame_rate" -of "csv=p=0" "%INPUT_MKV%"') do (
    set "PROBE=%%i"
)
for /f "tokens=1,2,3 delims=," %%a in ("!PROBE!") do (
    set "SRC_W=%%a"
    set "SRC_H=%%b"
    set "SRC_FPS=%%c"
)

echo  Source:     %SRC_W%x%SRC_H% @ %SRC_FPS% fps
echo.

echo  +------------------------------------------------------------------+
echo  ^|  TEARING THE FLESH FROM ITS BONES                                 ^|
echo  ^|  DEINTERLACE + NVENC H.264 + MUX                                  ^|
echo  +------------------------------------------------------------------+
echo.

mkdir "%OUTDIR%" 2>nul
set "TEMP_VIDEO=%TEMP%\video_encoded.mkv"

echo  Encoding video stream ...
ffmpeg -y -nostdin -i "%INPUT_MKV%" ^
    -vf "bwdif=mode=send_frame:parity=auto:deint=all,cas=0.5" ^
    -c:v h264_nvenc ^
    -preset p7 ^
    -cq 20 ^
    -tune hq ^
    -rc-lookahead 32 ^
    -b_ref_mode middle -bf 3 ^
    -spatial-aq 1 -temporal-aq 1 ^
    -pix_fmt yuv420p ^
    -colorspace bt709 ^
    -color_primaries bt709 ^
    -color_trc bt709 ^
    -an -sn -dn ^
    "%TEMP_VIDEO%"
if errorlevel 1 (
    echo  +------------------------------------------------------------------+
    echo  ^|  VIDEO ENCODE FAILED. RAW FILES PRESERVED.                       ^|
    echo  +------------------------------------------------------------------+
    pause & exit /b 1
)

echo.
echo  Muxing audio / subs / chapters ...
ffmpeg -y -nostdin ^
    -i "%TEMP_VIDEO%" ^
    -i "%INPUT_MKV%" ^
    -map 0:v:0 ^
    -map 1:a? ^
    -map 1:s? ^
    -map_chapters 1 ^
    -map_metadata 1 ^
    -c copy ^
    "%OUTPUT%"
if errorlevel 1 (
    echo  WARNING: chapters/metadata mux failed, retrying without ...
    ffmpeg -y -nostdin ^
        -i "%TEMP_VIDEO%" ^
        -i "%INPUT_MKV%" ^
        -map 0:v:0 ^
        -map 1:a? ^
        -map 1:s? ^
        -c copy ^
        "%OUTPUT%"
    if errorlevel 1 (
        echo  +------------------------------------------------------------------+
        echo  ^|  THE MUX RESISTED! ENCODE FAILED.                                ^|
        echo  ^|  RAW FILES PRESERVED FOR RETRY.                                  ^|
        echo  +------------------------------------------------------------------+
        del "%TEMP_VIDEO%" 2>nul
        pause & exit /b 1
    )
)

del "%TEMP_VIDEO%" 2>nul

:: --- VERIFY OUTPUT -------------------------------------------------

if not exist "%OUTPUT%" (
    echo  +------------------------------------------------------------------+
    echo  ^|  OUTPUT FILE MISSING! ENCODE MAY HAVE SILENTLY FAILED.           ^|
    echo  ^|  RAW FILES PRESERVED FOR RETRY.                                  ^|
    echo  +------------------------------------------------------------------+
    pause & exit /b 1
)

:: --- CLEANUP --------------------------------------------------------

if defined DID_RIP (
    echo.
    echo  +------------------------------------------------------------------+
    echo  ^|  CLEANING UP RAW FILES                                           ^|
    echo  +------------------------------------------------------------------+
    rmdir /s /q "%RAW%" 2>nul
)

:: --- DONE -----------------------------------------------------------

echo.
echo  +==================================================================+
echo  ^|  [OK]  DIRECT ENCODE COMPLETE!                                    ^|
echo  ^|                                                                   ^|
echo  ^|  %NAME%                                                           ^|
echo  ^|  %OUTPUT%                                                         ^|
echo  +==================================================================+
echo.
pause
