"""Offline, bounded video decoding for the new window planner.

This adapter never invokes an AI client or the application render pipeline.
Only a verified local file is decoded; timestamps come from decoder PTS rather
than being copied from the requested candidate timestamp.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time

from app.analysis.frame_selection import (
    FrameCandidate, FrameSample, FrameSelectionConfig, generate_candidates,
)
from app.analysis.perceptual_hash import perceptual_hash
from app.analysis.window_planner import PlanningResult
from app.schemas.script_contracts_v1 import Provenance


DECODER_VERSION = "ffmpeg-window-gray32-0.1"
MAX_DECODE_FRAMES = 1024
MAX_TIMEOUT_SECONDS = 120
_TIME_BASE = re.compile(r"config in time_base:\s*(\d+)/(\d+)")
_FRAME_PTS = re.compile(r"\bn:\s*0\s+pts:\s*(-?\d+)\s+pts_time:")


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, check=False)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("total decode time budget exhausted")
    return remaining


def _unavailable(candidate: FrameCandidate, reason: str) -> FrameSample:
    return FrameSample(frameId=candidate.frameId, assetHash=candidate.assetHash,
        decodedTimestampMs=None, perceptualHash=None,
        source=Provenance(mode="UNAVAILABLE", provider="ffmpeg", model=DECODER_VERSION,
                          reason=reason))


def _file_hash(path: Path, deadline: float) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            _remaining(deadline)
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _probe_start(ffprobe: str, path: Path, deadline: float) -> Fraction:
    result = _run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                   "stream=start_pts,start_time,time_base", "-of", "json", str(path)],
                  _remaining(deadline))
    if result.returncode != 0:
        raise ValueError("video timing probe failed")
    if len(result.stdout) > 65536:
        raise ValueError("video timing probe exceeded metadata limit")
    try:
        streams = json.loads(result.stdout)["streams"]
        if len(streams) != 1:
            raise ValueError("exactly one selected video stream is required")
        stream = streams[0]
        # start_pts and time_base avoid precision loss from ffprobe's decimal
        # start_time. Some containers only provide a decimal start_time.
        if type(stream.get("start_pts")) is int and "time_base" in stream:
            base = Fraction(stream["time_base"])
            if base <= 0:
                raise ValueError("invalid video time base")
            return stream["start_pts"] * base
        start = Decimal(stream["start_time"])
        if not start.is_finite():
            raise ValueError("nonfinite stream start time")
        return Fraction(start)
    except (KeyError, TypeError, json.JSONDecodeError, InvalidOperation,
            ZeroDivisionError, OverflowError) as exc:
        raise ValueError("video stream start timestamp is unavailable") from exc


def _seconds_arg(value: Fraction) -> str:
    # -ss takes a decimal duration. Twelve places are substantially finer than
    # the millisecond contract; observed PTS still decides acceptance.
    return format(Decimal(value.numerator) / Decimal(value.denominator), ".12f")


def _decoded_ms(stderr: bytes, stream_start: Fraction) -> int:
    log = stderr.decode("utf-8", errors="replace")
    bases = _TIME_BASE.findall(log)
    pts = _FRAME_PTS.findall(log)
    if len(bases) != 1 or len(pts) != 1:
        raise ValueError("decoder did not report one unambiguous frame PTS")
    numerator, denominator = map(int, bases[0])
    if numerator <= 0 or denominator <= 0:
        raise ValueError("decoder reported an invalid time base")
    millis = (int(pts[0]) * Fraction(numerator, denominator) - stream_start) * 1000
    if millis < 0:
        raise ValueError("decoded frame precedes the source video start")
    # Nearest integer millisecond, with half-millisecond ties rounded upward.
    return (millis.numerator * 2 + millis.denominator) // (2 * millis.denominator)


def _decode(ffmpeg: str, path: Path, candidate: FrameCandidate,
            stream_start: Fraction, deadline: float) -> tuple[int, str]:
    absolute = stream_start + Fraction(candidate.timestampMs, 1000)
    result = _run([
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "info", "-copyts",
        "-seek_timestamp", "1", "-ss", _seconds_arg(absolute), "-threads", "1",
        "-i", str(path), "-map", "0:v:0", "-an", "-sn", "-dn",
        "-filter_threads", "1", "-vf", "scale=32:32:flags=area,format=gray,showinfo",
        "-frames:v", "1", "-fps_mode", "passthrough", "-threads", "1",
        "-f", "rawvideo", "pipe:1",
    ], _remaining(deadline))
    # The process emits at most one 32x32 grayscale frame. Failed or partial
    # output never becomes a zero image or a fabricated successful sample.
    if result.returncode != 0:
        raise ValueError("frame decoder failed")
    if len(result.stdout) != 32 * 32:
        raise ValueError("decoder did not return one complete 32x32 grayscale frame")
    if len(result.stderr) > 1024 * 1024:
        raise ValueError("decoder exceeded diagnostic limit")
    timestamp = _decoded_ms(result.stderr, stream_start)
    pixels = [list(result.stdout[row * 32:(row + 1) * 32]) for row in range(32)]
    return timestamp, perceptual_hash(pixels)


def hash_video_candidates(video_path: str, plan: PlanningResult,
                          config: FrameSelectionConfig | None = None, *,
                          max_frames: int = 256, timeout_seconds: float = 10) -> list[FrameSample]:
    """Decode and hash candidate thumbnails within one total wall-clock budget.

    A mismatching SHA-256 or invalid/oversized plan is a hard ValueError before
    decoding. Missing files, tools, timing, or individual decode failures become
    UNAVAILABLE samples. An exhausted total timeout marks the remaining frames
    unavailable. Source time zero is the selected video stream's start PTS;
    input seeking uses absolute timestamps so nonzero/negative starts are explicit.
    """
    if type(max_frames) is not int or not 1 <= max_frames <= MAX_DECODE_FRAMES:
        raise ValueError(f"max_frames must be an integer between 1 and {MAX_DECODE_FRAMES}")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be a finite positive number")
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be greater than zero and at most {MAX_TIMEOUT_SECONDS}")
    plan = PlanningResult.model_validate(plan.model_dump())
    config = FrameSelectionConfig.model_validate(config.model_dump()) if config else FrameSelectionConfig()
    candidates = generate_candidates(plan, config)
    if len(candidates) > max_frames:
        raise ValueError("candidate count exceeds max_frames; no partial decoding started")
    deadline = time.monotonic() + timeout_seconds
    path = Path(video_path).expanduser().resolve()
    try:
        if not path.is_file():
            raise OSError("local source video file is missing")
        verified_stat = path.stat()
        actual_hash = _file_hash(path, deadline)
    except (OSError, TimeoutError) as exc:
        return [_unavailable(c, str(exc) if isinstance(exc, TimeoutError) else "local source video file is unavailable")
                for c in candidates]
    if actual_hash != plan.sourceIndex.assetRef.assetHash:
        raise ValueError("source video SHA-256 does not match the planning assetHash")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        return [_unavailable(c, "ffmpeg and ffprobe are required for verified frame decoding") for c in candidates]
    try:
        stream_start = _probe_start(ffprobe, path, deadline)
    except (OSError, ValueError, TimeoutError, subprocess.SubprocessError):
        return [_unavailable(c, "video stream timing probe failed or total time budget exhausted") for c in candidates]
    windows = {w.windowId: w for w in plan.windows}
    scenes = {s.sceneId: s for s in plan.sourceIndex.scenes}
    samples = []
    for candidate in candidates:
        try:
            current = path.stat()
            if (current.st_size, current.st_mtime_ns, current.st_ino) != (
                    verified_stat.st_size, verified_stat.st_mtime_ns, verified_stat.st_ino):
                raise ValueError("source video changed after SHA-256 verification")
            timestamp, phash = _decode(ffmpeg, path, candidate, stream_start, deadline)
            scene, window = scenes[candidate.sceneId], windows[candidate.windowId]
            if not (scene.sourceRange.startMs <= timestamp < scene.sourceRange.endMs
                    and window.startMs <= timestamp < window.endMs):
                raise ValueError("decoded frame falls outside candidate scene or primary window")
            if abs(timestamp - candidate.timestampMs) > config.maxTimestampDriftMs:
                raise ValueError("decoded frame exceeds configured timestamp drift tolerance")
            samples.append(FrameSample(frameId=candidate.frameId, assetHash=candidate.assetHash,
                decodedTimestampMs=timestamp, perceptualHash=phash,
                source=Provenance(mode="REAL", provider="ffmpeg", model=DECODER_VERSION,
                                  reason="Source SHA-256 verified; timestamp from decoded frame PTS")))
        except (OSError, ValueError, TimeoutError, subprocess.SubprocessError) as exc:
            reason = str(exc) if isinstance(exc, (ValueError, TimeoutError)) else "frame decoding failed or timed out"
            samples.append(_unavailable(candidate, reason))
    return samples
