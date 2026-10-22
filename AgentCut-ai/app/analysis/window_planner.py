"""Deterministic window planning on global integer milliseconds.

This module plans evidence collection. It does not select frames, run VAD/ASR,
call models, or assert that a time-covered source has been fully analyzed.
"""

from bisect import bisect_left, bisect_right
from typing import Annotated, Literal

from pydantic import Field, StrictBool, model_validator

from app.analysis.source_index import SourceIndex, planning_hash, stable_id
from app.schemas.analysis_evidence_v1 import AnalysisProfile, AnalysisWindow
from app.schemas.script_contracts_v1 import Contract, Hash, Id, Integer, Positive, Provenance, Range, Text


ContentType = Literal["TUTORIAL_INTERVIEW", "VLOG_DOCUMENTARY", "FAST_SHORT_VIDEO"]
PLANNER_VERSION = "window-planner-0.1"
PROFILE_VERSION = "technical-profile-0.1"


class ProfileConfig(Contract):
    configVersion: Text = "offline-planning-0.1"
    requestedType: Literal["AUTO", "TUTORIAL_INTERVIEW", "VLOG_DOCUMENTARY", "FAST_SHORT_VIDEO"] = "AUTO"
    autoFallbackType: ContentType = "VLOG_DOCUMENTARY"
    # None means deduplication has not run, rather than zero novel scenes.
    novelSceneIds: list[Id] | None = None
    frameBudgetCap: Annotated[int, Field(strict=True, ge=6, le=24)] = 24


def resolve_profile(index: SourceIndex, config: ProfileConfig) -> AnalysisProfile:
    observed = {s.sceneId for s in index.scenes if s.source.mode == "REAL"}
    density = len(observed) * 60000 / index.assetRef.durationMs
    if config.novelSceneIds is None:
        novel_density = density
        dedup_reason = "Deduplication pending; novel density is only a raw-count upper bound."
    else:
        novel = set(config.novelSceneIds)
        if len(novel) != len(config.novelSceneIds) or not novel <= observed:
            raise ValueError("novelSceneIds must be unique references to real observed scenes")
        novel_density = len(novel) * 60000 / index.assetRef.durationMs
        dedup_reason = "Novel density uses caller-supplied deduplication references."
    pace = "SLOW" if novel_density <= 8 else "NORMAL" if novel_density <= 20 else "FAST"
    effective = config.autoFallbackType if config.requestedType == "AUTO" else config.requestedType
    target = {"TUTORIAL_INTERVIEW": 60000, "VLOG_DOCUMENTARY": 55000, "FAST_SHORT_VIDEO": 40000}[effective]
    base_budget = 8 if novel_density <= 8 else 12 if novel_density <= 20 else 18 if novel_density <= 35 else 24
    budget = min(config.frameBudgetCap, max(6, round(base_budget * target / 60000)))
    type_reason = (f"AUTO uses configured fallback {effective}; semantic classification features are pending."
                   if config.requestedType == "AUTO" else f"Manual content type {effective} is preserved.")
    coverage_reason = ("Complete real scene detection." if index.detectionStatus == "COMPLETE" else
                       f"Detection is {index.detectionStatus}; density is a lower bound and pace is provisional.")
    return AnalysisProfile(
        profileVersion=PROFILE_VERSION, configVersion=config.configVersion,
        requestedType=config.requestedType, effectiveType=effective, detectedPace=pace,
        shotCountPerMinute=density, novelShotCountPerMinute=novel_density,
        # No calibrated content-classification confidence exists in this slice.
        confidence=0.0, adjustmentReason=" ".join([type_reason, coverage_reason, dedup_reason]),
        windowTargetMs=target, frameBudget=budget, vlmBatchSize=6, vlmConcurrency=2,
    )


class WindowPolicy(Contract):
    minMs: Positive
    targetMs: Positive
    maxMs: Positive
    contextMs: Annotated[int, Field(strict=True, ge=0, le=5000)] = 1000
    minTailMs: Integer = 15000
    maxWindows: Annotated[int, Field(strict=True, ge=1, le=4096)] = 4096

    @model_validator(mode="after")
    def valid_policy(self) -> "WindowPolicy":
        if not self.minMs <= self.targetMs <= self.maxMs:
            raise ValueError("window policy requires minMs <= targetMs <= maxMs")
        if self.minTailMs > self.minMs:
            raise ValueError("minTailMs must not exceed minMs")
        return self


def default_policy(profile: AnalysisProfile) -> WindowPolicy:
    fast = profile.effectiveType == "FAST_SHORT_VIDEO"
    return WindowPolicy(minMs=30000 if fast else 45000,
                        targetMs=profile.windowTargetMs, maxMs=45000 if fast else 75000)


class SilenceCue(Contract):
    cueId: Id
    assetHash: Hash
    sourceRange: Range
    reliable: StrictBool
    source: Provenance


class BoundaryDecision(Contract):
    windowId: Id
    cutMs: Positive
    kind: Literal["SILENCE", "SCENE", "TARGET", "TAIL_GUARD", "FINAL"]
    cueId: Id | None
    sceneId: Id | None


def _validate_cues(index: SourceIndex, cues: list[SilenceCue]) -> None:
    ids = set()
    for cue in cues:
        r = cue.sourceRange
        if cue.cueId in ids or cue.assetHash != index.assetRef.assetHash:
            raise ValueError("duplicate silence cue or foreign asset hash")
        ids.add(cue.cueId)
        if not 0 <= r.startMs < r.endMs <= index.assetRef.durationMs:
            raise ValueError("silence cue must be a nonempty range within the source")


def _layout(index: SourceIndex, policy: WindowPolicy, cues: list[SilenceCue]) -> list[tuple]:
    """Return (start, end, reason, cueId, sceneId), with exact full coverage."""
    duration = index.assetRef.durationMs
    if (duration + policy.maxMs - 1) // policy.maxMs > policy.maxWindows:
        raise ValueError("source exceeds configured maxWindows; no partial plan was emitted")
    _validate_cues(index, cues)
    # Gap edges and simulated scenes cannot become reliable shot boundaries.
    edges = [(left.sourceRange.endMs, left.sceneId)
             for left, right in zip(index.scenes, index.scenes[1:])
             if left.source.mode == right.source.mode == "REAL"]
    edge_times = [e[0] for e in edges]
    reliable = sorted((c for c in cues if c.reliable and c.source.mode == "REAL"),
                      key=lambda c: (c.sourceRange.startMs, c.cueId))
    layout = []
    start = 0
    cue_cursor = 0
    active_cues = []
    while start < duration:
        if len(layout) >= policy.maxWindows:
            raise ValueError("window plan exceeds configured maxWindows; no partial plan was emitted")
        if duration - start <= policy.maxMs:
            layout.append((start, duration, "FINAL", None, None))
            break
        low, high = start + policy.minMs, start + policy.maxMs
        # Avoid a tiny final window when the search range permits it.
        if duration - policy.minTailMs >= low:
            high = min(high, duration - policy.minTailMs)
        target = min(start + policy.targetMs, high)
        active_cues = [c for c in active_cues if c.sourceRange.endMs >= low]
        while cue_cursor < len(reliable) and reliable[cue_cursor].sourceRange.startMs <= high:
            candidate = reliable[cue_cursor]
            if candidate.sourceRange.endMs >= low:
                active_cues.append(candidate)
            cue_cursor += 1
        silence_candidates = []
        for cue in active_cues:
            lo = max(low, cue.sourceRange.startMs)
            hi = min(high, cue.sourceRange.endMs)
            if lo <= hi:
                cut = min(max(target, lo), hi)
                silence_candidates.append((abs(cut - target), cut, cue.cueId))
        if silence_candidates:
            _, end, cue_id = min(silence_candidates)
            decision = ("SILENCE", cue_id, None)
        else:
            candidates = edges[bisect_left(edge_times, low):bisect_right(edge_times, high)]
            if candidates:
                end, scene_id = min(candidates, key=lambda e: (abs(e[0] - target), e[0], e[1]))
                decision = ("SCENE", None, scene_id)
            else:
                end = target
                decision = ("TARGET" if target == start + policy.targetMs else "TAIL_GUARD", None, None)
        layout.append((start, end, *decision))
        start = end
    return layout


def _windows(index: SourceIndex, profile: AnalysisProfile, config: ProfileConfig,
             policy: WindowPolicy, cues: list[SilenceCue]) -> tuple[list[AnalysisWindow], list[BoundaryDecision]]:
    windows, decisions = [], []
    scene_starts = [s.sourceRange.startMs for s in index.scenes]
    scene_ends = [s.sourceRange.endMs for s in index.scenes]
    # Hash large deduplication configuration once, rather than once per window.
    binding = planning_hash({
        "assetId": index.assetRef.assetId, "assetHash": index.assetRef.assetHash,
        "sourceIndexId": index.indexId, "plannerVersion": PLANNER_VERSION,
        "profile": profile.model_dump(), "profileConfig": config.model_dump(),
        "policy": policy.model_dump(),
    })
    for start, end, kind, cue_id, scene_id in _layout(index, policy, cues):
        context_start = max(0, start - policy.contextMs)
        context_end = min(index.assetRef.durationMs, end + policy.contextMs)
        refs = [s.sceneId for s in index.scenes[
            bisect_right(scene_ends, context_start):bisect_left(scene_starts, context_end)]]
        window_id = stable_id("window", {
            "planningBindingHash": binding, "startMs": start, "endMs": end,
            "contextStartMs": context_start, "contextEndMs": context_end,
        })
        windows.append(AnalysisWindow(
            windowId=window_id, assetHash=index.assetRef.assetHash,
            startMs=start, endMs=end, contextStartMs=context_start, contextEndMs=context_end,
            sceneIds=refs, selectedFrameIds=[], profileVersion=profile.profileVersion,
            plannerVersion=PLANNER_VERSION,
        ))
        decisions.append(BoundaryDecision(windowId=window_id, cutMs=end, kind=kind,
                                          cueId=cue_id, sceneId=scene_id))
    return windows, decisions


class PlanningResult(Contract):
    planningSchemaVersion: Literal["offline-window-plan-0.1"] = "offline-window-plan-0.1"
    status: Literal["PLANNED"] = "PLANNED"
    sourceIndex: SourceIndex
    profileConfig: ProfileConfig
    profile: AnalysisProfile
    policy: WindowPolicy
    silenceCues: list[SilenceCue]
    windows: list[AnalysisWindow] = Field(min_length=1)
    boundaries: list[BoundaryDecision] = Field(min_length=1)
    plannedCoverageMs: Integer

    @model_validator(mode="after")
    def validate_plan(self) -> "PlanningResult":
        if self.profile != resolve_profile(self.sourceIndex, self.profileConfig):
            raise ValueError("analysis profile differs from its source/configuration")
        if self.policy.targetMs != self.profile.windowTargetMs:
            raise ValueError("window target must match the resolved profile")
        expected_windows, expected_decisions = _windows(
            self.sourceIndex, self.profile, self.profileConfig, self.policy, self.silenceCues)
        if self.windows != expected_windows or self.boundaries != expected_decisions:
            raise ValueError("windows, references, identities or boundary decisions differ from the planner")
        if self.plannedCoverageMs != self.sourceIndex.assetRef.durationMs:
            raise ValueError("primary windows must cover exactly the full source duration")
        return self


def plan_windows(index: SourceIndex, config: ProfileConfig | None = None, *,
                 silence_cues: list[SilenceCue] | None = None,
                 policy: WindowPolicy | None = None) -> PlanningResult:
    """Pure, deterministic, non-mutating entry point. No external services."""
    index = SourceIndex.model_validate(index.model_dump())
    config = ProfileConfig.model_validate(config.model_dump()) if config else ProfileConfig()
    cues = [SilenceCue.model_validate(c.model_dump()) for c in (silence_cues or [])]
    profile = resolve_profile(index, config)
    policy = WindowPolicy.model_validate(policy.model_dump()) if policy else default_policy(profile)
    if policy.targetMs != profile.windowTargetMs:
        raise ValueError("window target must match the resolved profile")
    windows, decisions = _windows(index, profile, config, policy, cues)
    return PlanningResult(sourceIndex=index, profileConfig=config, profile=profile, policy=policy,
                          silenceCues=cues, windows=windows, boundaries=decisions,
                          plannedCoverageMs=index.assetRef.durationMs)
