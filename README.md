# Rip & Tear

DVD/Blu-ray restoration pipeline -- rip, upscale, deblur, encode, and remux into Jellyfin-ready files.

## Requirements

### Software

| Tool | Purpose |
|---|---|
| Windows 10+ | OS (batch scripts use PowerShell-compatible shell) |
| [MakeMKV](https://www.makemkv.com/) | Disc ripping (`makemkvcon64.exe` expected at `C:\Program Files (x86)\MakeMKV\`) |
| [Python 3.10+](https://www.python.org/) | AI pipeline runtime |
| [FFmpeg](https://ffmpeg.org/) | Video decode/encode/mux (`ffmpeg`, `ffprobe` on PATH) |

### Python Packages

```
pip install torch numpy pillow av nvidia-vfx pyyaml
```

### Hardware

| Pipeline | Required |
|---|---|
| `RTX_encode.bat` | NVIDIA RTX GPU (NV VFX upscale + deblur) |
| `direct_encode.bat` | NVIDIA GPU with NVENC (any GTX/RTX) |

## Directory Structure

```
rip-and-tear/
  RTX_encode.bat          AI pipeline (rip -> upscale -> deblur -> encode -> mux)
  direct_encode.bat       No-AI pipeline (rip -> deinterlace -> encode -> mux)
  encoded/                Output files (gitignored, created automatically)
  raw/                    Temporary rip directory (gitignored, auto-cleaned)
  lib/
    RTX_encode.py         Python pipeline
    configs/
      RTX_config.yaml     Quality and encode settings
    tools/
      rip.bat             Standalone rip-only script
      clip.bat            Extract a 1-minute test clip from a raw MKV
      debug/              Debug frame output (gitignored)
      test_clips/         Test clip output (gitignored)
```

## Usage

### RTX Encode (full AI pipeline)

Double-click `RTX_encode.bat`:

1. Enter the movie name in TMDB format, e.g. `The Matrix (1999)`
2. The script checks `raw/` for existing rips -- if found, ripping is skipped
3. If `raw/` is empty, the disc is ripped via MakeMKV
4. The largest MKV in `raw/` is selected as the source
5. The Python pipeline runs each frame through the following stages in order:
   - **Deinterlace** -- bwdif field-blend deinterlace, converting interlaced DVD fields to progressive frames
   - **NV Upscale** -- NVIDIA Video Super Resolution upscales to 1080p (quality level configurable: ULTRA/HIGH/MEDIUM/LOW/BICUBIC)
   - **Gaussian Blur** -- optional pre-blur to soften source compression artifacts before sharpening (configurable sigma, 0 = off)
   - **NV Deblur** -- NVIDIA Video Super Resolution deblur pass for detail restoration and sharpening (quality level configurable, none = off)
   - **Color Grading** -- optional color correction pass: contrast adjustment, shadow lift, and saturation control
   - **CAS Sharpening** -- Contrast Adaptive Sharpening filter applied during ffmpeg encode
   - **NVENC Encode** -- hardware h.264 encoding at preset p7, CQ 20, 8-bit yuv420p
   - **Remux** -- original audio tracks, subtitles, chapters, and metadata are merged into the final MKV
6. Output is written to `encoded/<Movie Name>/<Movie Name>.mkv`
7. `raw/` is cleaned up only after a verified successful encode

### Direct Encode (no AI, fast)

Double-click `direct_encode.bat`:

Same flow as RTX Encode but skips the AI steps. It only deinterlaces and encodes with NVENC h.264. Ideal for Blu-rays or content that needs no upscaling.

### Drag and Drop

Drag any `.mkv` or `.mp4` file onto either `.bat`:

- The rip step is skipped entirely
- The script prompts for a movie name (leave blank to use the filename)
- Encoding proceeds directly from the dropped file
- The `raw/` folder is not created or touched

### Standalone Rip

Run `lib/tools/rip.bat` to rip the disc to `raw/` without encoding. Useful for ripping multiple discs ahead of time, then encoding in bulk later.

### Test Clip

Drag a raw MKV onto `lib/tools/clip.bat` to extract a 1-minute sample clip into `lib/tools/test_clips/`. The clip starts at a random timestamp between 500 and 3000 seconds.

## Configuration

Edit `lib/configs/RTX_config.yaml` to adjust:

| Setting | Default | Description |
|---|---|---|
| `target_height` | 1080 | Output resolution height |
| `upscale_quality` | ULTRA | NV VFX upscale quality: ULTRA, HIGH, MEDIUM, LOW, BICUBIC |
| `deblur_quality` | ULTRA | NV VFX deblur quality: ULTRA, HIGH, MEDIUM, LOW, none |
| `blur_sigma` | 2.0 | Gaussian blur before deblur -- softens compression artifacts (0 = off) |
| `color.enabled` | true | Enable color grading pass |
| `color.shadow_lift` | 0.04 | Gentle lift to open crushed DVD blacks |
| `color.contrast` | 1.10 | Mild pivoted contrast increase (anchored at 0.18) |
| `color.saturation` | 1.20 | Moderate saturation boost via Rec.601 luma weights |
| `encode.cq` | 20 | NVENC quality (lower = better, 1-51) |
| `encode.preset` | p7 | NVENC preset (p1 fastest, p7 best quality) |
| `batch.size` | 4 | Frames per GPU batch |

Direct encode uses the same encode settings (`cq`, `preset`) as the RTX pipeline. Its config is at `lib/configs/direct_config.yaml`.

### Language Filtering

Both configs include a `languages` section controlling which audio and subtitle tracks are kept during muxing:

```yaml
languages:
  audio: [fin, eng]        # Audio tracks to keep (ISO 639-2)
  subtitles: [fin, eng]    # Subtitle tracks to keep (ISO 639-2)
```

In the RTX pipeline this is read at runtime by the Python script. In the direct encode pipeline the values are mirrored as batch variables at the top of `direct_encode.bat`. Edit the list to match your region's languages (e.g. `[deu, eng]` for German, `[jpn, eng]` for Japanese).

### Color Grading Algorithm

When `color.enabled` is `true`, three operations are applied per frame on the GPU, in order:

**Shadow Lift** — fills dark areas using an inverse-luma mask.
```
pixel + (1 - luma)^2 * shadow_lift
```
The squared falloff targets only the deepest shadows without touching midtones.

**Pivoted Contrast** — contrast adjustment centered on 18% middle gray.
```
0.18 + (pixel - 0.18) * contrast
```
Middle gray (0.18) is the photographic standard, so contrast expands or compresses the range while keeping midtones anchored.

**Saturation** — standard saturation using Rec.601 luma coefficients.
```
gray + saturation * (channel - gray)
```
Uses BT.601 weights (0.299R / 0.587G / 0.114B), correct for the SD/DVD color space the source content uses. Each RGB channel is blended with the grayscale image by the saturation factor.

All operations clamp to [0, 1] after each step.

## Output

All encoded files go to `encoded/<Movie Name>/<Movie Name>.mkv` with:

- Video: h.264 8-bit (yuv420p), NVENC p7, CQ 20, 1080p
- Audio: copied from source (original quality)
- Subtitles: copied from source
- Chapters: copied from source
- Metadata: copied from source

Files are ready for direct-play in Jellyfin without server-side transcoding.

## License

MIT License.

## Credits

This project relies on the following open-source and proprietary tools:

- [NVIDIA Video Effects SDK](https://developer.nvidia.com/video-effects-sdk) -- AI upscaling and deblur via `nvidia-vfx`
- [MakeMKV](https://www.makemkv.com/) -- disc decryption and ripping
- [FFmpeg](https://ffmpeg.org/) -- video decoding, encoding, filtering, and muxing
- [PyTorch](https://pytorch.org/) -- GPU tensor operations and neural network runtime
- [PyAV](https://pyav.org/) -- video container probing and stream metadata
- [NumPy](https://numpy.org/) -- array manipulation
- [Pillow](https://python-pillow.org/) -- debug frame export
- [PyYAML](https://pyyaml.org/) -- configuration file parsing
