# rip-tear

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

DVD/Blu-ray restoration pipeline -- rip, upscale, deblur, color grade, encode, and remux into Jellyfin-ready files. Two paths: an AI pipeline with NVIDIA VFX (upscaling + deblur) and a fast direct-encode path for content that needs no restoration.

## Features

- **Disc ripping** -- MakeMKV integration, skips short extras (minimum 600 seconds)
- **AI upscaling** -- NVIDIA Video Super Resolution upscales DVD to 1080p (ULTRA quality)
- **AI deblur** -- NVIDIA Video Super Resolution deblur pass for detail restoration
- **Gaussian blur** -- optional pre-blur to soften compression artifacts before sharpening
- **Color grading** -- shadow lift, pivoted contrast, and Rec.601 saturation correction
- **CAS sharpening** -- Contrast Adaptive Sharpening applied during encode
- **NVENC encode** -- hardware h.264 8-bit (yuv420p) for universal browser direct-play
- **Full remux** -- original audio, subtitles, chapters, and metadata merged into final MKV
- **Drag-and-drop** -- drop any MKV/MP4 onto the batch file to skip ripping entirely
- **Smart resume** -- raw files are preserved on failure, cleaned only after verified success

## Prerequisites

| Tool | Purpose |
|---|---|
| Windows 10+ | OS |
| [MakeMKV](https://www.makemkv.com/) | Disc ripping (`makemkvcon64.exe` at `C:\Program Files (x86)\MakeMKV\`) |
| [Python 3.10+](https://www.python.org/) | AI pipeline runtime |
| [FFmpeg](https://ffmpeg.org/) | Video decode/encode/mux (`ffmpeg`, `ffprobe` on PATH) |

### Hardware

| Pipeline | Required |
|---|---|
| `RTX_encode.bat` | NVIDIA RTX GPU (NV VFX upscale + deblur) |
| `direct_encode.bat` | NVIDIA GPU with NVENC (any GTX/RTX) |

### Python packages

```bash
pip install -r requirements.txt
```

| Package | Purpose |
|---|---|
| `torch` | GPU tensor operations |
| `numpy` | Array manipulation |
| `pillow` | Debug frame export |
| `av` | Video container probing |
| `nvidia-vfx` | AI upscaling and deblur |
| `pyyaml` | Configuration file parsing |

## Quick start

Double-click `RTX_encode.bat` (AI pipeline) or `direct_encode.bat` (no-AI pipeline):

1. Enter the movie name in TMDB format, e.g. `The Matrix (1999)`
2. Insert the disc -- the script rips via MakeMKV
3. The largest title is selected and encoded
4. Output lands in `encoded/<Movie Name>/<Movie Name>.mkv`

If `raw/` already contains a previous rip, ripping is skipped and the existing files are used.

## Usage

### Drag and drop

Drag any `.mkv` or `.mp4` file onto either `.bat` to encode directly without ripping. The script prompts for a movie name -- leave blank to use the filename.

### Standalone rip

Run `lib/tools/rip.bat` to rip the disc to `raw/` without encoding. Useful for ripping multiple discs ahead of time.

### Test clip

Drag a raw MKV onto `lib/tools/clip.bat` to extract a 1-minute sample into `lib/tools/test_clips/`. The clip starts at a random offset between 500 and 3000 seconds.

## Pipeline stages

### RTX Encode (AI)

```
Deinterlace ──▶ NV Upscale (1080p) ──▶ Gaussian Blur ──▶ NV Deblur ──▶ Color Grade ──▶ CAS ──▶ NVENC Encode ──▶ Remux
```

1. **Deinterlace** -- bwdif field-blend, converting interlaced DVD fields to progressive frames
2. **NV Upscale** -- NVIDIA Video Super Resolution to 1080p (quality: ULTRA/HIGH/MEDIUM/LOW/BICUBIC)
3. **Gaussian Blur** -- optional pre-blur to soften compression artifacts (configurable sigma, 0 = off)
4. **NV Deblur** -- NVIDIA Video Super Resolution deblur for detail restoration (quality: ULTRA/HIGH/MEDIUM/LOW/none)
5. **Color Grading** -- shadow lift, pivoted contrast, and saturation correction (configurable)
6. **CAS Sharpening** -- Contrast Adaptive Sharpening filter applied during ffmpeg encode
7. **NVENC Encode** -- hardware h.264 8-bit at preset p7, CQ 20
8. **Remux** -- original audio, subtitles, chapters, and metadata merged into final MKV

### Direct Encode (no AI)

```
Deinterlace ──▶ CAS ──▶ NVENC Encode ──▶ Remux
```

Same flow without AI stages. Ideal for Blu-rays or content that needs no upscaling.

## Configuration

Edit `lib/configs/RTX_config.yaml` for the AI pipeline. Edit `lib/configs/direct_config.yaml` for the direct pipeline.

| Setting | Default | Description |
|---|---|---|
| `output.target_height` | 1080 | Output resolution height |
| `upscale_quality` | ULTRA | NV VFX upscale: ULTRA, HIGH, MEDIUM, LOW, BICUBIC |
| `deblur_quality` | ULTRA | NV VFX deblur: ULTRA, HIGH, MEDIUM, LOW, none |
| `blur_sigma` | 2.0 | Gaussian blur sigma (0 = off) |
| `color.enabled` | true | Enable color grading |
| `color.shadow_lift` | 0.04 | Gentle lift to open crushed DVD blacks |
| `color.contrast` | 1.10 | Mild pivoted contrast increase (anchored at 0.18) |
| `color.saturation` | 1.20 | Moderate saturation boost via Rec.601 luma weights |
| `encode.cq` | 20 | NVENC quality (lower = better, 1-51) |
| `encode.preset` | p7 | NVENC preset (p1 fastest, p7 best quality) |
| `batch.size` | 4 | Frames per GPU pass (see VRAM guidance in config) |
| `languages.audio` | [fin, eng] | Audio tracks to keep (ISO 639-2) |
| `languages.subtitles` | [fin, eng] | Subtitle tracks to keep (ISO 639-2) |

### Color grading algorithm

When `color.enabled` is `true`, three operations are applied per frame on the GPU, in order:

**Shadow lift** -- fills dark areas using an inverse-luma mask.
```
pixel + (1 - luma)^2 * shadow_lift
```
The squared falloff targets only the deepest shadows without touching midtones.

**Pivoted contrast** -- contrast adjustment centered on 18% middle gray.
```
0.18 + (pixel - 0.18) * contrast
```
Middle gray (0.18) is the photographic standard, so contrast expands or compresses the range while keeping midtones anchored.

**Saturation** -- standard saturation using Rec.601 luma coefficients.
```
gray + saturation * (channel - gray)
```
Uses BT.601 weights (0.299R / 0.587G / 0.114B), correct for the SD/DVD color space. Each RGB channel is blended with the grayscale image by the saturation factor.

All operations clamp to [0, 1] after each step.

## Directory structure

```
rip-and-tear/
  RTX_encode.bat          AI pipeline
  direct_encode.bat       No-AI pipeline
  encoded/                Output files (gitignored, created automatically)
  raw/                    Temporary rip directory (gitignored, auto-cleaned)
  requirements.txt        Python dependencies
  lib/
    RTX_encode.py         Python pipeline
    configs/
      RTX_config.yaml     Quality and encode settings
      direct_config.yaml  Direct encode settings
    tools/
      rip.bat             Standalone rip-only script
      clip.bat            Extract a 1-minute test clip
      debug/              Debug frame output (gitignored)
      test_clips/         Test clip output (gitignored)
```

## Output

All encoded files go to `encoded/<Movie Name>/<Movie Name>.mkv` with:

- **Video** -- h.264 8-bit (yuv420p), NVENC p7, CQ 20, 1080p
- **Audio** -- copied from source (original quality)
- **Subtitles** -- copied from source
- **Chapters** -- copied from source
- **Metadata** -- copied from source

Files direct-play in Jellyfin on any browser or device. No server-side transcoding required.

## Credits

This project relies on the following tools:

- [NVIDIA Video Effects SDK](https://developer.nvidia.com/video-effects-sdk) -- AI upscaling and deblur via `nvidia-vfx`
- [MakeMKV](https://www.makemkv.com/) -- disc decryption and ripping
- [FFmpeg](https://ffmpeg.org/) -- video decode, encode, filter, and mux
- [PyTorch](https://pytorch.org/) -- GPU tensor operations and neural network runtime
- [PyAV](https://pyav.org/) -- video container probing and stream metadata
- [NumPy](https://numpy.org/) -- array manipulation
- [Pillow](https://python-pillow.org/) -- debug frame export
- [PyYAML](https://pyyaml.org/) -- configuration file parsing

## License

MIT -- see [LICENSE](LICENSE) for details.
