"""Offline source/window invariants; all detector observations here are test doubles."""

import copy
import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.analysis.offline_planning import plan_fixture
from app.analysis.source_index import DetectorIdentity, SourceIndex, build_source_index, seconds_to_ms
from app.analysis.window_planner import (
    PlanningResult, ProfileConfig, SilenceCue, WindowPolicy, plan_windows, resolve_profile,
)
from app.schemas.analysis_evidence_v1 import AnalysisWindow
from app.schemas.script_contracts_v1 import AssetRef, Provenance, Range, Scene, canonical_hash


REAL = Provenance(mode="REAL", provider="test-double", model=None, reason=None)
SIMULATED = REAL.model_copy(update={"mode": "SIMULATED"})
UNAVAILABLE = REAL.model_copy(update={"mode": "UNAVAILABLE", "reason": "test dependency missing"})
DETECTOR = DetectorIdentity(name="test-double", version="1", settingsHash=canonical_hash({"threshold": 27}))
FIXTURE = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "offline-window-planning.input.json"


def asset(duration=180000, **changes):
    return AssetRef(assetId="asset_test", assetHash="sha256:" + "a" * 64,
                    durationMs=duration, displayName="offline-test.mp4").model_copy(update=changes)


def index(duration=180000, cuts=(), source=REAL):
    points = [0, *cuts, duration]
    ranges = [Range(startMs=s, endMs=e) for s, e in zip(points, points[1:])]
    return build_source_index(asset(duration), ranges, DETECTOR, source)


def tutorial(**kwargs):
    return ProfileConfig(requestedType="TUTORIAL_INTERVIEW", **kwargs)


def cue(start, end, *, name="vad_1", reliable=True, source=REAL, asset_hash=None):
    return SilenceCue(cueId=name, assetHash=asset_hash or asset().assetHash,
                      sourceRange=Range(startMs=start, endMs=end), reliable=reliable, source=source)


def test_every_short_scene_is_preserved_beyond_legacy_frame_cap():
    source = index(12400, range(100, 12400, 100))
    assert len(source.scenes) == 124
    assert source.observedCoverageMs == source.indexedCoverageMs == 12400
    assert source.detectionStatus == "COMPLETE"
    assert all(s.sourceRange.endMs - s.sourceRange.startMs == 100 for s in source.scenes)
    assert all(Scene.model_validate(s.model_dump()) == s for s in source.contract_scenes())
    low = plan_windows(source, tutorial(frameBudgetCap=6))
    high = plan_windows(source, tutorial(frameBudgetCap=24))
    assert low.sourceIndex == high.sourceIndex == source
    assert len(low.windows[0].sceneIds) == 124
    assert low.profile.frameBudget == 6 < high.profile.frameBudget
    assert low.windows[0].windowId != high.windows[0].windowId


def test_scene_identity_is_stable_and_does_not_depend_on_array_position():
    first = index(3000, [1000, 2000])
    extended = index(3000, [500, 1000, 2000])
    assert first.scenes[1].sceneId == extended.scenes[2].sceneId
    assert index(3000, [1000, 2000]).model_dump() == first.model_dump()
    assert len({s.sceneId for s in first.scenes}) == 3


@pytest.mark.parametrize("change", [
    {"assetId": "other"}, {"assetHash": "sha256:" + "b" * 64},
])
def test_source_identity_binds_asset(change):
    first = index(3000)
    other = build_source_index(asset(3000, **change), [Range(startMs=0, endMs=3000)], DETECTOR, REAL)
    assert first.indexId != other.indexId
    assert first.scenes[0].sceneId != other.scenes[0].sceneId


def test_source_identity_binds_detector_settings():
    first = index(3000)
    other = build_source_index(asset(3000), [Range(startMs=0, endMs=3000)],
                               DETECTOR.model_copy(update={"settingsHash": canonical_hash({"threshold": 28})}), REAL)
    assert first.scenes[0].sceneId != other.scenes[0].sceneId


def test_detection_gaps_are_explicit_and_not_observed_coverage():
    source = build_source_index(asset(10000), [Range(startMs=1000, endMs=2000),
                                             Range(startMs=3000, endMs=9000)], DETECTOR, REAL)
    assert [s.origin for s in source.scenes] == ["UNOBSERVED", "DETECTED", "UNOBSERVED", "DETECTED", "UNOBSERVED"]
    assert source.indexedCoverageMs == 10000
    assert source.observedCoverageMs == 7000
    assert source.detectionStatus == "PARTIAL"
    plan = plan_windows(source)
    assert plan.plannedCoverageMs == 10000
    assert "provisional" in plan.profile.adjustmentReason


@pytest.mark.parametrize("source,status", [(REAL, "UNAVAILABLE"), (UNAVAILABLE, "UNAVAILABLE"), (SIMULATED, "UNAVAILABLE")])
def test_empty_detection_is_not_a_real_no_cut(source, status):
    result = build_source_index(asset(1000), [], DETECTOR, source)
    assert result.scenes[0].origin == "UNOBSERVED"
    assert result.detectionStatus == status
    assert result.observedCoverageMs == 0


def test_successful_no_cut_and_simulated_data_have_distinct_provenance():
    real = build_source_index(asset(1000), [], DETECTOR, REAL, no_cuts=True)
    fake = build_source_index(asset(1000), [], DETECTOR, SIMULATED, no_cuts=True)
    assert real.detectionStatus == "COMPLETE" and real.scenes[0].origin == "NO_CUT"
    assert fake.detectionStatus == "SIMULATED" and fake.observedCoverageMs == 0
    assert real.scenes[0].sceneId != fake.scenes[0].sceneId


@pytest.mark.parametrize("ranges", [
    [(1000, 2000), (500, 1000)], [(0, 2000), (1000, 3000)],
    [(1000, 1000)], [(2000, 1000)], [(0, 3001)],
])
def test_invalid_detector_ranges_are_rejected(ranges):
    with pytest.raises(ValueError):
        build_source_index(asset(3000), [Range(startMs=s, endMs=e) for s, e in ranges], DETECTOR, REAL)


@pytest.mark.parametrize("kwargs", [{"source": UNAVAILABLE, "no_cuts": True},
                                    {"source": UNAVAILABLE, "ranges": [Range(startMs=0, endMs=1000)]},
                                    {"ranges": [Range(startMs=0, endMs=1000)], "no_cuts": True}])
def test_contradictory_detector_result_is_rejected(kwargs):
    args = {"asset": asset(1000), "ranges": [], "detector": DETECTOR, "source": REAL}
    args.update(kwargs)
    with pytest.raises(ValueError):
        build_source_index(**args)


@pytest.mark.parametrize("value", ["1", True, -1, float("inf"), float("nan")])
def test_seconds_adapter_rejects_invalid_numbers(value):
    with pytest.raises(ValueError):
        seconds_to_ms(value)


def test_seconds_adapter_uses_one_explicit_rounding_rule():
    assert seconds_to_ms(Decimal("1.2345")) == 1235
    assert seconds_to_ms(1.2344) == 1234
    with pytest.raises(ValueError):
        build_source_index(asset(1000), [Range(startMs=seconds_to_ms(0), endMs=seconds_to_ms(.0001))], DETECTOR, REAL)


@pytest.mark.parametrize("value", [True, "1000", 1000.5, -1, 9007199254740992])
def test_millisecond_fields_reject_ambiguous_or_unsafe_time(value):
    with pytest.raises(ValidationError):
        Range(startMs=value, endMs=2000)


@pytest.mark.parametrize("scene_count,pace,budget", [(4, "SLOW", 8), (12, "NORMAL", 12),
                                                  (30, "FAST", 18), (60, "FAST", 24)])
def test_technical_pace_and_budget_follow_observed_density(scene_count, pace, budget):
    source = index(60000, [i * 60000 // scene_count for i in range(1, scene_count)])
    profile = resolve_profile(source, tutorial())
    assert profile.detectedPace == pace
    assert profile.frameBudget == budget
    assert profile.shotCountPerMinute == scene_count
    assert profile.vlmBatchSize == 6 and profile.vlmConcurrency == 2
    assert "upper bound" in profile.adjustmentReason


def test_user_type_is_preserved_and_auto_fallback_is_not_claimed_as_classification():
    source = index(60000, range(1000, 60000, 1000))
    manual = resolve_profile(source, tutorial(autoFallbackType="FAST_SHORT_VIDEO"))
    automatic = resolve_profile(source, ProfileConfig())
    assert manual.effectiveType == "TUTORIAL_INTERVIEW"
    assert manual.windowTargetMs == 60000 and manual.detectedPace == "FAST"
    assert automatic.effectiveType == "VLOG_DOCUMENTARY" and automatic.windowTargetMs == 55000
    assert automatic.confidence == 0 and "fallback" in automatic.adjustmentReason


def test_validated_dedup_references_adjust_pace_without_removing_scenes():
    source = index(60000, range(1000, 60000, 1000))
    plan = plan_windows(source, tutorial(novelSceneIds=[s.sceneId for s in source.scenes[:4]]))
    assert len(plan.sourceIndex.scenes) == 60
    assert plan.profile.shotCountPerMinute == 60 and plan.profile.novelShotCountPerMinute == 4
    assert plan.profile.detectedPace == "SLOW" and plan.profile.frameBudget == 8
    for ids in [["foreign"], [source.scenes[0].sceneId] * 2]:
        with pytest.raises(ValueError):
            plan_windows(source, tutorial(novelSceneIds=ids))


def test_reliable_silence_has_priority_over_closer_shot_boundary():
    result = plan_windows(index(180000, [60000, 120000]), tutorial(), silence_cues=[cue(52000, 54000)])
    assert result.windows[0].endMs == 54000
    assert result.boundaries[0].kind == "SILENCE" and result.boundaries[0].cueId == "vad_1"


@pytest.mark.parametrize("silence", [cue(52000, 54000, reliable=False),
                                    cue(52000, 54000, source=SIMULATED), cue(52000, 54000, source=UNAVAILABLE)])
def test_unreliable_or_simulated_silence_is_ignored(silence):
    result = plan_windows(index(180000, [60000, 120000]), tutorial(), silence_cues=[silence])
    assert result.windows[0].endMs == 60000 and result.boundaries[0].kind == "SCENE"


def test_equal_distance_cuts_and_cues_have_deterministic_ties():
    source = index(180000, [55000, 65000, 120000])
    assert plan_windows(source, tutorial()).windows[0].endMs == 55000
    cues = [cue(65000, 65001, name="vad_b"), cue(54999, 55000, name="vad_a")]
    first = plan_windows(source, tutorial(), silence_cues=cues)
    second = plan_windows(source, tutorial(), silence_cues=list(reversed(cues)))
    assert first.windows == second.windows and first.boundaries == second.boundaries
    assert first.windows[0].endMs == 55000


def test_silence_containing_target_cuts_at_target():
    plan = plan_windows(index(), tutorial(), silence_cues=[cue(59000, 61000)])
    assert plan.windows[0].endMs == 60000 and plan.boundaries[0].kind == "SILENCE"


def test_unknown_gap_edges_and_simulated_shots_are_not_boundary_evidence():
    gapped = build_source_index(asset(), [Range(startMs=0, endMs=55000),
                                        Range(startMs=65000, endMs=180000)], DETECTOR, REAL)
    assert plan_windows(gapped, tutorial()).boundaries[0].kind == "TARGET"
    assert plan_windows(index(180000, [55000, 65000], SIMULATED), tutorial()).boundaries[0].kind == "TARGET"


@pytest.mark.parametrize("content_type,target,max_ms", [("TUTORIAL_INTERVIEW", 60000, 75000),
                                                       ("VLOG_DOCUMENTARY", 55000, 75000),
                                                       ("FAST_SHORT_VIDEO", 40000, 45000)])
@pytest.mark.parametrize("duration", [1, 44999, 45000, 75000, 75001, 76000, 180001, 1800000])
def test_primary_windows_cover_exactly_once_with_clipped_context(content_type, target, max_ms, duration):
    plan = plan_windows(index(duration), ProfileConfig(requestedType=content_type))
    assert plan.profile.windowTargetMs == target
    assert plan.windows[0].startMs == 0 and plan.windows[-1].endMs == duration
    assert sum(w.endMs - w.startMs for w in plan.windows) == plan.plannedCoverageMs == duration
    assert len({w.windowId for w in plan.windows}) == len(plan.windows)
    for left, right in zip(plan.windows, plan.windows[1:]):
        assert left.endMs == right.startMs
        assert left.contextEndMs - right.contextStartMs == 2000
    for window in plan.windows:
        assert window.endMs - window.startMs <= max_ms
        assert 0 <= window.contextStartMs <= window.startMs < window.endMs <= window.contextEndMs <= duration
        assert window.selectedFrameIds == []
        assert window.sceneIds == [plan.sourceIndex.scenes[0].sceneId]
        assert AnalysisWindow.model_validate(window.model_dump()) == window
    assert PlanningResult.model_validate_json(plan.model_dump_json()) == plan


def test_tail_guard_prevents_a_one_second_final_window():
    result = plan_windows(index(76000, [75000]), tutorial())
    assert [w.endMs for w in result.windows] == [60000, 76000]
    # Custom search bounds exercise clamping when target would leave a tiny tail.
    policy = WindowPolicy(minMs=45000, targetMs=60000, maxMs=60000, minTailMs=15000)
    result = plan_windows(index(61000), tutorial(), policy=policy)
    assert result.windows[0].endMs == 46000 and result.boundaries[0].kind == "TAIL_GUARD"


def test_context_refs_use_half_open_intersections_and_keep_cross_window_shots():
    source = index(180000, [59000, 61000, 120000, 121000])
    plan = plan_windows(source, tutorial(), silence_cues=[cue(60000, 60001)])
    # First context ends at 61000; the scene starting at 61000 is excluded.
    assert plan.windows[0].sceneIds == [s.sceneId for s in source.scenes[:2]]
    # Second context starts at 59000; the scene ending there is excluded.
    assert plan.windows[1].sceneIds == [s.sceneId for s in source.scenes[1:4]]


@pytest.mark.parametrize("silences", [[cue(0, 1000, asset_hash="sha256:" + "b" * 64)],
                                     [cue(0, 180001)], [cue(1000, 1000)], [cue(0, 1000), cue(2000, 3000)]])
def test_foreign_duplicate_or_out_of_range_cues_are_rejected(silences):
    with pytest.raises(ValueError):
        plan_windows(index(), tutorial(), silence_cues=silences)


@pytest.mark.parametrize("policy", [dict(minMs=60001, targetMs=60000, maxMs=75000),
                                    dict(minMs=45000, targetMs=60000, maxMs=59000),
                                    dict(minMs=45000, targetMs=60000, maxMs=75000, minTailMs=45001)])
def test_invalid_policy_is_rejected(policy):
    with pytest.raises(ValidationError):
        WindowPolicy(**policy)


def test_max_windows_rejects_huge_input_without_building_partial_plan():
    with pytest.raises(ValueError, match="maxWindows"):
        plan_windows(index(9007199254740991), tutorial())
    with pytest.raises(ValueError, match="maxWindows"):
        plan_windows(index(180000), tutorial(), policy=WindowPolicy(minMs=45000, targetMs=60000, maxMs=75000, maxWindows=2))


def test_repeated_planning_is_stable_and_does_not_mutate_inputs():
    source, config, silences = index(), tutorial(), [cue(52000, 54000)]
    before = copy.deepcopy((source.model_dump(), config.model_dump(), [c.model_dump() for c in silences]))
    first = plan_windows(source, config, silence_cues=silences)
    assert first == plan_windows(source, config, silence_cues=silences)
    assert before == (source.model_dump(), config.model_dump(), [c.model_dump() for c in silences])
    changed = plan_windows(source, tutorial(configVersion="other"), silence_cues=silences)
    assert first.sourceIndex == changed.sourceIndex
    assert first.windows[0].windowId != changed.windows[0].windowId


@pytest.mark.parametrize("change", [
    lambda d: d["windows"][0].update(startMs=1),
    lambda d: d["windows"][0].update(sceneIds=["foreign"]),
    lambda d: d["windows"][0].update(selectedFrameIds=["invented"]),
    lambda d: d["windows"][0].update(windowId="forged"),
    lambda d: d["profile"].update(configVersion="foreign"),
    lambda d: d.update(plannedCoverageMs=1),
    lambda d: d["sourceIndex"].update(observedCoverageMs=0),
    lambda d: d["sourceIndex"]["scenes"][0].update(sceneId="forged"),
    lambda d: d["boundaries"][0].update(kind="SILENCE", cueId="missing"),
])
def test_persisted_plan_reader_rejects_tampering(change):
    data = plan_windows(index(), tutorial()).model_dump()
    change(data)
    with pytest.raises(ValidationError):
        PlanningResult.model_validate(data)


def test_fixture_and_cli_are_reproducible_and_do_not_load_ai_configuration(tmp_path):
    data = json.loads(FIXTURE.read_text())
    result = plan_fixture(data)
    assert json.loads(FIXTURE.with_name("offline-window-planning.output.json").read_text()) == result.model_dump()
    assert result.sourceIndex.detectionStatus == "SIMULATED"
    assert result.sourceIndex.observedCoverageMs == 0
    assert result.plannedCoverageMs == 140000
    assert len(result.windows) == 3
    output = tmp_path / "plan.json"
    command = [sys.executable, "-m", "app.analysis.offline_planning", "--input", str(FIXTURE), "--output", str(output)]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout)["status"] == "PLANNED"
    assert PlanningResult.model_validate_json(output.read_text()) == result
    subprocess.run([sys.executable, "-c", "from app.analysis.offline_planning import plan_fixture; import sys; "
                    "assert 'app.config' not in sys.modules; assert 'openai' not in sys.modules"], check=True)


def test_complete_detector_adapter_preserves_all_shots_and_closes_stream(tmp_path, monkeypatch):
    from app.tools import scene_detect

    path = tmp_path / "fake.mp4"
    path.write_bytes(b"test source bytes, not a real video")
    reference = asset(12400, assetHash="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest())
    calls = {}

    class Stream:
        def close(self):
            calls["closed"] = True

    class Manager:
        def add_detector(self, detector):
            calls["detector"] = detector

        def detect_scenes(self, video):
            calls["video"] = video

        def get_scene_list(self):
            return [(Decimal(i) / 10, Decimal(i + 1) / 10) for i in range(124)]

    monkeypatch.setattr(scene_detect, "_HAS_SCENEDETECT", True)
    monkeypatch.setattr(scene_detect, "open_video", lambda path: Stream())
    monkeypatch.setattr(scene_detect, "SceneManager", Manager)
    monkeypatch.setattr(scene_detect, "ContentDetector", lambda **kwargs: kwargs)
    result = scene_detect.detect_source_index("file://" + str(path), reference)
    assert len(result.scenes) == 124 and result.detectionStatus == "COMPLETE"
    assert calls["detector"] == {"threshold": 27.0, "min_scene_len": 1}
    assert calls["closed"]
    with pytest.raises(ValueError, match="assetHash"):
        scene_detect.detect_source_index(str(path), asset(12400))


def test_complete_detector_unavailable_path_has_no_fictional_scenes(tmp_path, monkeypatch):
    from app.tools import scene_detect

    path = tmp_path / "fake.mp4"
    path.write_bytes(b"fake")
    monkeypatch.setattr(scene_detect, "_HAS_SCENEDETECT", False)
    for video_path in [None, str(path), str(tmp_path / "missing.mp4")]:
        result = scene_detect.detect_source_index(video_path, asset())
        assert result.detectionStatus == "UNAVAILABLE"
        assert len(result.scenes) == 1 and result.scenes[0].origin == "UNOBSERVED"
        assert result.observedCoverageMs == 0


@pytest.mark.parametrize("raw_scenes", [[], [(0.0, 0.0)], [(0, .7), (.5, 1)]])
def test_complete_detector_empty_vs_malformed_output(tmp_path, monkeypatch, raw_scenes):
    from app.tools import scene_detect

    path = tmp_path / "fake.mp4"
    path.write_bytes(b"fake")
    reference = asset(1000, assetHash="sha256:" + hashlib.sha256(b"fake").hexdigest())

    class Stream:
        def close(self):
            pass

    class Manager:
        def add_detector(self, _):
            pass

        def detect_scenes(self, _):
            pass

        def get_scene_list(self):
            return raw_scenes

    monkeypatch.setattr(scene_detect, "_HAS_SCENEDETECT", True)
    monkeypatch.setattr(scene_detect, "open_video", lambda path: Stream())
    monkeypatch.setattr(scene_detect, "SceneManager", Manager)
    monkeypatch.setattr(scene_detect, "ContentDetector", lambda **kwargs: kwargs)
    result = scene_detect.detect_source_index(str(path), reference)
    assert result.detectionStatus == ("COMPLETE" if not raw_scenes else "UNAVAILABLE")
    assert result.scenes[0].origin == ("NO_CUT" if not raw_scenes else "UNOBSERVED")
