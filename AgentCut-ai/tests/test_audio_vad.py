"""Local decoding/VAD boundaries, with fake subprocesses and synthetic PCM."""

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import wave

import pytest

from app.analysis.audio_track import plan_audio
from app.analysis.source_index import planning_hash
from app.schemas.script_contracts_v1 import AssetRef, Range
from app.tools import audio_vad


def source_ref(path, duration=1000):
    return AssetRef(assetId="wav_test", assetHash="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                    durationMs=duration, displayName=path.name)


def write_wav(path, duration=1000, *, rate=16000, channels=1, width=2, pcm=None):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(pcm if pcm is not None else b"\0" * (duration * rate // 1000 * channels * width))


@pytest.fixture
def fake_backend(monkeypatch):
    class Backend:
        flags = []
        count = 0
        lengths = []

        def is_speech(self, raw, rate):
            self.lengths.append(len(raw))
            flag = self.flags[self.count] if self.count < len(self.flags) else False
            self.count += 1
            if isinstance(flag, Exception): raise flag
            return flag

    backend = Backend()
    monkeypatch.setattr(audio_vad, "_make_vad", lambda config: backend)
    return backend


def test_vad_keeps_short_utterances_and_actual_tail_without_discarding_audio(tmp_path, fake_backend):
    path = tmp_path / "source.wav"
    write_wav(path, 95)
    fake_backend.flags = [True, False, True, True]
    result = audio_vad.detect_wav_audio(str(path), source_ref(path, 95))
    assert result.analyzedRanges == [Range(startMs=0, endMs=95)]
    assert result.speechRanges == [Range(startMs=0, endMs=30), Range(startMs=60, endMs=95)]
    assert fake_backend.lengths == [960] * 4
    assert result.reliable and result.audioPresent


def test_no_voice_requires_successful_full_pcm_analysis(tmp_path, fake_backend):
    path = tmp_path / "quiet.wav"
    write_wav(path)
    observed = audio_vad.detect_wav_audio(str(path), source_ref(path))
    assert plan_audio(observed).status == "NO_SPEECH"
    assert observed.source.mode == "REAL"


def test_backend_failure_preserves_prefix_and_marks_rest_unknown(tmp_path, fake_backend):
    path = tmp_path / "source.wav"
    write_wav(path, 120)
    fake_backend.flags = [True, False, RuntimeError("VAD failed")]
    result = audio_vad.detect_wav_audio(str(path), source_ref(path, 120))
    plan = plan_audio(result)
    assert result.analyzedRanges == [Range(startMs=0, endMs=60)]
    assert result.speechRanges == [Range(startMs=0, endMs=30)]
    assert plan.unknownRanges == [Range(startMs=60, endMs=120)]
    assert plan.silenceRanges == [Range(startMs=30, endMs=60)]


def test_missing_backend_and_failed_first_frame_never_mean_no_speech(tmp_path, fake_backend, monkeypatch):
    path = tmp_path / "source.wav"
    write_wav(path)
    fake_backend.flags = [RuntimeError("failed first frame")]
    assert plan_audio(audio_vad.detect_wav_audio(str(path), source_ref(path))).status == "UNAVAILABLE"

    def missing(_):
        raise ImportError("backend absent")

    monkeypatch.setattr(audio_vad, "_make_vad", missing)
    assert plan_audio(audio_vad.detect_wav_audio(str(path), source_ref(path))).status == "UNAVAILABLE"


@pytest.mark.parametrize("kwargs", [{"rate": 8000}, {"channels": 2}, {"width": 1}])
def test_incorrect_pcm_format_is_unavailable(tmp_path, fake_backend, kwargs):
    path = tmp_path / "source.wav"
    write_wav(path, **kwargs)
    result = audio_vad.detect_wav_audio(str(path), source_ref(path))
    assert result.source.mode == "UNAVAILABLE" and result.speechRanges == []


def test_audio_duration_mismatch_or_missing_file_does_not_fabricate_coverage(tmp_path, fake_backend):
    path = tmp_path / "source.wav"
    write_wav(path)
    assert audio_vad.detect_wav_audio(str(path), source_ref(path, 2000)).analyzedRanges == []
    ref = source_ref(path)
    assert audio_vad.detect_wav_audio(str(tmp_path / "missing.wav"), ref).analyzedRanges == []


def test_file_hash_mismatch_is_hard_error_before_any_backend_call(tmp_path, fake_backend):
    path = tmp_path / "source.wav"
    write_wav(path)
    ref = source_ref(path).model_copy(update={"assetHash": "sha256:" + "a" * 64})
    for detector in [audio_vad.detect_wav_audio, audio_vad.detect_video_audio]:
        with pytest.raises(ValueError, match="assetHash"):
            detector(str(path), ref)
    assert fake_backend.count == 0


def test_duration_cap_rejects_before_reading_source(tmp_path):
    path = tmp_path / "missing.wav"
    ref = AssetRef(assetId="large", assetHash="sha256:" + "a" * 64, durationMs=1800001, displayName="large")
    with pytest.raises(ValueError, match="duration"):
        audio_vad.detect_wav_audio(str(path), ref)


def test_video_without_audio_is_explicit_probe_evidence(tmp_path, monkeypatch):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"video-test-double")
    monkeypatch.setattr(audio_vad.shutil, "which", lambda name: "/test/" + name)
    metadata = {"streams": [{"codec_type": "video", "duration": "1.0"}]}
    monkeypatch.setattr(audio_vad, "_run", lambda *args: subprocess.CompletedProcess([], 0, json.dumps(metadata).encode(), b""))
    observed = audio_vad.detect_video_audio(str(path), source_ref(path))
    assert observed.audioPresent is False and observed.source.provider == "ffprobe"
    assert plan_audio(observed).status == "NO_SPEECH"


@pytest.mark.parametrize("origin", [Fraction(0), Fraction(5, 2), Fraction(-1, 2)])
def test_video_audio_alignment_uses_video_pts_origin_not_audio_start(tmp_path, monkeypatch, fake_backend, origin):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"video-test-double")
    monkeypatch.setattr(audio_vad.shutil, "which", lambda name: "/test/" + name)
    calls = []
    outputs = []

    def runner(args, deadline):
        calls.append(args)
        if "ffprobe" in args[0]:
            metadata = {"streams": [{"codec_type": "video", "start_pts": origin.numerator,
                                     "time_base": f"1/{origin.denominator}", "duration_ts": origin.denominator},
                                    {"codec_type": "audio", "start_time": "100"}]}
            return subprocess.CompletedProcess(args, 0, json.dumps(metadata).encode(), b"")
        output = Path(args[-1])
        outputs.append(output)
        write_wav(output)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(audio_vad, "_run", runner)
    result = audio_vad.detect_video_audio(str(path), source_ref(path))
    assert result.source.mode == "REAL" and plan_audio(result).status == "NO_SPEECH"
    command = calls[1]
    assert "-copyts" in command
    filters = command[command.index("-af") + 1]
    assert f"PTS-({origin.numerator}/{origin.denominator})/TB" in filters
    assert "first_pts=0" in filters and "atrim=end_sample=16000" in filters
    assert all(not output.exists() for output in outputs)


@pytest.mark.parametrize("metadata", [{}, {"streams": [1]}, {"streams": []},
    {"streams": [{"codec_type": "video"}]},
    {"streams": [{"codec_type": "video", "duration": "10"}]},
    {"streams": [{"codec_type": "video", "duration": "1", "start_time": "unknown"}, {"codec_type": "audio"}]}])
def test_bad_source_metadata_is_unavailable(tmp_path, monkeypatch, metadata):
    path = tmp_path / "source.mp4"
    path.write_bytes(b"video-test-double")
    monkeypatch.setattr(audio_vad.shutil, "which", lambda name: "/test/" + name)
    monkeypatch.setattr(audio_vad, "_run", lambda *args: subprocess.CompletedProcess([], 0, json.dumps(metadata).encode(), b""))
    observed = audio_vad.detect_video_audio(str(path), source_ref(path))
    assert plan_audio(observed).status == "UNAVAILABLE"


def test_real_webrtc_backend_on_synthetic_silence(tmp_path):
    pytest.importorskip("webrtcvad")
    path = tmp_path / "quiet.wav"
    write_wav(path, 1005)
    observed = audio_vad.detect_wav_audio(str(path), source_ref(path, 1005))
    assert observed.detector.version != "unavailable"
    assert observed.speechRanges == [] and observed.analyzedRanges == [Range(startMs=0, endMs=1005)]
    assert plan_audio(observed).status == "NO_SPEECH"
