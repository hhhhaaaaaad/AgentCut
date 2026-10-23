"""Bounded local PCM decoding and WebRTC VAD; no settings or ASR clients."""

from decimal import Decimal
from fractions import Fraction
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Annotated, Literal
import wave

from pydantic import Field

from app.analysis.audio_track import VadObservation
from app.analysis.source_index import DetectorIdentity, planning_hash
from app.schemas.script_contracts_v1 import AssetRef, Contract, Provenance, Range


EXTRACTOR_VERSION = "video-pcm16k-0.1"


class VadConfig(Contract):
    frameMs: Literal[10, 20, 30] = 30
    aggressiveness: Annotated[int, Field(strict=True, ge=0, le=3)] = 2
    maxDurationMs: Annotated[int, Field(strict=True, ge=1, le=1800000)] = 600000
    timeoutSeconds: float = Field(default=30.0, gt=0, le=120, allow_inf_nan=False)


def _identity(config: VadConfig) -> DetectorIdentity:
    try:
        backend_version = version("webrtcvad-wheels")
    except PackageNotFoundError:
        backend_version = "unavailable"
    return DetectorIdentity(name="webrtcvad", version=backend_version,
        settingsHash=planning_hash({"frameMs": config.frameMs, "aggressiveness": config.aggressiveness,
            "extractorVersion": EXTRACTOR_VERSION, "finalFrame": "zero-pad-to-frame-size"}))


def _unavailable(asset: AssetRef, config: VadConfig, reason: str) -> VadObservation:
    return VadObservation(assetRef=asset, detector=_identity(config),
        source=Provenance(mode="UNAVAILABLE", provider="local-audio", model=EXTRACTOR_VERSION, reason=reason),
        audioPresent=None, reliable=False, analyzedRanges=[], speechRanges=[])


def _remaining(deadline: float) -> float:
    result = deadline - time.monotonic()
    if result <= 0:
        raise TimeoutError("local audio time budget exhausted")
    return result


def _verified_path(video_path: str, asset: AssetRef, deadline: float) -> Path:
    path = Path(video_path.removeprefix("file://")).expanduser().resolve()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            _remaining(deadline)
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    if "sha256:" + digest.hexdigest() != asset.assetHash:
        raise ValueError("source audio/video bytes do not match assetHash")
    return path


def _make_vad(config: VadConfig):
    import webrtcvad

    return webrtcvad.Vad(config.aggressiveness)


def _observe_pcm_wav(path: Path, asset: AssetRef, config: VadConfig, deadline: float) -> VadObservation:
    try:
        vad = _make_vad(config)
    except Exception:
        return _unavailable(asset, config, "WebRTC VAD backend is unavailable")
    processed, active, speech, stopped = 0, None, [], False
    try:
        with wave.open(str(path), "rb") as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getcomptype()) != (16000, 1, 2, "NONE"):
                return _unavailable(asset, config, "VAD requires uncompressed 16kHz mono PCM16 WAV")
            if audio.getnframes() != asset.durationMs * 16:
                return _unavailable(asset, config, "PCM frame count differs from the source timeline duration")
            frame_samples = 16 * config.frameMs
            while processed < audio.getnframes():
                try:
                    _remaining(deadline)
                    actual_samples = min(frame_samples, audio.getnframes() - processed)
                    raw = audio.readframes(actual_samples)
                    if len(raw) != actual_samples * 2:
                        raise ValueError("truncated PCM samples")
                    # The final partial frame is classified with zero padding;
                    # only actual source samples enter coverage/timestamps.
                    voiced = vad.is_speech(raw.ljust(frame_samples * 2, b"\0"), 16000)
                    if type(voiced) is not bool:
                        raise ValueError("invalid VAD frame result")
                except Exception:
                    stopped = True
                    break
                start_ms = processed // 16
                if voiced and active is None:
                    active = start_ms
                if not voiced and active is not None:
                    speech.append(Range(startMs=active, endMs=start_ms))
                    active = None
                processed += actual_samples
    except (OSError, EOFError, wave.Error):
        return _unavailable(asset, config, "PCM WAV cannot be read")
    end_ms = processed // 16
    if active is not None and active < end_ms:
        speech.append(Range(startMs=active, endMs=end_ms))
    if not end_ms:
        return _unavailable(asset, config, "No PCM frames were successfully classified")
    return VadObservation(assetRef=asset, detector=_identity(config),
        source=Provenance(mode="REAL", provider="webrtcvad", model=_identity(config).version,
                          reason="VAD stopped before completing source coverage" if stopped else None),
        audioPresent=True, reliable=True, analyzedRanges=[Range(startMs=0, endMs=end_ms)], speechRanges=speech)


def _config(asset: AssetRef, config: VadConfig | None) -> VadConfig:
    config = VadConfig.model_validate(config.model_dump()) if config else VadConfig()
    if asset.durationMs > config.maxDurationMs:
        raise ValueError("source duration exceeds configured local audio limit")
    return config


def detect_wav_audio(wav_path: str, asset: AssetRef, config: VadConfig | None = None) -> VadObservation:
    """For a WAV source asset itself: verify bytes before classifying frames."""
    asset = AssetRef.model_validate(asset.model_dump())
    config = _config(asset, config)
    deadline = time.monotonic() + config.timeoutSeconds
    try:
        path = _verified_path(wav_path, asset, deadline)
        verified_stat = path.stat()
    except (OSError, TimeoutError):
        return _unavailable(asset, config, "WAV source is unavailable or the time budget expired")
    result = _observe_pcm_wav(path, asset, config, deadline)
    try:
        current = path.stat()
        if (current.st_size, current.st_mtime_ns, current.st_ino) == (verified_stat.st_size, verified_stat.st_mtime_ns, verified_stat.st_ino):
            return result
    except OSError:
        pass
    return _unavailable(asset, config, "WAV source changed after hash verification")


def _run(args: list[str], deadline: float):
    return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                          timeout=_remaining(deadline), check=False)


def _video_start(stream: dict) -> Fraction:
    if type(stream.get("start_pts")) is int and stream.get("time_base"):
        base = Fraction(stream["time_base"])
        if base <= 0:
            raise ValueError("invalid video time base")
        return stream["start_pts"] * base
    value = Decimal(stream["start_time"])
    if not value.is_finite():
        raise ValueError("invalid video start timestamp")
    return Fraction(value)


def _video_duration_ms(stream: dict) -> int:
    if type(stream.get("duration_ts")) is int and stream.get("time_base"):
        duration = stream["duration_ts"] * Fraction(stream["time_base"])
    else:
        value = Decimal(stream["duration"])
        if not value.is_finite():
            raise ValueError("invalid video duration")
        duration = Fraction(value)
    if duration <= 0:
        raise ValueError("video duration must be positive")
    ms = duration * 1000
    return (2 * ms.numerator + ms.denominator) // (2 * ms.denominator)


def detect_video_audio(video_path: str, asset: AssetRef, config: VadConfig | None = None) -> VadObservation:
    """Align audio to video-stream time zero, then classify a bounded PCM WAV.

    Source audio offsets are preserved by -copyts/asetpts; resampling pads or
    trims samples around video zero. Missing audio is explicit probe evidence.
    """
    asset = AssetRef.model_validate(asset.model_dump())
    config = _config(asset, config)
    deadline = time.monotonic() + config.timeoutSeconds
    try:
        path = _verified_path(video_path, asset, deadline)
        verified_stat = path.stat()
    except (OSError, TimeoutError):
        return _unavailable(asset, config, "Source video is unavailable or the time budget expired")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffprobe:
        return _unavailable(asset, config, "ffprobe is unavailable")
    try:
        probe = _run([ffprobe, "-v", "error", "-show_entries",
            "stream=index,codec_type,start_pts,time_base,start_time,duration_ts,duration", "-of", "json", str(path)], deadline)
        if probe.returncode != 0 or len(probe.stdout) > 131072:
            raise ValueError("source audio metadata probe failed")
        streams = json.loads(probe.stdout)["streams"]
        if not isinstance(streams, list) or not all(isinstance(s, dict) for s in streams):
            raise ValueError("invalid source stream metadata")
        video = next(s for s in streams if s.get("codec_type") == "video")
        if _video_duration_ms(video) != asset.durationMs:
            return _unavailable(asset, config, "Source video duration differs from the planning asset")
        if not any(s.get("codec_type") == "audio" for s in streams):
            return VadObservation(assetRef=asset,
                detector=DetectorIdentity(name="ffprobe.no-audio", version=EXTRACTOR_VERSION, settingsHash=planning_hash({})),
                source=Provenance(mode="REAL", provider="ffprobe", model=EXTRACTOR_VERSION,
                                  reason="Verified source has no audio stream"),
                audioPresent=False, reliable=True, analyzedRanges=[Range(startMs=0, endMs=asset.durationMs)], speechRanges=[])
        if not ffmpeg:
            return _unavailable(asset, config, "ffmpeg is unavailable")
        origin = _video_start(video)
        with tempfile.TemporaryDirectory(prefix="agentcut_audio_") as directory:
            output = Path(directory) / "source.wav"
            filters = (f"asetpts=PTS-({origin.numerator}/{origin.denominator})/TB,"
                       f"aresample=16000:async=1:first_pts=0,apad,atrim=end_sample={asset.durationMs * 16}")
            decoded = _run([ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-copyts", "-threads", "1",
                "-i", str(path), "-map", "0:a:0", "-vn", "-sn", "-dn", "-filter_threads", "1",
                "-af", filters, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output)], deadline)
            if decoded.returncode != 0:
                raise ValueError("PCM source decoding failed")
            current = path.stat()
            if (current.st_size, current.st_mtime_ns, current.st_ino) != (verified_stat.st_size, verified_stat.st_mtime_ns, verified_stat.st_ino):
                return _unavailable(asset, config, "Source video changed after hash verification")
            return _observe_pcm_wav(output, asset, config, deadline)
    except (OSError, ValueError, ArithmeticError, KeyError, TypeError, StopIteration, TimeoutError, subprocess.SubprocessError):
        return _unavailable(asset, config, "Audio probe/decoding failed or the time budget expired")
