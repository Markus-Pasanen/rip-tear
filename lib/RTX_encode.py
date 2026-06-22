"""
RTX_encode.py — DVD Restoration Pipeline v2
Single-file; everything lives here.

Usage:
    python RTX_encode.py -i raw/movie.mkv -o out/movie.mkv
    python RTX_encode.py -c config.yaml -i raw/movie.mkv -o out/movie.mkv

"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from queue import Queue

import av
import numpy as np
import torch
import torch.nn.functional as F
import yaml
from PIL import Image

os.environ["TRANSFORMERS_VERBOSITY"] = "error"


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class Pipeline:
    """GPU-accelerated DVD restoration pipeline."""

    def __init__(self, config_path: str, debug: bool = False):
        self.cfg = load_config(config_path)
        self.device = torch.device("cuda:0")
        self.gpu = 0
        self.debug = debug

        self.in_w = self.in_h = None
        self.target_w = self.target_h = None

        self.nv_upscaler = None
        self.nv_deblur = None
        self._stream_ptr = None

        self.frames_processed = 0
        self._start_time = None

        if self.debug:
            self.debug_dir = Path("debug")
            if self.debug_dir.exists():
                shutil.rmtree(self.debug_dir)
            self.debug_dir.mkdir()
            self._debug_step = 0

    def configure(self, in_w: int, in_h: int, sar=None):
        self.in_w = in_w
        self.in_h = in_h

        if sar and sar.numerator and sar.denominator:
            dar = (in_w * sar.numerator) / (in_h * sar.denominator)
        else:
            dar = in_w / in_h

        self.target_h = self.cfg["output"]["target_height"]
        self.target_w = int(self.target_h * dar)
        self.target_w += self.target_w % 2

        self.blur_sigma = float(self.cfg.get("blur_sigma", 0))
        self.upscale_quality = self.cfg.get("upscale_quality", "ULTRA")
        self.deblur_quality = self.cfg.get("deblur_quality", "none")

        torch.cuda.set_device(self.gpu)
        torch.backends.cudnn.benchmark = True
        self._stream_ptr = torch.cuda.current_stream().cuda_stream

        print(f"  Resolution chain:  {in_w}x{in_h}  ->  {self.target_w}x{self.target_h}")
        self._load_models()

    def _load_models(self):
        from nvvfx import VideoSuperRes
        Q = VideoSuperRes.QualityLevel

        q_up = self.upscale_quality.upper()
        self.nv_upscaler = VideoSuperRes(device=self.gpu, quality=Q[q_up])
        self.nv_upscaler.input_width = self.in_w
        self.nv_upscaler.input_height = self.in_h
        self.nv_upscaler.output_width = self.target_w
        self.nv_upscaler.output_height = self.target_h
        self.nv_upscaler.load()
        print(f"  NV UPSCALE:        {q_up}  {self.in_w}x{self.in_h} -> {self.target_w}x{self.target_h}")

        q_db = self.deblur_quality.upper()
        if q_db != "NONE":
            q_key = f"DEBLUR_{q_db}"
            self.nv_deblur = VideoSuperRes(device=self.gpu, quality=Q[q_key])
            self.nv_deblur.input_width = self.target_w
            self.nv_deblur.input_height = self.target_h
            self.nv_deblur.output_width = self.target_w
            self.nv_deblur.output_height = self.target_h
            self.nv_deblur.load()
            print(f"  NV DEBLUR:         {q_db}  @ {self.target_w}x{self.target_h}")
        else:
            self.nv_deblur = None
            print(f"  NV DEBLUR:         OFF")

    def close(self):
        if self.nv_upscaler is not None:
            self.nv_upscaler.close()
        if self.nv_deblur is not None:
            self.nv_deblur.close()

    def upscale_frame(self, frame: torch.Tensor) -> torch.Tensor:
        out = self.nv_upscaler.run(frame, stream_ptr=self._stream_ptr)
        return torch.from_dlpack(out.image).clone()

    def gaussian_blur(self, batch: torch.Tensor, sigma: float = 1.0) -> torch.Tensor:
        kernel_size = int(sigma * 6) | 1
        x = torch.arange(-(kernel_size // 2), kernel_size // 2 + 1, dtype=torch.float32, device=self.device)
        k = torch.exp(-0.5 * (x / sigma) ** 2)
        k = k / k.sum()
        k = (k[:, None] * k[None, :])[None, None]
        k = k.expand(batch.shape[1], 1, kernel_size, kernel_size)
        return F.conv2d(
            F.pad(batch, [kernel_size // 2] * 4, mode="reflect"),
            k, groups=batch.shape[1],
        )

    def deblur_frame(self, frame: torch.Tensor) -> torch.Tensor:
        out = self.nv_deblur.run(frame, stream_ptr=self._stream_ptr)
        return torch.from_dlpack(out.image).clone()

    def color_grade(self, batch: torch.Tensor) -> torch.Tensor:
        cc = self.cfg.get("color", {})
        if not cc.get("enabled", False):
            return batch
        contrast = cc.get("contrast", 1.0)
        shadow_lift = cc.get("shadow_lift", 0.0)
        saturation = cc.get("saturation", 1.0)
        if shadow_lift > 0:
            luma = 0.299 * batch[:, 0:1] + 0.587 * batch[:, 1:2] + 0.114 * batch[:, 2:3]
            batch = (batch + (1 - luma).clamp(0, 1) ** 2 * shadow_lift).clamp(0, 1)
        pivot = 0.18
        batch = pivot + (batch - pivot) * contrast
        batch = batch.clamp(0, 1)
        if abs(saturation - 1.0) > 0.001:
            r, g, b = batch[:, 0:1], batch[:, 1:2], batch[:, 2:3]
            gray = 0.299 * r + 0.587 * g + 0.114 * b
            batch = torch.cat([
                (gray + saturation * (r - gray)).clamp(0, 1),
                (gray + saturation * (g - gray)).clamp(0, 1),
                (gray + saturation * (b - gray)).clamp(0, 1),
            ], dim=1)
        return batch.clamp(0, 1)

    def _process_debug(self, input_path: Path):
        decode_cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-i", str(input_path),
            "-vf", "bwdif=0:0,format=rgb24",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-vframes", "1",
            "pipe:1",
        ]
        ffmpeg_dec = subprocess.Popen(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        data = ffmpeg_dec.stdout.read()
        ffmpeg_dec.wait()
        if not data:
            print("  DEBUG: no frames decoded")
            return

        frame = self._bytes_to_tensor(data)
        self._dbg_save(frame.unsqueeze(0), "raw")

        frame = self.upscale_frame(frame)
        self._dbg_save(frame.unsqueeze(0), "upscale")

        if self.blur_sigma > 0:
            frame = self.gaussian_blur(frame.unsqueeze(0), sigma=self.blur_sigma).squeeze(0)
            self._dbg_save(frame.unsqueeze(0), "blur")

        if self.nv_deblur is not None:
            frame = self.deblur_frame(frame)
            self._dbg_save(frame.unsqueeze(0), "deblur")

        batch = self.color_grade(frame.unsqueeze(0))
        self._dbg_save(batch, "color")

        n = self._debug_step
        print(f"  DEBUG: saved {n} frames to debug/")
        print(f"  DEBUG: skipping encode — exiting")

    def _tensor_to_bytes(self, t: torch.Tensor) -> bytes:
        return (
            t.clamp(0, 1).mul_(255).byte()
            .permute(1, 2, 0).contiguous().cpu().numpy().tobytes()
        )

    def _bytes_to_tensor(self, data: bytes) -> torch.Tensor:
        arr = np.frombuffer(data, dtype=np.uint8).copy().reshape(self.in_h, self.in_w, 3)
        t = torch.from_numpy(arr).to(self.device)
        return t.permute(2, 0, 1).float().div_(255.0).contiguous()

    def _dbg_save(self, t: torch.Tensor, label: str):
        if not self.debug:
            return
        arr = t.detach().squeeze(0).cpu().clamp(0, 1).numpy()
        if arr.ndim == 3:
            arr = (arr * 255).astype(np.uint8).transpose(1, 2, 0)
        else:
            arr = (arr * 255).astype(np.uint8)
        img = Image.fromarray(arr)
        img.save(self.debug_dir / f"{self._debug_step:02d}_{label}.png")
        self._debug_step += 1

    def process(self, input_path: str, output_path: str):
        input_path = Path(input_path)
        output_path = Path(output_path)

        container = av.open(str(input_path))
        stream = container.streams.video[0]
        in_w = stream.codec_context.width
        in_h = stream.codec_context.height
        fps = float(stream.average_rate) if stream.average_rate else 25.0
        sar = stream.codec_context.sample_aspect_ratio
        total_frames = stream.frames or 0
        container.close()

        self.configure(in_w, in_h, sar)

        batch_size = self.cfg.get("batch", {}).get("size", 4)
        cq = self.cfg.get("encode", {}).get("cq", 20)
        preset = self.cfg.get("encode", {}).get("preset", "p7")
        lang_cfg = self.cfg.get("languages", {})
        audio_langs = lang_cfg.get("audio", ["fin", "eng"])
        sub_langs = lang_cfg.get("subtitles", ["fin", "eng"])

        print()
        print(f"  Input:        {input_path}")
        print(f"  Output:       {output_path}")
        print(f"  Source:       {in_w}x{in_h} @ {fps:.2f} fps  ({total_frames or '?'} frames)")
        print(f"  Deinterlace:  bwdif  (field blend, {fps:.2f} fps)")
        print(f"  Upscale:      {self.upscale_quality}  {in_w}x{in_h} -> {self.target_w}x{self.target_h}")
        if self.blur_sigma > 0:
            print(f"  Blur:         gaussian  sigma={self.blur_sigma}")
        if self.nv_deblur is not None:
            print(f"  Deblur:       {self.deblur_quality}  @ {self.target_w}x{self.target_h}")
        print(f"  Batch size:   {batch_size}")
        print(f"  Color:        {'ON' if self.cfg.get('color', {}).get('enabled') else 'OFF'}")
        print(f"  Encoder:      NVENC {preset}  CQ {cq}  hq tune  b-frames  CAS  10-bit  {self.target_w}x{self.target_h}")
        print()

        if self.debug:
            self._process_debug(input_path)
            return

        output_path.parent.mkdir(parents=True, exist_ok=True)

        decode_cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-i", str(input_path),
            "-vf", "bwdif=0:0,format=rgb24",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-vsync", "0",
            "pipe:1",
        ]
        ffmpeg_dec = subprocess.Popen(decode_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        temp_dir = Path(tempfile.mkdtemp())
        temp_video = temp_dir / "video.mkv"
        encode_cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{self.target_w}x{self.target_h}",
            "-r", str(fps),
            "-i", "-",
            "-vf", "cas=0.5",
            "-c:v", "hevc_nvenc",
            "-preset", preset,
            "-cq", str(cq),
            "-rc-lookahead", "32",
            "-bf", "2",
            "-spatial-aq", "1", "-temporal-aq", "1",
            "-pix_fmt", "p010le",
            "-colorspace", "bt709",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            str(temp_video),
        ]
        ffmpeg_enc = subprocess.Popen(encode_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

        frame_bytes_len = in_w * in_h * 3
        in_queue = Queue(maxsize=batch_size * 4)
        out_queue = Queue(maxsize=batch_size * 4)
        io_stop = threading.Event()

        def reader_thread():
            buf = bytearray()
            try:
                while not io_stop.is_set():
                    needed = frame_bytes_len * batch_size
                    while len(buf) < needed:
                        chunk = ffmpeg_dec.stdout.read(min(needed - len(buf), frame_bytes_len))
                        if not chunk:
                            break
                        buf.extend(chunk)
                    if len(buf) < frame_bytes_len:
                        break
                    frames = []
                    for _ in range(batch_size):
                        if len(buf) >= frame_bytes_len:
                            frames.append(bytes(buf[:frame_bytes_len]))
                            buf = buf[frame_bytes_len:]
                        else:
                            break
                    if frames:
                        in_queue.put(frames)
                in_queue.put(None)
            except Exception:
                in_queue.put(None)

        def writer_thread():
            try:
                while True:
                    item = out_queue.get()
                    if item is None:
                        break
                    ffmpeg_enc.stdin.write(item)
            except Exception:
                pass

        reader = threading.Thread(target=reader_thread, daemon=True)
        writer = threading.Thread(target=writer_thread, daemon=True)
        reader.start()
        writer.start()

        self._start_time = time.time()
        self.frames_processed = 0
        last_report = time.time()

        try:
            while True:
                try:
                    frames_data = in_queue.get(timeout=5)
                except:
                    if time.time() - last_report > 4:
                        print(f"  Waiting for ffmpeg decode ... ({time.time() - self._start_time:.0f}s)", end="\r")
                        last_report = time.time()
                    continue
                if frames_data is None:
                    break

                frames = [self._bytes_to_tensor(d) for d in frames_data]
                batch = torch.stack(frames)

                upscaled = []
                for i in range(batch.shape[0]):
                    upscaled.append(self.upscale_frame(batch[i]))
                batch = torch.stack(upscaled)

                if self.blur_sigma > 0:
                    batch = self.gaussian_blur(batch, sigma=self.blur_sigma)

                if self.nv_deblur is not None:
                    deblurred = []
                    for i in range(batch.shape[0]):
                        deblurred.append(self.deblur_frame(batch[i]))
                    batch = torch.stack(deblurred)

                batch = self.color_grade(batch)

                for i in range(batch.shape[0]):
                    out_queue.put(self._tensor_to_bytes(batch[i]))

                n = len(frames_data)
                self.frames_processed += n
                if self.frames_processed % 50 == 0:
                    elapsed = time.time() - self._start_time
                    fps_rate = self.frames_processed / elapsed
                    pct = f"{self.frames_processed / total_frames * 100:.1f}%" if total_frames else "?"
                    print(f"  {self.frames_processed}/{total_frames or '?'} "
                          f"({pct}) @ {fps_rate:.1f} fps   ", end="\r")
        finally:
            io_stop.set()
            out_queue.put(None)

        reader.join()
        writer.join()
        ffmpeg_dec.stdout.close()
        ffmpeg_dec.wait()
        if ffmpeg_dec.returncode != 0:
            print(f"\n  WARNING: ffmpeg decode exited with code {ffmpeg_dec.returncode}")
        ffmpeg_enc.stdin.close()
        ffmpeg_enc.wait()

        print()

        print("  Muxing audio / subs / chapters ...")
        mux_cmd = [
            "ffmpeg", "-y",
            "-i", str(temp_video),
            "-i", str(input_path),
            "-map", "0:v:0",
        ]
        for lang in audio_langs:
            mux_cmd.extend(["-map", f"1:a:m:language:{lang}?"])
        for lang in sub_langs:
            mux_cmd.extend(["-map", f"1:s:m:language:{lang}?"])
        mux_cmd.extend([
            "-map_chapters", "1",
            "-map_metadata", "1",
            "-c", "copy",
            str(output_path),
        ])
        r = subprocess.run(mux_cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print("  WARNING: chapters/metadata failed, retrying without ...")
            mux_cmd2 = [
                "ffmpeg", "-y",
                "-i", str(temp_video),
                "-i", str(input_path),
                "-map", "0:v:0",
            ]
            for lang in audio_langs:
                mux_cmd2.extend(["-map", f"1:a:m:language:{lang}?"])
            for lang in sub_langs:
                mux_cmd2.extend(["-map", f"1:s:m:language:{lang}?"])
            mux_cmd2.extend([
                "-c", "copy",
                str(output_path),
            ])
            subprocess.run(mux_cmd2, check=True, stderr=subprocess.DEVNULL)

        temp_video.unlink()
        temp_dir.rmdir()

        elapsed = time.time() - self._start_time
        size_mb = output_path.stat().st_size / 1024 / 1024
        print(f"  Done!  {self.frames_processed} frames  in  {elapsed:.1f}s  "
              f"({self.frames_processed / elapsed:.1f} fps)")
        print(f"  Size:  {size_mb:.1f} MB")
        print(f"  Output:  {output_path}")


def parse_args():
    p = argparse.ArgumentParser(description="RTX Video Pipeline")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--debug", action="store_true",
                   help="Process first frame only, save each step as PNG to debug/, skip encode")
    return p.parse_args()


def main():
    args = parse_args()
    print()
    print("=" * 60)
    print("  RTX VIDEO PIPELINE")
    print("=" * 60)
    cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs", "RTX_config.yaml")
    pipe = Pipeline(cfg, debug=args.debug)
    try:
        pipe.process(args.input, args.output)
    finally:
        pipe.close()


if __name__ == "__main__":
    main()
