"""Decoder tests use local bytes and subprocess doubles, never model clients."""

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from app.analysis.frame_selection import FrameSelectionConfig, generate_candidates
from app.analysis.source_index import DetectorIdentity, build_source_index
from app.analysis.window_planner import plan_windows
from app.schemas.script_contracts_v1 import AssetRef, Provenance, Range, canonical_hash
from app.tools import window_frames as decoder


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "a video.mp4"
    path.write_bytes(b"local source fixture, not a real encoded video")
    asset = AssetRef(assetId="asset_decoder", assetHash="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                     durationMs=10000, displayName=path.name)
    index = build_source_index(asset, [Range(startMs=0, endMs=5000), Range(startMs=5000, endMs=10000)],
        DetectorIdentity(name="fixture", version="1", settingsHash=canonical_hash({})),
        Provenance(mode="REAL", provider="test-double", model=None, reason=None))
    return path, plan_windows(index)


def completed(stdout=b"", stderr=b"", code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def frame(absolute_ms, *, pixels=None, time_base="1/1000", pts=None):
    log = (f"[Parsed_showinfo_2] config in time_base: {time_base}, frame_rate: 25/1\n"
           f"[Parsed_showinfo_2] n:   0 pts: {absolute_ms if pts is None else pts} pts_time:1 pos:1 fmt:gray\n").encode()
    return completed(bytes(range(256)) * 4 if pixels is None else pixels, log)


def install_runner(monkeypatch, *, stream=None, decode=None):
    calls = []
    stream = stream if stream is not None else {"start_pts": 7500, "time_base": "1/1000", "start_time": "7.5"}

    def run(args, timeout):
        calls.append((args, timeout))
        assert isinstance(args, list) and timeout > 0
        if "-show_entries" in args:
            return completed(json.dumps({"streams": [stream]}).encode())
        absolute_ms = round(Fraction(args[args.index("-ss") + 1]) * 1000)
        return decode(args, absolute_ms, len(calls) - 2) if decode else frame(absolute_ms)

    monkeypatch.setattr(decoder.shutil, "which", lambda binary: "/opt/homebrew/bin/" + binary)
    monkeypatch.setattr(decoder, "_run", run)
    return calls


def test_verified_file_and_nonzero_start_use_observed_global_timestamps(source, monkeypatch):
    path, plan = source
    calls = install_runner(monkeypatch, decode=lambda args, pts, i: frame(pts + 40))
    samples = decoder.hash_video_candidates(str(path), plan)
    candidates = generate_candidates(plan)
    assert len(samples) == len(candidates)
    assert all(s.source.mode == "REAL" for s in samples)
    assert [s.decodedTimestampMs for s in samples] == [c.timestampMs + 40 for c in candidates]
    assert all(len(s.perceptualHash) == 16 for s in samples)
    for args, _ in calls[1:]:
        assert args[args.index("-seek_timestamp") + 1] == "1"
        assert "-copyts" in args
        assert args[args.index("-frames:v") + 1] == "1"
        assert args[args.index("-vf") + 1] == "scale=32:32:flags=area,format=gray,showinfo"
        assert args[args.index("-i") + 1] == str(path.resolve())
    assert all(s.source.provider == "ffmpeg" for s in samples)
    assert len({s.perceptualHash for s in samples}) == 1


def test_file_sha256_mismatch_is_hard_failure_before_probe(source, monkeypatch):
    path, plan = source
    calls = install_runner(monkeypatch)
    path.write_bytes(b"changed source")
    with pytest.raises(ValueError, match="SHA-256"):
        decoder.hash_video_candidates(str(path), plan)
    assert calls == []


def test_max_frames_rejects_before_file_hash_or_process(source, monkeypatch):
    path, plan = source
    calls = install_runner(monkeypatch)
    monkeypatch.setattr(decoder, "_file_hash", lambda *args: pytest.fail("file hash started"))
    with pytest.raises(ValueError, match="candidate count"):
        decoder.hash_video_candidates(str(path), plan, max_frames=1)
    assert calls == []


@pytest.mark.parametrize("kwargs", [
    {"max_frames": True}, {"max_frames": 0}, {"max_frames": 1025}, {"max_frames": 1.5},
    {"timeout_seconds": True}, {"timeout_seconds": 0}, {"timeout_seconds": -1},
    {"timeout_seconds": float("nan")}, {"timeout_seconds": float("inf")},
    {"timeout_seconds": 121}, {"timeout_seconds": "10"},
])
def test_resource_limits_reject_invalid_values(source, kwargs):
    with pytest.raises(ValueError):
        decoder.hash_video_candidates(str(source[0]), source[1], **kwargs)


def assert_unavailable(samples):
    assert samples
    assert all(s.source.mode == "UNAVAILABLE" and s.source.reason for s in samples)
    assert all(s.decodedTimestampMs is None and s.perceptualHash is None for s in samples)


def test_missing_file_is_explicit_unavailable(source, monkeypatch):
    path, plan = source
    calls = install_runner(monkeypatch)
    assert_unavailable(decoder.hash_video_candidates(str(path.parent / "missing.mp4"), plan))
    assert calls == []


def test_missing_binary_is_explicit_unavailable(source, monkeypatch):
    path, plan = source
    calls = install_runner(monkeypatch)
    monkeypatch.setattr(decoder.shutil, "which", lambda name: None)
    assert_unavailable(decoder.hash_video_candidates(str(path), plan))
    assert calls == []


@pytest.mark.parametrize("result", [
    completed(code=1), completed(b"not-json"), completed(b'{"streams": []}'),
    completed(b'{"streams": [{"time_base": "1/1000"}]}'),
    completed(b'{"streams": [{"start_time": "NaN"}]}'),
    completed(b'{"streams": [{"start_pts": 0,"time_base": "1/0"}]}'),
    completed(b"x" * 65537),
])
def test_bad_or_missing_probe_timing_has_no_fabricated_samples(source, monkeypatch, result):
    path, plan = source
    install_runner(monkeypatch)
    monkeypatch.setattr(decoder, "_run", lambda args, timeout: result)
    assert_unavailable(decoder.hash_video_candidates(str(path), plan))


@pytest.mark.parametrize("result", [
    completed(code=1), completed(b"short"), completed(bytes(1024)),
    completed(bytes(1025), b"bad"), frame(1, time_base="1/0"),
    frame(1, time_base="0/1000"),
    completed(bytes(1024), frame(1).stderr + frame(1).stderr),
])
def test_decoder_errors_affect_one_candidate_and_preserve_other_successes(source, monkeypatch, result):
    path, plan = source
    install_runner(monkeypatch, decode=lambda args, pts, i: result if i == 0 else frame(pts))
    samples = decoder.hash_video_candidates(str(path), plan)
    assert_unavailable(samples[:1])
    assert all(s.source.mode == "REAL" for s in samples[1:])


def test_observed_frame_outside_requested_scene_is_rejected(source, monkeypatch):
    path, plan = source
    install_runner(monkeypatch, decode=lambda args, pts, i: frame(12500) if i == 0 else frame(pts))
    samples = decoder.hash_video_candidates(str(path), plan)
    assert_unavailable(samples[:1])
    assert "outside" in samples[0].source.reason
    assert all(s.source.mode == "REAL" for s in samples[1:])


def test_observed_frame_outside_primary_window_is_rejected(source, monkeypatch):
    path, plan = source
    install_runner(monkeypatch, decode=lambda args, pts, i: frame(17500) if i == 0 else frame(pts))
    samples = decoder.hash_video_candidates(str(path), plan)
    assert_unavailable(samples[:1])
    assert "outside" in samples[0].source.reason


def test_observed_frame_drift_uses_configured_tolerance(source, monkeypatch):
    path, plan = source
    install_runner(monkeypatch, decode=lambda args, pts, i: frame(pts + 100))
    samples = decoder.hash_video_candidates(str(path), plan, FrameSelectionConfig(maxTimestampDriftMs=50))
    assert_unavailable(samples)
    assert all("drift" in s.source.reason for s in samples)


def test_negative_start_offset_is_explicit_and_normalized(source, monkeypatch):
    path, plan = source
    calls = install_runner(monkeypatch, stream={"start_pts": -1000, "time_base": "1/1000"})
    samples = decoder.hash_video_candidates(str(path), plan)
    assert all(s.source.mode == "REAL" for s in samples)
    assert samples[0].decodedTimestampMs == generate_candidates(plan)[0].timestampMs
    assert Fraction(calls[1][0][calls[1][0].index("-ss") + 1]) < 0


def test_decimal_start_time_fallback_is_supported(source, monkeypatch):
    path, plan = source
    install_runner(monkeypatch, stream={"start_time": "7.5"})
    samples = decoder.hash_video_candidates(str(path), plan)
    assert [s.decodedTimestampMs for s in samples] == [c.timestampMs for c in generate_candidates(plan)]


def test_pts_conversion_uses_exact_time_base_and_rounds_half_up():
    assert decoder._decoded_ms(frame(0, time_base="1/2000", pts=1).stderr, Fraction(0)) == 1
    assert decoder._decoded_ms(frame(0, time_base="1/90000", pts=123456).stderr,
                               Fraction(12345, 90000)) == 1235
    with pytest.raises(ValueError, match="precedes"):
        decoder._decoded_ms(frame(-1).stderr, Fraction(0))


def test_process_timeout_is_per_candidate_and_does_not_discard_completed_samples(source, monkeypatch):
    path, plan = source

    def decode(args, pts, i):
        if i == 1:
            raise subprocess.TimeoutExpired(args, 1)
        return frame(pts)

    install_runner(monkeypatch, decode=decode)
    samples = decoder.hash_video_candidates(str(path), plan)
    assert samples[0].source.mode == "REAL"
    assert_unavailable(samples[1:2])
    assert all(s.source.mode == "REAL" for s in samples[2:])


def test_total_deadline_prevents_starting_more_subprocesses(source, monkeypatch):
    path, plan = source
    calls = install_runner(monkeypatch)
    remaining_calls = []

    def remaining(deadline):
        remaining_calls.append(deadline)
        # file hash reads twice, probe, first frame; then the total budget ends.
        if len(remaining_calls) > 4:
            raise TimeoutError("total decode time budget exhausted")
        return 1.0

    monkeypatch.setattr(decoder, "_remaining", remaining)
    samples = decoder.hash_video_candidates(str(path), plan)
    assert samples[0].source.mode == "REAL"
    assert_unavailable(samples[1:])
    assert len(calls) == 2


def test_file_mutation_after_hash_does_not_decode_unverified_bytes(source, monkeypatch):
    path, plan = source
    calls = install_runner(monkeypatch)
    original_probe = decoder._probe_start

    def probe(*args):
        result = original_probe(*args)
        path.write_bytes(b"mutated after source hash was verified")
        return result

    monkeypatch.setattr(decoder, "_probe_start", probe)
    samples = decoder.hash_video_candidates(str(path), plan)
    assert_unavailable(samples)
    assert all("changed" in s.source.reason for s in samples)
    assert len(calls) == 1


def test_subprocess_wrapper_uses_no_shell_and_finite_timeout(monkeypatch):
    observed = {}

    def run(args, **kwargs):
        observed.update(kwargs)
        return completed()

    monkeypatch.setattr(decoder.subprocess, "run", run)
    decoder._run(["ffmpeg", "-version"], 2.5)
    assert observed == {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
                        "stderr": subprocess.PIPE, "timeout": 2.5, "check": False}
