"""Offline VAD/ASR contracts; REAL observations below are explicit test doubles."""

import asyncio
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.analysis.asr_track import (
    AsrChunkResult, AsrExecutionPolicy, AsrTrack, assemble_asr_track, failed_chunk, run_asr,
)
from app.analysis.audio_track import (
    AudioChunkPolicy, AudioPlan, VadObservation, coverage_ms, overlap_ranges, plan_audio, silence_cues,
)
from app.analysis.source_index import DetectorIdentity, build_source_index, planning_hash
from app.analysis.window_planner import ProfileConfig, plan_windows
from app.schemas.analysis_evidence_v1 import TranscriptSegmentV1
from app.schemas.script_contracts_v1 import AssetRef, Provenance, Range


REAL = Provenance(mode="REAL", provider="test-double", model="test-1", reason=None)
SIMULATED = REAL.model_copy(update={"mode": "SIMULATED", "reason": "offline fixture"})
UNAVAILABLE = REAL.model_copy(update={"mode": "UNAVAILABLE", "reason": "not observed"})
DETECTOR = DetectorIdentity(name="test-vad", version="1", settingsHash=planning_hash({}))


def observation(duration=140000, speech=((55000, 95000),), *, source=REAL, analyzed=None,
                present=True, reliable=None):
    asset = AssetRef(assetId="audio_test", assetHash="sha256:" + "a" * 64,
                     durationMs=duration, displayName="offline-source.mp4")
    return VadObservation(assetRef=asset, detector=DETECTOR, source=source, audioPresent=present,
        reliable=(source.mode == "REAL") if reliable is None else reliable,
        analyzedRanges=[Range(startMs=a, endMs=b) for a, b in (analyzed if analyzed is not None else [(0, duration)])],
        speechRanges=[Range(startMs=a, endMs=b) for a, b in speech])


def visual(vad, config_version="visual-1"):
    index = build_source_index(vad.assetRef, [], DETECTOR, REAL, no_cuts=True)
    return plan_windows(index, ProfileConfig(requestedType="TUTORIAL_INTERVIEW", configVersion=config_version))


def successful(plan, *, source=REAL):
    return [AsrChunkResult(chunkId=c.chunkId, assetHash=c.assetHash, status="SUCCESS",
                           text=f"Original block {i}", source=source, error=None) for i, c in enumerate(plan.chunks)]


@pytest.mark.parametrize("duration", [1, 29000, 30000, 30001, 95000, 1800000])
@pytest.mark.parametrize("overlap", [0, 500, 1000])
def test_chunks_cover_all_speech_with_requests_at_most_thirty_seconds(duration, overlap):
    vad = observation(duration, [(0, duration)])
    plan = plan_audio(vad, AudioChunkPolicy(overlapMs=overlap))
    assert plan.chunks[0].sourceRange.startMs == plan.chunks[0].requestRange.startMs == 0
    assert plan.chunks[-1].sourceRange.endMs == plan.chunks[-1].requestRange.endMs == duration
    assert sum(c.sourceRange.endMs - c.sourceRange.startMs for c in plan.chunks) == duration
    assert all(a.sourceRange.endMs == b.sourceRange.startMs for a, b in zip(plan.chunks, plan.chunks[1:]))
    for chunk in plan.chunks:
        assert chunk.requestRange.startMs <= chunk.sourceRange.startMs < chunk.sourceRange.endMs <= chunk.requestRange.endMs
        assert chunk.requestRange.endMs - chunk.requestRange.startMs <= 30000
    assert AudioPlan.model_validate_json(plan.model_dump_json()) == plan


def test_nearby_voice_merges_but_known_long_silence_does_not():
    vad = observation(10000, [(100, 500), (1000, 1500), (5000, 6000)])
    plan = plan_audio(vad)
    assert [(c.sourceRange.startMs, c.sourceRange.endMs) for c in plan.chunks] == [(100, 1500), (5000, 6000)]
    assert plan.speechMs == 1900
    assert [(r.startMs, r.endMs) for r in plan.silenceRanges] == [(0, 100), (500, 1000), (1500, 5000), (6000, 10000)]


def test_thirty_second_utterance_needs_only_one_request_with_clipped_overlap():
    audio = plan_audio(observation(30000, [(0, 30000)]))
    assert len(audio.chunks) == 1
    assert audio.chunks[0].requestRange == Range(startMs=0, endMs=30000)


def test_vad_unknown_gap_is_never_merged_or_declared_silent():
    vad = observation(3000, [(0, 1000), (1500, 2000)], analyzed=[(0, 1000), (1500, 3000)])
    plan = plan_audio(vad)
    assert len(plan.chunks) == 2
    assert plan.unknownRanges == [Range(startMs=1000, endMs=1500)]
    assert plan.silenceRanges == [Range(startMs=2000, endMs=3000)]
    assert all(not (c.sourceRange.startMs < 1500 and c.sourceRange.endMs > 1000) for c in plan.chunks)


def test_no_speech_requires_complete_reliable_vad_and_is_not_a_missing_backend():
    real = plan_audio(observation(1000, []))
    fake = plan_audio(observation(1000, [], source=SIMULATED))
    partial = plan_audio(observation(1000, [], analyzed=[(0, 500)]))
    missing = plan_audio(observation(1000, [], analyzed=[], source=UNAVAILABLE, present=None))
    assert real.status == "NO_SPEECH" and real.chunks == []
    assert fake.status == partial.status == "PLANNED"
    assert missing.status == "UNAVAILABLE" and missing.unknownRanges == [Range(startMs=0, endMs=1000)]
    assert silence_cues(fake) == silence_cues(missing) == []
    assert silence_cues(real)[0].sourceRange == Range(startMs=0, endMs=1000)


def test_verified_no_audio_is_full_metadata_coverage_without_chunks():
    vad = observation(1000, [], present=False)
    audio = plan_audio(vad)
    track = assemble_asr_track(audio, visual(vad), [])
    assert track.status == "NO_SPEECH"
    assert track.transcripts == [] and track.windowLinks[0].status == "NO_SPEECH"


@pytest.mark.parametrize("changes", [
    {"speech": [(100, 100)]}, {"speech": [(500, 400)]}, {"speech": [(0, 1001)]},
    {"speech": [(0, 700), (600, 900)]}, {"speech": [(700, 800), (100, 200)]},
    {"speech": [(0, 1000)], "analyzed": [(0, 500)]},
    {"speech": [], "analyzed": [], "source": REAL},
    {"speech": [], "source": SIMULATED, "reliable": True},
    {"speech": [], "source": UNAVAILABLE, "present": None},
    {"speech": [(0, 100)], "present": False},
])
def test_invalid_vad_ranges_and_contradictory_sources_are_rejected(changes):
    with pytest.raises(ValidationError):
        observation(1000, **changes)


def test_audio_id_is_stable_across_visual_window_configs_and_changes_with_audio_policy():
    vad = observation()
    first = plan_audio(vad)
    assert first == plan_audio(vad)
    assert visual(vad, "a").windows[0].windowId != visual(vad, "b").windows[0].windowId
    assert first.chunks == plan_audio(vad).chunks
    assert first.planId != plan_audio(vad, AudioChunkPolicy(configVersion="other")).planId


def test_oversized_audio_plans_fail_before_allocating_chunks():
    with pytest.raises(ValueError, match="maxChunks"):
        plan_audio(observation(9007199254740991, [(0, 9007199254740991)]))


@pytest.mark.parametrize("change", [
    lambda d: d.update(observedMs=1), lambda d: d.update(status="NO_SPEECH"),
    lambda d: d["chunks"][0].update(chunkId="forged"),
    lambda d: d["chunks"][0]["requestRange"].update(endMs=140000),
    lambda d: d.update(silenceRanges=[]),
])
def test_persisted_audio_plan_rejects_tampering(change):
    data = plan_audio(observation()).model_dump()
    change(data)
    with pytest.raises(ValidationError):
        AudioPlan.model_validate(data)


def test_cross_window_asr_preserves_one_original_block_and_global_time():
    vad = observation(140000, [(55000, 65000)])
    audio = plan_audio(vad)
    track = assemble_asr_track(audio, visual(vad), successful(audio))
    assert track.status == "COMPLETE" and track.missingSpeechMs == 0
    assert len(track.transcripts) == 1
    transcript = track.transcripts[0]
    assert (transcript.startMs, transcript.endMs, transcript.timingQuality) == (55000, 65000, "COARSE_BLOCK")
    assert [w.transcriptRefs for w in track.windowLinks] == [[transcript.transcriptId], [transcript.transcriptId], []]
    assert [w.transcribedSpeechMs for w in track.windowLinks] == [5000, 5000, 0]
    assert track.windowLinks[-1].status == "NO_SPEECH"
    assert TranscriptSegmentV1.model_validate(transcript.model_dump()) == transcript


def test_overlap_coverage_uses_union_and_original_text_records_remain_intact():
    vad = observation(140000, [(0, 95000)])
    audio = plan_audio(vad)
    results = successful(audio)
    results[0] = results[0].model_copy(update={"text": "Intro: shared phrase boundary"})
    results[1] = results[1].model_copy(update={"text": "shared phrase boundary continued"})
    track = assemble_asr_track(audio, visual(vad), results)
    assert track.transcribedSpeechMs == 95000
    assert sum(t.endMs - t.startMs for t in track.transcripts) > 95000
    assert track.transcripts[1].text == "shared phrase boundary continued"
    assert track.textJoins[1].removedPrefix == "shared phrase boundary"
    assert track.textJoins[1].displayText == " continued"
    assert track.textJoins[1].overlapWith == track.transcripts[0].transcriptId
    assert track.transcripts[1].startMs == audio.chunks[1].requestRange.startMs


def test_identical_text_is_not_deduped_without_temporal_overlap():
    vad = observation(60000, [(0, 60000)])
    audio = plan_audio(vad, AudioChunkPolicy(overlapMs=0))
    results = [r.model_copy(update={"text": "Repeated intentional sentence."}) for r in successful(audio)]
    track = assemble_asr_track(audio, visual(vad), results)
    assert all(not j.removedPrefix for j in track.textJoins)


def test_missing_chunk_retains_successes_and_explicit_failed_speech_coverage():
    vad = observation(140000, [(0, 140000)])
    audio = plan_audio(vad)
    supplied = successful(audio)
    missing = audio.chunks[3]
    track = assemble_asr_track(audio, visual(vad), [r for r in supplied if r.chunkId != missing.chunkId])
    assert track.status == "PARTIAL" and len(track.transcripts) == len(audio.chunks) - 1
    assert track.chunkResults[3].error.code == "MISSING_RESULT"
    assert track.missingSpeechMs > 0
    assert track.windowLinks[0].status == "COMPLETE"
    assert track.windowLinks[1].failedChunkRefs == [missing.chunkId]


def test_explicit_no_speech_response_does_not_erase_positive_vad_evidence():
    vad = observation(1000, [(0, 1000)])
    audio = plan_audio(vad)
    chunk = audio.chunks[0]
    source = REAL.model_copy(update={"mode": "NO_SPEECH", "reason": "recognizer explicitly reported no recognizable speech"})
    result = AsrChunkResult(chunkId=chunk.chunkId, assetHash=chunk.assetHash, status="NO_SPEECH", text="", source=source, error=None)
    track = assemble_asr_track(audio, visual(vad), [result])
    assert track.status == "PARTIAL" and track.transcripts == []
    assert track.missingSpeechMs == 1000 and "VAD_ASR_DISAGREEMENT" in track.reviewReasons


def test_simulated_asr_is_not_real_speech_coverage():
    vad = observation(1000, [(0, 1000)])
    audio = plan_audio(vad)
    track = assemble_asr_track(audio, visual(vad), successful(audio, source=SIMULATED))
    assert track.status == "PARTIAL" and track.transcribedSpeechMs == 0
    assert track.transcripts[0].source.mode == "SIMULATED"


@pytest.mark.parametrize("kind", ["unknown", "duplicate", "hash", "asset"])
def test_foreign_or_duplicate_asr_results_are_rejected(kind):
    vad = observation()
    audio, windows = plan_audio(vad), visual(vad)
    results = successful(audio)
    if kind == "unknown": results[0] = results[0].model_copy(update={"chunkId": "unknown"})
    if kind == "duplicate": results.append(results[0])
    if kind == "hash": results[0] = results[0].model_copy(update={"assetHash": "sha256:" + "b" * 64})
    if kind == "asset": windows.sourceIndex.assetRef.displayName = "different asset snapshot"
    with pytest.raises(ValueError):
        assemble_asr_track(audio, windows, results)


@pytest.mark.parametrize("change", [{"text": ""}, {"text": "  "}, {"source": UNAVAILABLE},
                                    {"status": "NO_SPEECH", "text": ""}, {"startMs": 0}])
def test_asr_cannot_supply_free_times_empty_success_or_false_provenance(change):
    audio = plan_audio(observation())
    data = successful(audio)[0].model_dump()
    data.update(change)
    with pytest.raises(ValidationError):
        AsrChunkResult.model_validate(data)


def test_replay_is_stable_and_does_not_mutate_evidence():
    vad = observation()
    audio, windows = plan_audio(vad), visual(vad)
    results = successful(audio)
    before = copy.deepcopy((audio.model_dump(), windows.model_dump(), [r.model_dump() for r in results]))
    first = assemble_asr_track(audio, windows, results)
    assert first == assemble_asr_track(audio, windows, list(reversed(results)))
    assert before == (audio.model_dump(), windows.model_dump(), [r.model_dump() for r in results])
    assert AsrTrack.model_validate_json(first.model_dump_json()) == first


@pytest.mark.parametrize("change", [
    lambda d: d.update(transcribedSpeechMs=1), lambda d: d.update(trackId="forged"),
    lambda d: d["transcripts"][0].update(startMs=0),
    lambda d: d["transcripts"][0].update(timingQuality="SENTENCE"),
    lambda d: d["windowLinks"][0].update(transcriptRefs=["foreign"]),
    lambda d: d["textJoins"][0].update(displayText="invented"),
])
def test_persisted_asr_track_rejects_forged_time_text_refs_and_coverage(change):
    vad = observation()
    audio = plan_audio(vad)
    data = assemble_asr_track(audio, visual(vad), successful(audio)).model_dump()
    change(data)
    with pytest.raises(ValidationError):
        AsrTrack.model_validate(data)


def test_async_adapter_is_bounded_and_out_of_order_failures_keep_successes():
    vad = observation(140000, [(0, 140000)])
    audio = plan_audio(vad)

    class Adapter:
        active = 0
        maximum = 0

        async def transcribe(self, chunk):
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            try:
                await asyncio.sleep(.005 if chunk.chunkId == audio.chunks[0].chunkId else .001)
                if chunk.chunkId == audio.chunks[1].chunkId:
                    raise RuntimeError("test adapter failure")
                return AsrChunkResult(chunkId=chunk.chunkId, assetHash=chunk.assetHash, status="SUCCESS", text="Original text", source=REAL, error=None)
            finally:
                self.active -= 1

    adapter = Adapter()
    results = asyncio.run(run_asr(audio, adapter))
    assert adapter.maximum == 2
    assert [r.chunkId for r in results] == [c.chunkId for c in audio.chunks]
    assert results[1].status == "FAILED" and results[1].error.code == "ADAPTER_ERROR"
    assert all(r.status == "SUCCESS" for i, r in enumerate(results) if i != 1)


@pytest.mark.parametrize("behavior", ["timeout", "late", "foreign"])
def test_adapter_timeout_late_and_foreign_results_never_publish_success(behavior):
    audio = plan_audio(observation(1000, [(0, 1000)]))

    class Adapter:
        async def transcribe(self, chunk):
            if behavior in {"timeout", "late"}:
                try:
                    await asyncio.sleep(.05)
                except asyncio.CancelledError:
                    if behavior == "timeout": raise
                    await asyncio.sleep(.005)
            return AsrChunkResult(chunkId="foreign" if behavior == "foreign" else chunk.chunkId,
                assetHash=chunk.assetHash, status="SUCCESS", text="Late text", source=REAL, error=None)

    timeout = .5 if behavior == "foreign" else .001
    results = asyncio.run(run_asr(audio, Adapter(), AsrExecutionPolicy(timeoutSeconds=timeout)))
    assert results[0].status == "FAILED"
    assert results[0].error.code == ("INVALID_RESPONSE" if behavior == "foreign" else "TIMEOUT")


def test_confirmed_no_speech_never_calls_adapter():
    audio = plan_audio(observation(1000, []))

    class Adapter:
        async def transcribe(self, chunk):
            raise AssertionError("quiet audio must not invoke ASR")

    assert asyncio.run(run_asr(audio, Adapter())) == []


def test_explicit_recovery_reuses_successes_and_only_runs_failed_or_missing_chunks():
    vad = observation(140000, [(0, 140000)])
    audio, windows = plan_audio(vad), visual(vad)
    original = successful(audio)
    original[1] = failed_chunk(audio.chunks[1], "TIMEOUT", "prior call timed out", retryable=True)
    partial = assemble_asr_track(audio, windows, original[:-1])
    calls = []

    class Adapter:
        async def transcribe(self, chunk):
            calls.append(chunk.chunkId)
            return AsrChunkResult(chunkId=chunk.chunkId, assetHash=chunk.assetHash, status="SUCCESS", text="Recovered original block", source=REAL, error=None)

    restored = asyncio.run(run_asr(audio, Adapter(), existing_results=partial.chunkResults))
    track = assemble_asr_track(audio, windows, restored)
    assert calls == [audio.chunks[1].chunkId, audio.chunks[-1].chunkId]
    assert partial.status == "PARTIAL" and track.status == "COMPLETE"
    assert track.transcripts[0] == partial.transcripts[0]
    assert restored[0] == original[0]
    assert track.trackId != partial.trackId
    assert asyncio.run(run_asr(audio, Adapter(), existing_results=restored)) == restored
    assert len(calls) == 2


@pytest.mark.parametrize("change", [{"chunkId": "old_plan_chunk"}, {"assetHash": "sha256:" + "b" * 64}])
def test_recovery_rejects_prior_results_from_other_asset_or_plan(change):
    audio = plan_audio(observation())
    prior = successful(audio)
    prior[0] = prior[0].model_copy(update=change)

    class Adapter:
        async def transcribe(self, chunk):
            raise AssertionError("invalid recovery must not call the recognizer")

    with pytest.raises(ValueError):
        asyncio.run(run_asr(audio, Adapter(), existing_results=prior))


def test_offline_audio_cli_replays_simulation_failure_and_cross_window_refs(tmp_path):
    from app.analysis.offline_audio_track import OfflineAudioInput, replay_audio
    from app.analysis.window_planner import PlanningResult

    contracts = Path(__file__).resolve().parents[2] / "docs" / "contracts"
    request = OfflineAudioInput.model_validate_json((contracts / "offline-audio-track.input.json").read_text())
    windows = PlanningResult.model_validate_json((contracts / "offline-window-planning.output.json").read_text())
    expected = replay_audio(windows, request)
    assert expected.status == "PARTIAL" and len(expected.transcripts) == 2
    assert expected.transcribedSpeechMs == 0 and expected.missingSpeechMs == 46000
    assert expected.transcripts[0].source.mode == "SIMULATED"
    assert expected.windowLinks[0].transcriptRefs[0] == expected.windowLinks[1].transcriptRefs[0]
    output = tmp_path / "audio-track.json"
    completed = subprocess.run([sys.executable, "-m", "app.analysis.offline_audio_track",
        "--visual-plan", str(contracts / "offline-window-planning.output.json"),
        "--input", str(contracts / "offline-audio-track.input.json"), "--output", str(output)],
        capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout)["audioChunks"] == 3
    assert AsrTrack.model_validate_json(output.read_text()) == expected
    subprocess.run([sys.executable, "-c", "from app.analysis.offline_audio_track import OfflineAudioInput; "
        "import sys; assert 'app.config' not in sys.modules; assert 'openai' not in sys.modules; "
        "assert 'app.tools.audio_vad' not in sys.modules"], check=True)


@pytest.mark.parametrize("policy", [dict(maxChunkMs=30001), dict(maxChunkMs=1000, overlapMs=500),
                                    dict(mergeGapMs=1001), dict(maxChunks=0)])
def test_invalid_chunk_policy_is_rejected(policy):
    with pytest.raises(ValidationError):
        AudioChunkPolicy(**policy)
