"""Independent VAD observations and bounded ASR chunk planning (global ms)."""

from bisect import bisect_left, bisect_right
from typing import Annotated, Literal

from pydantic import Field, StrictBool, model_validator

from app.analysis.source_index import DetectorIdentity, stable_id
from app.analysis.window_planner import SilenceCue
from app.schemas.script_contracts_v1 import AssetRef, Contract, Hash, Id, Integer, Provenance, Range, Text


AUDIO_PLANNER_VERSION = "audio-chunks-0.1"


def merge_ranges(ranges: list[Range]) -> list[Range]:
    """Union for derived coverage only; input observations are validated first."""
    result = []
    for r in sorted(ranges, key=lambda r: (r.startMs, r.endMs)):
        if result and r.startMs <= result[-1].endMs:
            result[-1] = Range(startMs=result[-1].startMs, endMs=max(result[-1].endMs, r.endMs))
        else:
            result.append(r.model_copy())
    return result


def overlap_ranges(left: list[Range], right: list[Range]) -> list[Range]:
    left, right = merge_ranges(left), merge_ranges(right)
    result, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        lo, hi = max(left[i].startMs, right[j].startMs), min(left[i].endMs, right[j].endMs)
        if lo < hi:
            result.append(Range(startMs=lo, endMs=hi))
        if left[i].endMs <= right[j].endMs:
            i += 1
        else:
            j += 1
    return result


def coverage_ms(ranges: list[Range]) -> int:
    return sum(r.endMs - r.startMs for r in merge_ranges(ranges))


def subtract_ranges(coverage: list[Range], excluded: list[Range]) -> list[Range]:
    excluded = merge_ranges(excluded)
    result, j = [], 0
    for r in merge_ranges(coverage):
        cursor = r.startMs
        while j < len(excluded) and excluded[j].endMs <= cursor:
            j += 1
        k = j
        while k < len(excluded) and excluded[k].startMs < r.endMs:
            cut = excluded[k]
            if cursor < cut.startMs:
                result.append(Range(startMs=cursor, endMs=min(cut.startMs, r.endMs)))
            cursor = max(cursor, cut.endMs)
            k += 1
        if cursor < r.endMs:
            result.append(Range(startMs=cursor, endMs=r.endMs))
    return result


def _ordered_ranges(ranges: list[Range], duration: int, label: str) -> None:
    previous = 0
    for r in ranges:
        if not previous <= r.startMs < r.endMs <= duration:
            raise ValueError(label + " must be ordered non-overlapping nonempty source ranges")
        previous = r.endMs


class VadObservation(Contract):
    assetRef: AssetRef
    detector: DetectorIdentity
    source: Provenance
    audioPresent: StrictBool | None
    reliable: StrictBool
    analyzedRanges: list[Range] = Field(max_length=100000)
    speechRanges: list[Range] = Field(max_length=100000)

    @model_validator(mode="after")
    def valid_observation(self) -> "VadObservation":
        duration = self.assetRef.durationMs
        _ordered_ranges(self.analyzedRanges, duration, "VAD coverage")
        _ordered_ranges(self.speechRanges, duration, "VAD speech")
        if coverage_ms(overlap_ranges(self.speechRanges, self.analyzedRanges)) != coverage_ms(self.speechRanges):
            raise ValueError("speech must be contained in actually analyzed audio")
        if self.source.mode not in {"REAL", "SIMULATED", "UNAVAILABLE"}:
            raise ValueError("VAD source must be REAL, SIMULATED or UNAVAILABLE")
        if self.reliable and self.source.mode != "REAL":
            raise ValueError("only real VAD observations may be marked reliable")
        if self.source.mode == "UNAVAILABLE":
            if self.analyzedRanges or self.speechRanges or self.audioPresent is not None or self.reliable:
                raise ValueError("unavailable VAD cannot claim audio presence or observed ranges")
        elif self.audioPresent is None or not self.analyzedRanges:
            raise ValueError("available VAD must record audio presence and actual coverage")
        if self.audioPresent is False:
            if self.speechRanges or coverage_ms(self.analyzedRanges) != duration:
                raise ValueError("verified audio absence requires full metadata coverage and no speech")
        return self


class AudioChunkPolicy(Contract):
    configVersion: Text = "audio-planning-0.1"
    maxChunkMs: Annotated[int, Field(strict=True, ge=1, le=30000)] = 30000
    mergeGapMs: Annotated[int, Field(strict=True, ge=0, le=1000)] = 1000
    overlapMs: Annotated[int, Field(strict=True, ge=0, le=1000)] = 500
    maxChunks: Annotated[int, Field(strict=True, ge=1, le=4096)] = 4096

    @model_validator(mode="after")
    def nonempty_primary_budget(self) -> "AudioChunkPolicy":
        if 2 * self.overlapMs >= self.maxChunkMs:
            raise ValueError("audio overlap must leave a positive primary chunk budget")
        return self


class AudioChunk(Contract):
    chunkId: Id
    assetHash: Hash
    sourceRange: Range
    requestRange: Range
    speechRanges: list[Range] = Field(min_length=1)


def _chunks(vad: VadObservation, policy: AudioChunkPolicy) -> list[AudioChunk]:
    groups = []
    observed = merge_ranges(vad.analyzedRanges)
    obs_cursor = 0
    for speech in vad.speechRanges:
        while observed[obs_cursor].endMs <= speech.startMs:
            obs_cursor += 1
        if (groups and speech.startMs - groups[-1].endMs <= policy.mergeGapMs
                and observed[obs_cursor].startMs <= groups[-1].startMs):
            groups[-1] = Range(startMs=groups[-1].startMs, endMs=speech.endMs)
        else:
            groups.append(speech.model_copy())
    primary_budget = policy.maxChunkMs - 2 * policy.overlapMs
    edge_budget = policy.maxChunkMs - policy.overlapMs
    count = sum(1 if g.endMs - g.startMs <= policy.maxChunkMs else
                2 + (max(0, g.endMs - g.startMs - 2 * edge_budget) + primary_budget - 1) // primary_budget
                for g in groups)
    if count > policy.maxChunks:
        raise ValueError("audio plan exceeds maxChunks; no partial chunk plan emitted")
    result = []
    # Bind detector evidence and configuration, independently of visual windows.
    observation_id = stable_id("vad", vad.model_dump())
    speech_starts = [r.startMs for r in vad.speechRanges]
    speech_ends = [r.endMs for r in vad.speechRanges]
    for group in groups:
        start = group.startMs
        while start < group.endMs:
            left_context = min(policy.overlapMs, start - group.startMs)
            remaining = group.endMs - start
            end = (group.endMs if remaining + left_context <= policy.maxChunkMs else
                   start + policy.maxChunkMs - left_context - policy.overlapMs)
            primary = Range(startMs=start, endMs=end)
            speech = overlap_ranges([primary], vad.speechRanges[
                bisect_right(speech_ends, start):bisect_left(speech_starts, end)])
            if speech:
                request = Range(startMs=start - left_context,
                                endMs=min(group.endMs, end + policy.overlapMs))
                chunk_id = stable_id("audio", {
                    "observationId": observation_id, "plannerVersion": AUDIO_PLANNER_VERSION,
                    "policy": policy.model_dump(), "sourceRange": primary.model_dump(),
                    "requestRange": request.model_dump(),
                })
                result.append(AudioChunk(chunkId=chunk_id, assetHash=vad.assetRef.assetHash,
                                         sourceRange=primary, requestRange=request, speechRanges=speech))
            start = end
    return result


class AudioPlan(Contract):
    audioSchemaVersion: Literal["audio-plan-0.1"] = "audio-plan-0.1"
    plannerVersion: Literal[AUDIO_PLANNER_VERSION] = AUDIO_PLANNER_VERSION
    planId: Id
    vad: VadObservation
    policy: AudioChunkPolicy
    status: Literal["PLANNED", "NO_SPEECH", "UNAVAILABLE"]
    chunks: list[AudioChunk]
    silenceRanges: list[Range]
    unknownRanges: list[Range]
    observedMs: Integer
    speechMs: Integer

    @model_validator(mode="after")
    def check_plan(self) -> "AudioPlan":
        expected = _audio_fields(self.vad, self.policy)
        if any(getattr(self, key) != value for key, value in expected.items()):
            raise ValueError("audio chunks, identity or coverage differ from the VAD plan")
        return self


def _audio_fields(vad: VadObservation, policy: AudioChunkPolicy) -> dict:
    duration = vad.assetRef.durationMs
    observed = coverage_ms(vad.analyzedRanges)
    known_silent = subtract_ranges(vad.analyzedRanges, vad.speechRanges)
    unknown = subtract_ranges([Range(startMs=0, endMs=duration)], vad.analyzedRanges)
    no_speech = vad.reliable and observed == duration and not vad.speechRanges
    return {
        "planId": stable_id("audio_plan", {"vad": vad.model_dump(), "policy": policy.model_dump(),
                                          "plannerVersion": AUDIO_PLANNER_VERSION}),
        "status": "NO_SPEECH" if no_speech else "PLANNED" if vad.analyzedRanges else "UNAVAILABLE",
        "chunks": _chunks(vad, policy), "silenceRanges": known_silent, "unknownRanges": unknown,
        "observedMs": observed, "speechMs": coverage_ms(vad.speechRanges),
    }


def plan_audio(vad: VadObservation, policy: AudioChunkPolicy | None = None) -> AudioPlan:
    vad = VadObservation.model_validate(vad.model_dump())
    policy = AudioChunkPolicy.model_validate(policy.model_dump()) if policy else AudioChunkPolicy()
    return AudioPlan(vad=vad, policy=policy, **_audio_fields(vad, policy))


def silence_cues(plan: AudioPlan) -> list[SilenceCue]:
    """Only real, reliable observed silence can influence the visual planner."""
    plan = AudioPlan.model_validate(plan.model_dump())
    if not plan.vad.reliable:
        return []
    return [SilenceCue(cueId=stable_id("silence", {"audioPlanId": plan.planId, "range": r.model_dump()}),
                       assetHash=plan.vad.assetRef.assetHash, sourceRange=r, reliable=True,
                       source=plan.vad.source.model_copy()) for r in plan.silenceRanges]
