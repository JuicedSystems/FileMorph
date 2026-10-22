"""Audio & video conversions with bundled FFmpeg."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .. import proc
from ..registry import ConversionError, Ctx, Registry

AUDIO_IN = ["mp3", "wav", "m4a", "flac", "ogg", "opus", "wma", "aiff"]
AUDIO_OUT = ["mp3", "wav", "m4a", "flac", "ogg", "opus"]
VIDEO_IN = ["mp4", "mov", "mkv", "webm", "avi", "wmv"]
VIDEO_OUT = ["mp4", "mov", "mkv", "webm", "avi"]

_AUDIO_ARGS = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "wav": ["-c:a", "pcm_s16le"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "flac": ["-c:a", "flac"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "6"],
    "opus": ["-c:a", "libopus", "-b:a", "160k"],
}
_EVEN = ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p"]
_VIDEO_ARGS = {
    "mp4": ["-c:v", "libx264", "-preset", "medium", "-crf", "{crf}", *_EVEN, "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart"],
    "mov": ["-c:v", "libx264", "-preset", "medium", "-crf", "{crf}", *_EVEN, "-c:a", "aac", "-b:a", "160k"],
    "mkv": ["-c:v", "libx264", "-preset", "medium", "-crf", "{crf}", *_EVEN, "-c:a", "aac", "-b:a", "160k"],
    "webm": ["-c:v", "libvpx-vp9", "-crf", "{crf9}", "-b:v", "0", "-row-mt", "1", "-deadline", "good",
             "-cpu-used", "4", "-pix_fmt", "yuv420p", "-c:a", "libopus", "-b:a", "128k"],
    "avi": ["-c:v", "mpeg4", "-q:v", "3", "-c:a", "libmp3lame", "-q:a", "3"],
}


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise ConversionError("The media engine (FFmpeg) is missing from this installation.") from e


def probe(src: Path, ctx: Ctx | None = None) -> dict:
    """Duration, and whether there are audio/video streams (parsed from ffmpeg -i)."""
    # `ffmpeg -i` without an output always exits non-zero; we only want its stderr report.
    _, _, err = proc.run_capture([ffmpeg_exe(), "-hide_banner", "-nostdin", "-i", str(src)], ctx, timeout=60)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0
    has_video = bool(re.search(r"Stream #.*Video:(?!.*(?:png|mjpeg).*attached pic)", err))
    return {"duration": dur, "audio": "Audio:" in err, "video": has_video}


def _run_ffmpeg(args: list[str], src: Path, ctx: Ctx, duration: float, label: str):
    def on_line(line: str):
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                us = int(line.split("=", 1)[1])
            except ValueError:
                return
            if duration > 0:
                ctx.progress(us / 1e6 / duration, label)
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats",
           "-i", str(src), *args]
    # No fixed time limit for long videos: only stop if ffmpeg stops reporting progress for 10 min
    proc.run(cmd, ctx, on_line=on_line, err_msg="The media file couldn't be converted.",
             timeout=600, idle_timeout=True)


def to_audio(src: Path, dst: Path, ctx: Ctx):
    info = probe(src, ctx)
    if not info["audio"]:
        raise ConversionError("This file has no audio track to convert.")
    _run_ffmpeg(["-vn", "-map", "0:a:0", *_AUDIO_ARGS[ctx.dst_fmt], str(dst)], src, ctx, info["duration"],
                "Encoding audio")


def to_video(src: Path, dst: Path, ctx: Ctx):
    info = probe(src, ctx)
    if not info["video"] and ctx.src_fmt != "gif":
        raise ConversionError("This file has no video track.")
    q = int(ctx.opt("quality", 90))  # 50..100 -> crf
    crf = str(round(35 - (q - 50) * 0.3))      # 90 -> 23
    crf9 = str(round(45 - (q - 50) * 0.3))     # 90 -> 33
    args = [a.replace("{crf}", crf).replace("{crf9}", crf9) for a in _VIDEO_ARGS[ctx.dst_fmt]]
    maps = ["-map", "0:v:0"] + (["-map", "0:a:0?"] if info["audio"] else ["-an"])
    _run_ffmpeg([*maps, *args, str(dst)], src, ctx, info["duration"], "Encoding video")


def video_to_gif(src: Path, dst: Path, ctx: Ctx):
    info = probe(src, ctx)
    width = int(ctx.opt("gif_width", 640))
    fps = int(ctx.opt("gif_fps", 12))
    vf = (f"fps={fps},scale='min({width},iw)':-1:flags=lanczos,split[a][b];"
          f"[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4")
    _run_ffmpeg(["-vf", vf, "-loop", "0", str(dst)], src, ctx, info["duration"], "Making GIF")


def register(reg: Registry) -> None:
    reg.add(AUDIO_IN + VIDEO_IN, AUDIO_OUT, to_audio, label="Encoding audio", engine="ffmpeg")
    reg.add(VIDEO_IN + ["gif"], VIDEO_OUT, to_video, cost=1.2, label="Encoding video", engine="ffmpeg")
    reg.add(VIDEO_IN, "gif", video_to_gif, cost=1.2, label="Making GIF", engine="ffmpeg")
