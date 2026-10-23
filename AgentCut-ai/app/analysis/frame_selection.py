"""Bounded candidate generation and pHash selection, independent of AI clients."""

from bisect import bisect_right
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.analysis.perceptual_hash import PHASH_VERSION, hamming_distance
from app.analysis.source_index import planning_hash, stable_id
from app.analysis.window_planner import PlanningResult
from app.schemas.analysis_evidence_v1 import AnalysisWindow
from app.schemas.script_contracts_v1 import Contract, Hash, Id, Integer, Positive, Provenance, Text


CANDIDATE_VERSION = "window-candidates-0.1"
SELECTION_VERSION = "window-frame-selection-0.1"
PHash = Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]


class FrameSelectionConfig(Contract):
    configVersion: Text = "frame-selection-0.1"
    intervalMs: Annotated[int, Field(strict=True, ge=1000, le=30000)] = 10000
    edgeOffsetMs: Annotated[int, Field(strict=True, ge=0, le=1000)] = 500
    coverageBins: Annotated[int, Field(strict=True, ge=3, le=6)] = 6
    hammingThreshold: Annotated[int, Field(strict=True, ge=0, le=16)] = 6
    maxTimestampDriftMs: Annotated[int, Field(strict=True, ge=0, le=1000)] = 1000
    maxCandidatesPerWindow: Annotated[int, Field(strict=True, ge=1, le=5000)] = 2048
    maxCandidatesTotal: Annotated[int, Field(strict=True, ge=1, le=100000)] = 20000


class FrameCandidate(Contract):
    frameId: Id
    assetHash: Hash
    windowId: Id
    sceneId: Id
    timestampMs: Integer
    reasons: list[Literal["SCENE_MIDPOINT", "UNIFORM", "START", "MIDDLE", "END"]] = Field(min_length=1)


class FrameSample(Contract):
    frameId: Id
    assetHash: Hash
    decodedTimestampMs: Integer | None
    perceptualHash: PHash | None
    hashVersion: Literal[PHASH_VERSION] = PHASH_VERSION
    source: Provenance

    @model_validator(mode="after")
    def valid_sample(self) -> "FrameSample":
        if self.source.mode in {"REAL", "SIMULATED"}:
            if self.decodedTimestampMs is None or self.perceptualHash is None:
                raise ValueError("real/simulated frame sample requires timestamp and pHash")
        elif self.source.mode == "UNAVAILABLE":
            if self.decodedTimestampMs is not None or self.perceptualHash is not None or not self.source.reason:
                raise ValueError("unavailable frame must have a reason and no fabricated timestamp/hash")
        else:
            raise ValueError("frame sample source must be REAL, SIMULATED or UNAVAILABLE")
        return self


def generate_candidates(plan: PlanningResult, config: FrameSelectionConfig | None = None) -> list[FrameCandidate]:
    """Preserve the scene index; caps fail explicitly instead of sampling it away."""
    plan = PlanningResult.model_validate(plan.model_dump())
    config = FrameSelectionConfig.model_validate(config.model_dump()) if config else FrameSelectionConfig()
    scenes = plan.sourceIndex.scenes
    starts = [s.sourceRange.startMs for s in scenes]
    ends = [s.sourceRange.endMs for s in scenes]
    candidates = []
    for window in plan.windows:
        points: dict[int, set[str]] = {}

        def add(timestamp: int, reason: str):
            points.setdefault(timestamp, set()).add(reason)
            if len(points) > config.maxCandidatesPerWindow or len(candidates) + len(points) > config.maxCandidatesTotal:
                raise ValueError("candidate limit exceeded; source index retained, no partial candidate plan emitted")

        for scene in scenes[bisect_right(ends, window.startMs):bisect_right(starts, window.endMs - 1)]:
            lo, hi = max(window.startMs, scene.sourceRange.startMs), min(window.endMs, scene.sourceRange.endMs)
            add((lo + hi) // 2, "SCENE_MIDPOINT")
        duration = window.endMs - window.startMs
        count = (duration + config.intervalMs - 1) // config.intervalMs
        # Each temporal bin also has a candidate, including sub-second windows.
        for n in {count, min(config.coverageBins, duration)}:
            for i in range(n):
                add(window.startMs + (2 * i + 1) * duration // (2 * n), "UNIFORM")
        offset = min(config.edgeOffsetMs, (duration - 1) // 2)
        add(window.startMs + offset, "START")
        add(window.startMs + duration // 2, "MIDDLE")
        add(window.endMs - 1 - offset, "END")
        for timestamp, reasons in sorted(points.items()):
            scene = scenes[bisect_right(starts, timestamp) - 1]
            frame_id = stable_id("frame", {
                "assetId": plan.sourceIndex.assetRef.assetId,
                "assetHash": plan.sourceIndex.assetRef.assetHash,
                "sceneId": scene.sceneId, "timestampMs": timestamp,
                "candidateVersion": CANDIDATE_VERSION,
            })
            candidates.append(FrameCandidate(frameId=frame_id, assetHash=window.assetHash,
                windowId=window.windowId, sceneId=scene.sceneId, timestampMs=timestamp, reasons=sorted(reasons)))
    return candidates


class DuplicateGroup(Contract):
    representativeId: Id
    frameIds: list[Id] = Field(min_length=1)


class WindowFrameSelection(Contract):
    windowId: Id
    status: Literal["SELECTED", "PARTIAL", "UNAVAILABLE"]
    budget: Positive
    novelSceneCount: Integer
    novelShotCountPerMinute: float = Field(ge=0, allow_inf_nan=False)
    selectedFrameIds: list[Id]
    duplicateGroups: list[DuplicateGroup]
    failedFrameIds: list[Id]
    sceneIdsWithoutSelectedFrame: list[Id]
    decodedBins: list[Integer]
    selectedBins: list[Integer]
    equivalentBins: list[Integer]
    missingSelectedBins: list[Integer]
    coverageBinCount: Positive
    reviewReasons: list[Text]


def _validate_samples(plan: PlanningResult, config: FrameSelectionConfig,
                      candidates: list[FrameCandidate], samples: list[FrameSample]) -> dict[str, FrameSample]:
    known = {c.frameId: c for c in candidates}
    windows = {w.windowId: w for w in plan.windows}
    scenes = {s.sceneId: s for s in plan.sourceIndex.scenes}
    result = {}
    for sample in samples:
        if sample.frameId in result or sample.frameId not in known:
            raise ValueError("duplicate sample or unknown frameId")
        candidate = known[sample.frameId]
        if sample.assetHash != candidate.assetHash:
            raise ValueError("frame sample assetHash mismatch")
        if sample.decodedTimestampMs is not None:
            t = sample.decodedTimestampMs
            w, scene = windows[candidate.windowId], scenes[candidate.sceneId]
            if not (w.startMs <= t < w.endMs and scene.sourceRange.startMs <= t < scene.sourceRange.endMs):
                raise ValueError("decoded frame falls outside candidate scene/primary window")
            if abs(t - candidate.timestampMs) > config.maxTimestampDriftMs:
                raise ValueError("decoded frame exceeds configured timestamp tolerance")
        result[sample.frameId] = sample
    return result


def _select_window(plan: PlanningResult, window: AnalysisWindow, config: FrameSelectionConfig,
                   candidates: list[FrameCandidate], samples: dict[str, FrameSample]) -> WindowFrameSelection:
    usable = [c for c in candidates if c.frameId in samples and samples[c.frameId].perceptualHash is not None]
    usable.sort(key=lambda c: (samples[c.frameId].decodedTimestampMs, c.frameId))
    groups: list[list[FrameCandidate]] = []
    for candidate in usable:
        sample = samples[candidate.frameId]
        # Complete-link grouping keeps every possible selected representative
        # within threshold of all equivalents; no transitive similarity chains.
        group = next((g for g in groups if samples[g[0].frameId].source.mode == sample.source.mode
                      and all(hamming_distance(samples[c.frameId].perceptualHash, sample.perceptualHash)
                              <= config.hammingThreshold for c in g)), None)
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)
    scene_ranges = {s.sceneId: s.sourceRange for s in plan.sourceIndex.scenes}
    detected_scenes = {s.sceneId for s in plan.sourceIndex.scenes if s.origin != "UNOBSERVED"}
    midpoint_groups = [g for g in groups if any("SCENE_MIDPOINT" in c.reasons and c.sceneId in detected_scenes for c in g)]
    novel_scenes = len(midpoint_groups)
    duration = window.endMs - window.startMs
    density = novel_scenes * 60000 / duration
    base = 8 if density <= 8 else 12 if density <= 20 else 18 if density <= 35 else 24
    # Capacity, not a demand to pad duplicates when fewer distinct frames exist.
    budget = min(plan.profileConfig.frameBudgetCap, max(6, (base * duration + 30000) // 60000))
    bin_count = min(config.coverageBins, duration)

    def time(candidate):
        return samples[candidate.frameId].decodedTimestampMs

    def bin_of(candidate):
        return min(bin_count - 1, (time(candidate) - window.startMs) * bin_count // duration)

    priority = list(dict.fromkeys([0, bin_count // 2, bin_count - 1, *range(bin_count)]))
    options_by_bin = {}
    for b in priority:
        options = [(abs((time(c) - window.startMs) * 2 * bin_count - (2 * b + 1) * duration), time(c), c.frameId, i, c)
                   for i, group in enumerate(groups) for c in group if bin_of(c) == b]
        options_by_bin[b] = sorted(options, key=lambda o: o[:3])
    # Maximum bin/group matching avoids consuming a repeated group in the only
    # bin where another distinct group is available. At most six bins recurse.
    group_bins, bin_frames = {}, {}

    def match(b, visited):
        for *_, i, candidate in options_by_bin[b]:
            if i in visited:
                continue
            visited.add(i)
            if i not in group_bins or match(group_bins[i], visited):
                group_bins[i] = b
                bin_frames[b] = candidate
                return True
        return False

    for b in priority:
        match(b, set())
    selected: list[FrameCandidate] = list(bin_frames.values())
    available = set(range(len(groups))) - set(group_bins)
    while available and len(selected) < budget:
        selected_scenes = {c.sceneId for c in selected}

        def score(option):
            _, c = option
            r = scene_ranges[c.sceneId]
            distance = min((abs(time(c) - time(s)) for s in selected), default=duration)
            return (c.sceneId not in selected_scenes, distance,
                    min(window.endMs, r.endMs) - max(window.startMs, r.startMs), -time(c), c.frameId)

        i, candidate = max(((i, c) for i in sorted(available) for c in groups[i]), key=score)
        selected.append(candidate)
        available.remove(i)
    selected.sort(key=lambda c: (time(c), c.frameId))
    selected_ids = {c.frameId for c in selected}
    selected_bins = sorted({bin_of(c) for c in selected})
    equivalent_bins = sorted({bin_of(c) for g in groups if any(c.frameId in selected_ids for c in g) for c in g})
    missing = sorted(set(range(bin_count)) - set(selected_bins))
    failed = [c.frameId for c in candidates if c.frameId not in samples or samples[c.frameId].perceptualHash is None]
    reasons = []
    if failed:
        reasons.append("MISSING_OR_FAILED_SAMPLES")
    if missing:
        reasons.append("SELECTED_TIME_BINS_MISSING")
    if any(samples[c.frameId].source.mode != "REAL" for c in usable):
        reasons.append("SIMULATED_FRAME_SAMPLES")
    if plan.sourceIndex.detectionStatus != "COMPLETE":
        reasons.append("SOURCE_DETECTION_INCOMPLETE_OR_SIMULATED")
    primary_scenes = list(dict.fromkeys(c.sceneId for c in candidates))
    return WindowFrameSelection(windowId=window.windowId,
        status="UNAVAILABLE" if not selected else "PARTIAL" if reasons else "SELECTED",
        budget=budget, novelSceneCount=novel_scenes, novelShotCountPerMinute=density,
        selectedFrameIds=[c.frameId for c in selected],
        duplicateGroups=[DuplicateGroup(representativeId=g[0].frameId, frameIds=[c.frameId for c in g]) for g in groups],
        failedFrameIds=failed, sceneIdsWithoutSelectedFrame=[s for s in primary_scenes if s not in {c.sceneId for c in selected}],
        decodedBins=sorted({bin_of(c) for c in usable}), selectedBins=selected_bins,
        equivalentBins=equivalent_bins, missingSelectedBins=missing, coverageBinCount=bin_count,
        reviewReasons=reasons)


def _selections(plan: PlanningResult, config: FrameSelectionConfig,
                candidates: list[FrameCandidate], samples: list[FrameSample]):
    sample_map = _validate_samples(plan, config, candidates, samples)
    by_window = {w.windowId: [] for w in plan.windows}
    for candidate in candidates:
        by_window[candidate.windowId].append(candidate)
    selections = [_select_window(plan, w, config, by_window[w.windowId], sample_map) for w in plan.windows]
    selected_windows = [AnalysisWindow.model_validate({**w.model_dump(), "selectedFrameIds": s.selectedFrameIds})
                        for w, s in zip(plan.windows, selections)]
    status = ("UNAVAILABLE" if all(s.status == "UNAVAILABLE" for s in selections) else
              "SELECTED" if all(s.status == "SELECTED" for s in selections) else "PARTIAL")
    return selections, selected_windows, status


class FrameSelectionResult(Contract):
    selectionSchemaVersion: Literal["offline-frame-selection-0.1"] = "offline-frame-selection-0.1"
    selectorVersion: Literal[SELECTION_VERSION] = SELECTION_VERSION
    candidateVersion: Literal[CANDIDATE_VERSION] = CANDIDATE_VERSION
    selectionId: Id
    status: Literal["SELECTED", "PARTIAL", "UNAVAILABLE"]
    plan: PlanningResult
    config: FrameSelectionConfig
    candidates: list[FrameCandidate] = Field(min_length=1)
    samples: list[FrameSample]
    selections: list[WindowFrameSelection] = Field(min_length=1)
    selectedWindows: list[AnalysisWindow] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_selection(self) -> "FrameSelectionResult":
        if self.candidates != generate_candidates(self.plan, self.config):
            raise ValueError("candidate geometry/identity differs from the source/window plan")
        selections, windows, status = _selections(self.plan, self.config, self.candidates, self.samples)
        if self.selections != selections or self.selectedWindows != windows or self.status != status:
            raise ValueError("frame selection, coverage or references differ from deterministic selection")
        if self.selectionId != _selection_id(self.plan, self.config, self.samples):
            raise ValueError("frame selection identity mismatch")
        return self


def _selection_id(plan: PlanningResult, config: FrameSelectionConfig, samples: list[FrameSample]) -> str:
    return stable_id("selection", {"planHash": planning_hash(plan.model_dump()), "config": config.model_dump(),
        "selectorVersion": SELECTION_VERSION, "candidateVersion": CANDIDATE_VERSION,
        "samplesHash": planning_hash({"samples": sorted((s.model_dump() for s in samples), key=lambda s: s["frameId"])})})


def select_frames(plan: PlanningResult, samples: list[FrameSample],
                  config: FrameSelectionConfig | None = None) -> FrameSelectionResult:
    plan = PlanningResult.model_validate(plan.model_dump())
    config = FrameSelectionConfig.model_validate(config.model_dump()) if config else FrameSelectionConfig()
    samples = sorted((FrameSample.model_validate(s.model_dump()) for s in samples), key=lambda s: s.frameId)
    candidates = generate_candidates(plan, config)
    selections, windows, status = _selections(plan, config, candidates, samples)
    return FrameSelectionResult(selectionId=_selection_id(plan, config, samples), status=status,
        plan=plan, config=config, candidates=candidates, samples=samples, selections=selections, selectedWindows=windows)
