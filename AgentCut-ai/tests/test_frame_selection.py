"""Deterministic frame planning with declared synthetic hash observations."""

import copy
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.analysis.frame_selection import (
    FrameCandidate, FrameSample, FrameSelectionConfig, FrameSelectionResult, generate_candidates, select_frames,
)
from app.analysis.source_index import DetectorIdentity, build_source_index, planning_hash
from app.analysis.window_planner import ProfileConfig, plan_windows
from app.schemas.analysis_evidence_v1 import AnalysisWindow
from app.schemas.script_contracts_v1 import AssetRef, Provenance, Range


REAL = Provenance(mode="REAL", provider="test-double", model=None, reason=None)
SIMULATED = REAL.model_copy(update={"mode": "SIMULATED", "reason": "offline hash fixture"})
UNAVAILABLE = REAL.model_copy(update={"mode": "UNAVAILABLE", "reason": "test decode failure"})
CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


def plan(duration=60000, cuts=(), *, frame_cap=24, source=REAL):
    asset = AssetRef(assetId="frame_test", assetHash="sha256:" + "c" * 64,
                     durationMs=duration, displayName="offline.mp4")
    detector = DetectorIdentity(name="test-double", version="1", settingsHash=planning_hash({"threshold": 27}))
    points = [0, *cuts, duration]
    index = build_source_index(asset, [Range(startMs=a, endMs=b) for a, b in zip(points, points[1:])], detector, source)
    return plan_windows(index, ProfileConfig(requestedType="TUTORIAL_INTERVIEW", frameBudgetCap=frame_cap))


def samples_for(candidates, *, source=REAL):
    rng = random.Random(1234)
    return [FrameSample(frameId=c.frameId, assetHash=c.assetHash, decodedTimestampMs=c.timestampMs,
                        perceptualHash=f"{rng.getrandbits(64):016x}", source=source) for c in candidates]


def test_long_single_shot_gets_scene_anchor_and_temporal_candidates():
    p = plan()
    candidates = generate_candidates(p)
    times = {c.timestampMs for c in candidates}
    assert {500, 5000, 15000, 25000, 30000, 35000, 45000, 55000, 59499} == times
    middle = next(c for c in candidates if c.timestampMs == 30000)
    assert set(middle.reasons) == {"SCENE_MIDPOINT", "MIDDLE"}
    assert all(c.sceneId == p.sourceIndex.scenes[0].sceneId for c in candidates)


def test_dense_short_shots_all_get_candidates_without_dropping_source_ranges():
    p = plan(60000, range(1000, 60000, 1000))
    original = copy.deepcopy(p.model_dump())
    candidates = generate_candidates(p)
    midpoints = [c for c in candidates if "SCENE_MIDPOINT" in c.reasons]
    assert len(midpoints) == len(p.sourceIndex.scenes) == 60
    result = select_frames(p, samples_for(candidates))
    assert result.selections[0].budget == 24
    assert len(result.selections[0].selectedFrameIds) == 24
    assert len(result.selections[0].sceneIdsWithoutSelectedFrame) >= 36
    assert result.plan.model_dump() == original
    assert len(result.plan.sourceIndex.scenes) == 60
    assert all(w.selectedFrameIds == [] for w in p.windows)


def test_candidate_ids_are_stable_for_same_source_point_across_window_budget_configs():
    first = generate_candidates(plan(frame_cap=6))
    second = generate_candidates(plan(frame_cap=24))
    assert [c.frameId for c in first] == [c.frameId for c in second]
    assert first[0].windowId != second[0].windowId
    modified = generate_candidates(plan(), FrameSelectionConfig(intervalMs=5000))
    by_time = {c.timestampMs: c.frameId for c in modified}
    assert all(by_time[c.timestampMs] == c.frameId for c in first)


@pytest.mark.parametrize("duration", [1, 2, 5, 10, 999, 75999, 180001])
def test_candidates_use_global_half_open_primary_and_scene_time(duration):
    p = plan(duration)
    candidates = generate_candidates(p)
    windows = {w.windowId: w for w in p.windows}
    scenes = {s.sceneId: s for s in p.sourceIndex.scenes}
    assert len({c.frameId for c in candidates}) == len(candidates)
    assert len({c.timestampMs for c in candidates}) == len(candidates)
    for c in candidates:
        w, s = windows[c.windowId], scenes[c.sceneId].sourceRange
        assert w.startMs <= c.timestampMs < w.endMs
        assert s.startMs <= c.timestampMs < s.endMs
        assert c.assetHash == p.sourceIndex.assetRef.assetHash
    if duration == 1:
        assert len(candidates) == 1 and candidates[0].timestampMs == 0


@pytest.mark.parametrize("config", [FrameSelectionConfig(maxCandidatesPerWindow=2),
                                   FrameSelectionConfig(maxCandidatesTotal=2)])
def test_candidate_caps_fail_explicitly_without_modifying_index(config):
    p = plan()
    snapshot = p.model_dump()
    with pytest.raises(ValueError, match="candidate limit"):
        generate_candidates(p, config)
    assert p.model_dump() == snapshot


def test_unique_frames_cover_all_time_regions_and_fit_actual_duration_budget():
    p = plan(140000)
    candidates = generate_candidates(p)
    result = select_frames(p, samples_for(candidates))
    assert [s.budget for s in result.selections] == [8, 8, 6]
    for selection, window in zip(result.selections, result.selectedWindows):
        assert selection.status == "SELECTED"
        assert selection.selectedBins == list(range(6))
        assert selection.missingSelectedBins == []
        assert len(selection.selectedFrameIds) <= selection.budget <= 24
        assert window.selectedFrameIds == selection.selectedFrameIds
        assert AnalysisWindow.model_validate(window.model_dump()) == window
    assert result.status == "SELECTED"
    assert FrameSelectionResult.model_validate_json(result.model_dump_json()) == result


def test_static_shot_dedups_without_padding_or_claiming_full_selected_time_coverage():
    p = plan()
    candidates = generate_candidates(p)
    samples = [s.model_copy(update={"perceptualHash": "0000000000000000"}) for s in samples_for(candidates)]
    result = select_frames(p, samples)
    selected = result.selections[0]
    assert len(selected.selectedFrameIds) == len(selected.duplicateGroups) == selected.novelSceneCount == 1
    assert selected.decodedBins == selected.equivalentBins == list(range(6))
    assert len(selected.selectedBins) == 1 and len(selected.missingSelectedBins) == 5
    assert selected.status == "PARTIAL" and "SELECTED_TIME_BINS_MISSING" in selected.reviewReasons
    assert len(selected.duplicateGroups[0].frameIds) == len(candidates)


def test_bin_matching_can_move_a_repeated_group_to_preserve_all_available_regions():
    p = plan()
    candidates = generate_candidates(p)
    samples = samples_for(candidates)
    for i, candidate in enumerate(candidates):
        if candidate.timestampMs in {5000, 15000}:
            samples[i] = samples[i].model_copy(update={"perceptualHash": "0000000000000000"})
    result = select_frames(p, samples)
    assert result.selections[0].selectedBins == list(range(6))
    selected = {c.timestampMs for c in candidates if c.frameId in result.selections[0].selectedFrameIds}
    assert 500 in selected and 15000 in selected and 5000 not in selected


def test_dedup_does_not_merge_transitive_hash_chain():
    p = plan()
    candidates = generate_candidates(p)
    hashes = ["0000000000000000", "0000000000000001", "0000000000000003"]
    samples = [s.model_copy(update={"perceptualHash": h}) for s, h in zip(samples_for(candidates), hashes)]
    result = select_frames(p, samples, FrameSelectionConfig(hammingThreshold=1))
    groups = result.selections[0].duplicateGroups
    assert [len(g.frameIds) for g in groups] == [2, 1]


def test_every_possible_group_representative_is_close_to_all_equivalents():
    p = plan()
    candidates = generate_candidates(p)
    hashes = ["0000000000000000", "000000000000003f", "0000000000000fc0"]
    samples = [s.model_copy(update={"perceptualHash": h}) for s, h in zip(samples_for(candidates), hashes)]
    result = select_frames(p, samples)
    assert [len(g.frameIds) for g in result.selections[0].duplicateGroups] == [2, 1]


def test_simulated_and_real_samples_cannot_collapse_into_same_duplicate_group():
    p = plan()
    candidates = generate_candidates(p)
    samples = [s.model_copy(update={"perceptualHash": "0000000000000000"}) for s in samples_for(candidates[:2])]
    samples[1] = samples[1].model_copy(update={"source": SIMULATED})
    selected = select_frames(p, samples).selections[0]
    assert len(selected.duplicateGroups) == 2 and selected.status == "PARTIAL"
    assert "SIMULATED_FRAME_SAMPLES" in selected.reviewReasons


def test_deduplicated_midpoint_density_controls_budget_without_rewriting_source_profile():
    p = plan(60000, range(1000, 60000, 1000))
    candidates = generate_candidates(p)
    samples = [s.model_copy(update={"perceptualHash": "0000000000000000"}) for s in samples_for(candidates)]
    selected = select_frames(p, samples).selections[0]
    assert p.profile.frameBudget == 24
    assert selected.novelSceneCount == selected.novelShotCountPerMinute == 1
    assert selected.budget == 8
    assert len(p.sourceIndex.scenes) == 60


def test_unknown_source_gap_is_not_counted_as_detected_shot():
    p = plan()
    source = build_source_index(p.sourceIndex.assetRef, [], p.sourceIndex.detector, UNAVAILABLE)
    p = plan_windows(source, p.profileConfig)
    selected = select_frames(p, samples_for(generate_candidates(p))).selections[0]
    assert selected.novelSceneCount == 0
    assert "SOURCE_DETECTION_INCOMPLETE_OR_SIMULATED" in selected.reviewReasons


def test_one_window_failure_keeps_other_window_samples_and_selected_ids():
    p = plan(180000)
    candidates = generate_candidates(p)
    samples = samples_for(candidates)
    failed_window = p.windows[1].windowId
    failed_ids = {c.frameId for c in candidates if c.windowId == failed_window}
    samples = [FrameSample(frameId=s.frameId, assetHash=s.assetHash, decodedTimestampMs=None,
                          perceptualHash=None, source=UNAVAILABLE) if s.frameId in failed_ids else s for s in samples]
    result = select_frames(p, samples)
    assert [s.status for s in result.selections] == ["SELECTED", "UNAVAILABLE", "SELECTED"]
    assert result.selections[0].selectedFrameIds and result.selections[2].selectedFrameIds
    assert set(result.selections[1].failedFrameIds) == failed_ids
    assert result.status == "PARTIAL"


def test_missing_samples_are_recorded_and_not_invented():
    p = plan()
    result = select_frames(p, [])
    assert result.status == "UNAVAILABLE" and result.samples == []
    assert result.selectedWindows[0].selectedFrameIds == []
    assert result.selections[0].failedFrameIds == [c.frameId for c in result.candidates]


@pytest.mark.parametrize("change", [
    {"frameId": "foreign"}, {"assetHash": "sha256:" + "b" * 64},
    {"decodedTimestampMs": 60000}, {"decodedTimestampMs": 5000},
])
def test_unknown_or_misbound_samples_are_rejected(change):
    p = plan()
    sample = samples_for(generate_candidates(p)[:1])[0].model_copy(update=change)
    with pytest.raises(ValueError):
        select_frames(p, [sample])


def test_decoded_timestamp_cannot_cross_scene_boundary_even_within_drift_tolerance():
    p = plan(60000, [1000])
    candidate = generate_candidates(p)[0]
    sample = samples_for([candidate])[0].model_copy(update={"decodedTimestampMs": 1000})
    with pytest.raises(ValueError, match="outside candidate scene"):
        select_frames(p, [sample])


def test_duplicate_samples_are_rejected():
    p = plan()
    sample = samples_for(generate_candidates(p)[:1])[0]
    with pytest.raises(ValueError, match="duplicate sample"):
        select_frames(p, [sample, sample])


@pytest.mark.parametrize("change", [
    {"perceptualHash": "F" * 16}, {"perceptualHash": "0" * 16 + "\n"},
    {"decodedTimestampMs": None}, {"hashVersion": "foreign"},
    {"source": UNAVAILABLE}, {"decodedTimestampMs": 1.5},
])
def test_invalid_frame_sample_shape_is_rejected(change):
    candidate = generate_candidates(plan())[0]
    data = samples_for([candidate])[0].model_dump()
    data.update(change)
    with pytest.raises(ValidationError):
        FrameSample.model_validate(data)


def test_selection_is_stable_for_out_of_order_completion_and_does_not_mutate_inputs():
    p, config = plan(), FrameSelectionConfig()
    samples = samples_for(generate_candidates(p))
    before = copy.deepcopy((p.model_dump(), config.model_dump(), [s.model_dump() for s in samples]))
    first = select_frames(p, samples, config)
    assert first == select_frames(p, list(reversed(samples)), config)
    assert before == (p.model_dump(), config.model_dump(), [s.model_dump() for s in samples])
    changed = select_frames(p, samples, config.model_copy(update={"configVersion": "other"}))
    assert first.selectionId != changed.selectionId
    assert first.candidates == changed.candidates


@pytest.mark.parametrize("change", [
    lambda d: d.update(selectionId="forged"),
    lambda d: d.update(status="UNAVAILABLE"),
    lambda d: d["candidates"][0].update(timestampMs=1),
    lambda d: d["candidates"][0].update(sceneId="foreign"),
    lambda d: d["selectedWindows"][0].update(selectedFrameIds=["invented"]),
    lambda d: d["selections"][0].update(budget=25),
    lambda d: d["selections"][0].update(selectedBins=[]),
    lambda d: d["selections"][0]["duplicateGroups"][0].update(frameIds=["invented"]),
])
def test_persisted_selection_rejects_tampered_identity_references_and_coverage(change):
    p = plan()
    data = select_frames(p, samples_for(generate_candidates(p))).model_dump()
    change(data)
    with pytest.raises(ValidationError):
        FrameSelectionResult.model_validate(data)


def test_offline_fixture_cli_preserves_explicit_simulation_and_loads_no_ai_config(tmp_path):
    from app.analysis.offline_frame_selection import OfflineSamplesInput
    from app.analysis.window_planner import PlanningResult

    p = PlanningResult.model_validate_json((CONTRACTS / "offline-window-planning.output.json").read_text())
    request = OfflineSamplesInput.model_validate_json((CONTRACTS / "offline-frame-selection.samples.json").read_text())
    expected = select_frames(p, request.samples, request.config)
    assert expected.status == "PARTIAL"
    assert len(expected.candidates) == 30
    assert sum(len(s.selectedFrameIds) for s in expected.selections) == 15
    assert all(s.source.mode == "SIMULATED" for s in expected.samples)
    output = tmp_path / "selected.json"
    completed = subprocess.run([sys.executable, "-m", "app.analysis.offline_frame_selection",
        "--plan", str(CONTRACTS / "offline-window-planning.output.json"),
        "--samples", str(CONTRACTS / "offline-frame-selection.samples.json"), "--output", str(output)],
        check=True, capture_output=True, text=True)
    assert json.loads(completed.stdout)["selectedFrames"] == 15
    assert FrameSelectionResult.model_validate_json(output.read_text()) == expected
    subprocess.run([sys.executable, "-c", "from app.analysis.offline_frame_selection import OfflineSamplesInput; "
        "import sys; assert 'app.config' not in sys.modules; assert 'openai' not in sys.modules; "
        "assert 'app.tools.window_frames' not in sys.modules"], check=True)
