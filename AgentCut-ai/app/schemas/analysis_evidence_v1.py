"""B1 analysis evidence contract, separate from the legacy AnalysisReport.

All time values are integer milliseconds on the original asset timeline. Ranges
are half open: [startMs, endMs). The contract carries evidence and coverage; it
does not change the running analysis pipeline or Plan 1.0.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Id = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")]
NonEmpty = Annotated[str, Field(min_length=1)]
Ms = Annotated[int, Field(strict=True, ge=0)]
Count = Annotated[int, Field(strict=True, ge=0)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceProvenance(ContractModel):
    mode: Literal["REAL", "SIMULATED", "MIXED", "NO_SPEECH", "UNAVAILABLE"]
    provider: str | None = None
    model: str | None = None
    reason: str | None = None


class AnalysisProfile(ContractModel):
    profileVersion: NonEmpty
    configVersion: NonEmpty
    requestedType: Literal["AUTO", "TUTORIAL_INTERVIEW", "VLOG_DOCUMENTARY", "FAST_SHORT_VIDEO"]
    effectiveType: Literal["TUTORIAL_INTERVIEW", "VLOG_DOCUMENTARY", "FAST_SHORT_VIDEO"]
    detectedPace: Literal["SLOW", "NORMAL", "FAST"]
    shotCountPerMinute: float = Field(ge=0)
    novelShotCountPerMinute: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    adjustmentReason: str
    windowTargetMs: Annotated[int, Field(strict=True, gt=0)]
    frameBudget: Count
    vlmBatchSize: Annotated[int, Field(strict=True, gt=0)]
    vlmConcurrency: Annotated[int, Field(strict=True, gt=0)]

    @model_validator(mode="after")
    def keep_manual_type(self) -> "AnalysisProfile":
        if self.requestedType != "AUTO" and self.requestedType != self.effectiveType:
            raise ValueError("manual requestedType cannot be overridden")
        if self.novelShotCountPerMinute > self.shotCountPerMinute:
            raise ValueError("novel shot density cannot exceed shot density")
        return self


class AnalysisWindow(ContractModel):
    windowId: Id
    assetHash: NonEmpty
    startMs: Ms
    endMs: Ms
    contextStartMs: Ms
    contextEndMs: Ms
    sceneIds: list[Id]
    selectedFrameIds: list[Id]
    profileVersion: NonEmpty
    plannerVersion: NonEmpty

    @model_validator(mode="after")
    def valid_bounds(self) -> "AnalysisWindow":
        if not self.contextStartMs <= self.startMs < self.endMs <= self.contextEndMs:
            raise ValueError("window context must contain a nonempty primary range")
        if len(self.sceneIds) != len(set(self.sceneIds)):
            raise ValueError("duplicate sceneId in window")
        if len(self.selectedFrameIds) != len(set(self.selectedFrameIds)):
            raise ValueError("duplicate selectedFrameId in window")
        return self


class FrameObservation(ContractModel):
    frameId: Id
    windowId: Id
    sceneId: Id
    timestampMs: Ms
    description: str
    tags: list[str]
    importance: float = Field(ge=0, le=1)
    source: SourceProvenance


class TranscriptSegmentV1(ContractModel):
    transcriptId: Id
    startMs: Ms
    endMs: Ms
    text: str
    timingQuality: Literal["COARSE_BLOCK", "SENTENCE", "WORD", "MANUAL"]
    source: SourceProvenance

    @model_validator(mode="after")
    def nonempty_range(self) -> "TranscriptSegmentV1":
        if self.startMs >= self.endMs:
            raise ValueError("transcript range must be nonempty")
        return self


class WindowCoverage(ContractModel):
    selectedFrames: Count
    successfulFrames: Count
    asrOverlapMs: Ms
    visualComplete: bool
    audioComplete: bool


class WindowAnalysis(ContractModel):
    windowId: Id
    startMs: Ms
    endMs: Ms
    frameObservationRefs: list[Id]
    transcriptRefs: list[Id]
    summary: str
    topics: list[str]
    events: list[str]
    coverage: WindowCoverage
    provenance: dict[str, SourceProvenance]

    @model_validator(mode="after")
    def nonempty_range(self) -> "WindowAnalysis":
        if self.startMs >= self.endMs:
            raise ValueError("window analysis range must be nonempty")
        if len(self.frameObservationRefs) != len(set(self.frameObservationRefs)):
            raise ValueError("duplicate frame observation reference")
        if len(self.transcriptRefs) != len(set(self.transcriptRefs)):
            raise ValueError("duplicate transcript reference")
        return self


class GlobalFinding(ContractModel):
    findingId: Id
    kind: Literal["TOPIC", "CHAPTER", "ARGUMENT", "HIGHLIGHT", "REDUNDANCY", "DEPENDENCY"]
    startMs: Ms
    endMs: Ms
    text: NonEmpty
    evidenceRefs: list[Id] = Field(min_length=1)

    @model_validator(mode="after")
    def nonempty_range(self) -> "GlobalFinding":
        if self.startMs >= self.endMs:
            raise ValueError("finding range must be nonempty")
        return self


class GlobalAnalysis(ContractModel):
    windowRefs: list[Id]
    summary: str
    topics: list[str]
    findings: list[GlobalFinding]
    provenance: dict[str, SourceProvenance]


class FailureRange(ContractModel):
    startMs: Ms
    endMs: Ms
    phase: Literal["PROBE", "SCENE", "FRAMES", "ASR", "VLM", "FUSION", "GLOBAL"]
    code: NonEmpty
    reason: str

    @model_validator(mode="after")
    def nonempty_range(self) -> "FailureRange":
        if self.startMs >= self.endMs:
            raise ValueError("failure range must be nonempty")
        return self


class GlobalCoverage(ContractModel):
    totalWindows: Count
    completeWindows: Count
    coveredMs: Ms
    failedWindowIds: list[Id]


class AnalysisEvidenceV1(ContractModel):
    schemaVersion: Literal["1.0"]
    assetId: Id
    assetHash: NonEmpty
    durationMs: Annotated[int, Field(strict=True, gt=0)]
    configVersion: NonEmpty
    profile: AnalysisProfile
    windows: list[AnalysisWindow] = Field(min_length=1)
    frameObservations: list[FrameObservation]
    transcripts: list[TranscriptSegmentV1]
    windowAnalyses: list[WindowAnalysis]
    globalAnalysis: GlobalAnalysis
    coverage: GlobalCoverage
    failureRanges: list[FailureRange]
    executionStatus: Literal["SUCCESS"]
    analysisOutcome: Literal["COMPLETE", "PARTIAL"]
    reviewStatus: Literal["READY", "NEEDS_REVIEW"]
    provenance: dict[str, SourceProvenance]

    @model_validator(mode="after")
    def validate_evidence(self) -> "AnalysisEvidenceV1":
        if self.configVersion != self.profile.configVersion:
            raise ValueError("profile configVersion mismatch")
        windows = self.windows
        window_ids = [w.windowId for w in windows]
        if len(window_ids) != len(set(window_ids)):
            raise ValueError("duplicate windowId")
        if windows[0].startMs != 0 or windows[-1].endMs != self.durationMs:
            raise ValueError("primary windows must cover the whole asset")
        for previous, current in zip(windows, windows[1:]):
            if previous.endMs != current.startMs:
                raise ValueError("primary windows must be contiguous and ordered")

        by_window = {w.windowId: w for w in windows}
        selected_ids = [frame_id for w in windows for frame_id in w.selectedFrameIds]
        if len(selected_ids) != len(set(selected_ids)):
            raise ValueError("selected frameId belongs to more than one window")
        for window in windows:
            if window.assetHash != self.assetHash:
                raise ValueError("window assetHash mismatch")
            if window.profileVersion != self.profile.profileVersion:
                raise ValueError("window profileVersion mismatch")
            if window.contextEndMs > self.durationMs:
                raise ValueError("window context exceeds asset duration")

        frame_by_id = {frame.frameId: frame for frame in self.frameObservations}
        if len(frame_by_id) != len(self.frameObservations):
            raise ValueError("duplicate frameId")
        for frame in self.frameObservations:
            window = by_window.get(frame.windowId)
            if window is None or frame.frameId not in window.selectedFrameIds:
                raise ValueError("frameId is not selected by its window")
            if frame.sceneId not in window.sceneIds:
                raise ValueError("unknown sceneId for frame")
            if not window.contextStartMs <= frame.timestampMs < window.contextEndMs:
                raise ValueError("frame timestamp outside window context")

        transcript_by_id = {t.transcriptId: t for t in self.transcripts}
        if len(transcript_by_id) != len(self.transcripts):
            raise ValueError("duplicate transcriptId")
        for transcript in self.transcripts:
            if transcript.endMs > self.durationMs:
                raise ValueError("transcript exceeds asset duration")

        analyses = {analysis.windowId: analysis for analysis in self.windowAnalyses}
        if len(analyses) != len(self.windowAnalyses) or set(analyses) != set(window_ids):
            raise ValueError("one WindowAnalysis is required per window")
        complete_ids = []
        for window in windows:
            analysis = analyses[window.windowId]
            if (analysis.startMs, analysis.endMs) != (window.startMs, window.endMs):
                raise ValueError("WindowAnalysis range differs from AnalysisWindow")
            if any(frame_id not in frame_by_id or frame_by_id[frame_id].windowId != window.windowId
                   for frame_id in analysis.frameObservationRefs):
                raise ValueError("unknown or foreign frame observation reference")
            if any(transcript_id not in transcript_by_id or
                   not (transcript_by_id[transcript_id].startMs < window.endMs and
                        transcript_by_id[transcript_id].endMs > window.startMs)
                   for transcript_id in analysis.transcriptRefs):
                raise ValueError("transcript reference does not overlap window")
            coverage = analysis.coverage
            if coverage.selectedFrames != len(window.selectedFrameIds):
                raise ValueError("selected frame coverage count mismatch")
            if coverage.successfulFrames != len(analysis.frameObservationRefs):
                raise ValueError("successful frame coverage count mismatch")
            if coverage.successfulFrames > coverage.selectedFrames:
                raise ValueError("successful frames exceed selected frames")
            if coverage.asrOverlapMs > window.endMs - window.startMs:
                raise ValueError("ASR overlap exceeds window duration")
            if coverage.visualComplete != (coverage.selectedFrames > 0 and
                                           coverage.successfulFrames == coverage.selectedFrames):
                raise ValueError("visualComplete conflicts with frame counts")
            if coverage.audioComplete and not analysis.transcriptRefs and (
                analysis.provenance.get("asr") is None or
                analysis.provenance["asr"].mode != "NO_SPEECH"
            ):
                raise ValueError("audioComplete without transcript requires NO_SPEECH provenance")
            overlaps = sorted(
                (max(window.startMs, transcript_by_id[transcript_id].startMs),
                 min(window.endMs, transcript_by_id[transcript_id].endMs))
                for transcript_id in analysis.transcriptRefs
            )
            overlap_ms = 0
            last_end = window.startMs
            for start, end in overlaps:
                overlap_ms += max(0, end - max(start, last_end))
                last_end = max(last_end, end)
            if coverage.asrOverlapMs != overlap_ms:
                raise ValueError("ASR overlap coverage does not match transcript references")
            if coverage.visualComplete and coverage.audioComplete:
                complete_ids.append(window.windowId)

        if {ref for a in analyses.values() for ref in a.frameObservationRefs} != set(frame_by_id):
            raise ValueError("frame observation is not referenced by a window")
        if {ref for a in analyses.values() for ref in a.transcriptRefs} != set(transcript_by_id):
            raise ValueError("transcript is not referenced by a window")

        if self.globalAnalysis.windowRefs != window_ids:
            raise ValueError("GlobalAnalysis must reference all windows in order")
        evidence_ids = set(window_ids) | set(frame_by_id) | set(transcript_by_id)
        finding_ids = [finding.findingId for finding in self.globalAnalysis.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("duplicate findingId")
        for finding in self.globalAnalysis.findings:
            if finding.endMs > self.durationMs or not set(finding.evidenceRefs) <= evidence_ids:
                raise ValueError("finding has an invalid range or evidence reference")
            for ref in finding.evidenceRefs:
                if ref in frame_by_id:
                    t = frame_by_id[ref].timestampMs
                    supported = finding.startMs <= t < finding.endMs
                elif ref in transcript_by_id:
                    transcript = transcript_by_id[ref]
                    supported = transcript.startMs < finding.endMs and transcript.endMs > finding.startMs
                else:
                    window = by_window[ref]
                    supported = window.startMs < finding.endMs and window.endMs > finding.startMs
                if not supported:
                    raise ValueError("finding evidence does not overlap its range")

        failed_ids = [window_id for window_id in window_ids if window_id not in complete_ids]
        if (self.coverage.totalWindows != len(windows) or
                self.coverage.completeWindows != len(complete_ids) or
                self.coverage.coveredMs != self.durationMs or
                self.coverage.failedWindowIds != failed_ids):
            raise ValueError("global coverage does not match windows")
        for failure in self.failureRanges:
            if failure.endMs > self.durationMs:
                raise ValueError("failure range exceeds asset duration")
        if self.analysisOutcome == "COMPLETE" and (failed_ids or self.failureRanges):
            raise ValueError("COMPLETE outcome contains missing evidence")
        if self.analysisOutcome == "PARTIAL" and not (failed_ids or self.failureRanges):
            raise ValueError("PARTIAL outcome has no recorded gap")
        if self.analysisOutcome == "PARTIAL" and self.reviewStatus != "NEEDS_REVIEW":
            raise ValueError("partial analysis requires review")
        if self.reviewStatus == "READY":
            all_sources = list(self.provenance.values())
            all_sources += [frame.source for frame in self.frameObservations]
            all_sources += [transcript.source for transcript in self.transcripts]
            all_sources += [source for a in self.windowAnalyses for source in a.provenance.values()]
            all_sources += list(self.globalAnalysis.provenance.values())
            if any(source.mode in {"SIMULATED", "MIXED", "UNAVAILABLE"} for source in all_sources):
                raise ValueError("READY result cannot rely on simulated or missing evidence")
        return self
