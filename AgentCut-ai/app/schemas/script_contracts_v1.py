"""Additive B1 contracts. Offline readers only; no legacy endpoints are changed."""

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, model_validator


MAX_SAFE_INTEGER = 9007199254740991


def json_integer(value):
    # JSON Schema and JavaScript treat 1.0 as the integer 1.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


Integer = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER), BeforeValidator(json_integer)]
Positive = Annotated[int, Field(strict=True, ge=1, le=MAX_SAFE_INTEGER), BeforeValidator(json_integer)]
Id = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Hash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Timing = Literal["NONE", "COARSE_BLOCK", "SENTENCE", "WORD", "MANUAL"]
Mode = Literal["REAL", "SIMULATED", "MIXED", "NO_SPEECH", "UNAVAILABLE"]
Role = Literal["HOOK", "CONTEXT", "EXPLANATION", "EXAMPLE", "CONCLUSION", "OTHER"]
Phase = Literal["VALIDATING_INPUT", "PROBING", "TRANSCRIBING", "VISUAL_ANALYZING",
                "INDEXING", "PLANNING", "CHECKING", "PERSISTING", "COMPLETED", "FAILED"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Range(Contract):
    startMs: Integer
    endMs: Positive


class AssetRef(Contract):
    assetId: Id
    assetHash: Hash
    durationMs: Positive
    displayName: Text


class ArtifactRef(Contract):
    artifactId: Id
    revision: Positive
    contentHash: Hash


class IndexRef(Contract):
    indexId: Id
    indexVersion: Positive
    indexHash: Hash


class Provenance(Contract):
    mode: Mode
    provider: Text | None
    model: Text | None
    reason: Text | None


class Scene(Contract):
    sceneId: Id
    sourceRange: Range


class Observation(Contract):
    frameId: Id
    sceneId: Id
    timestampMs: Integer
    description: str
    source: Provenance


class Dependency(Contract):
    unitId: Id
    kind: Literal["DEFINITION", "COREFERENCE", "CONDITION", "NEGATION", "CAUSE", "QUESTION_ANSWER"]
    level: Literal["REQUIRED", "REVIEW"]


class IndexTranscript(Contract):
    transcriptId: Id
    sourceRange: Range
    text: Text
    timingQuality: Literal["COARSE_BLOCK", "SENTENCE", "WORD", "MANUAL"]
    source: Provenance


class MaterialUnit(Contract):
    unitId: Id
    kind: Literal["SPEECH", "VISUAL_ONLY"]
    sourceRange: Range
    originalText: str
    timingQuality: Timing
    transcriptRefs: list[Id]
    sceneRefs: list[Id] = Field(min_length=1)
    frameRefs: list[Id]
    asrSource: Provenance
    dependencies: list[Dependency]


class MaterialIndexV1(Contract):
    indexSchemaVersion: Literal["1.0"]
    indexId: Id
    indexVersion: Positive
    indexHash: Hash
    assetRef: AssetRef
    analysisRef: ArtifactRef
    scenes: list[Scene] = Field(min_length=1)
    observations: list[Observation]
    transcripts: list[IndexTranscript]
    units: list[MaterialUnit] = Field(min_length=1)


class Target(Contract):
    mode: Literal["TOPIC_EXTRACT"]
    topic: Text
    maxDurationMs: Positive
    desiredDurationMs: Positive | None
    aspectRatio: Literal["9:16", "16:9", "1:1", "4:3"]
    subtitleRequested: StrictBool
    style: str
    contentType: Literal["AUTO", "TUTORIAL_INTERVIEW", "VLOG_DOCUMENTARY", "FAST_SHORT_VIDEO"]
    editPolicy: Literal["ORIGINAL_ORDER_ORIGINAL_SPEED_HARD_CUT"]


class PackagingProposal(Contract):
    suggestionId: Id
    kind: Literal["TITLE", "EMPHASIS", "B_ROLL", "MUSIC", "ANIMATION", "CARD"]
    text: Text


class DecisionRow(Contract):
    rowId: Id
    sourceUnitRefs: list[Id] = Field(min_length=1)
    narrativeRole: Role
    selectionReason: Text
    packagingSuggestions: list[PackagingProposal]


class DirectorDecisionV1(Contract):
    decisionSchemaVersion: Literal["1.0"]
    decisionId: Id
    indexRef: IndexRef
    inputHash: Hash
    rows: list[DecisionRow] = Field(min_length=1)


class SourcePart(Contract):
    unitId: Id
    sourceRange: Range


class SpokenQuote(Contract):
    unitId: Id
    text: Text


class VisualEvidence(Contract):
    frameId: Id
    observedDescription: str


class ScriptRow(Contract):
    rowId: Id
    shotNo: Positive
    sourceUnitRefs: list[Id] = Field(min_length=1)
    sourceParts: list[SourcePart] = Field(min_length=1)
    outputRange: Range
    spokenQuotes: list[SpokenQuote]
    visualEvidence: list[VisualEvidence]
    narrativeRole: Role
    selectionReason: Text
    dependencyRefs: list[Id]
    riskRefs: list[Id]
    treatmentNote: str
    audioTreatment: Literal["ORIGINAL"]
    cutNotes: str


class CaptionCue(Contract):
    cueId: Id
    rowId: Id
    unitId: Id
    text: Text
    outputRange: Range
    timingQuality: Literal["SENTENCE", "WORD", "MANUAL"]


class PackagingSuggestion(PackagingProposal):
    rowId: Id
    status: Literal["PROPOSED", "ACCEPTED_MANUAL", "REJECTED"]


class Action(Contract):
    actionId: Id
    type: Literal["ORIGINAL_AUDIO", "CAPTION"]
    rowId: Id
    cueId: Id | None


class Risk(Contract):
    riskId: Id
    code: Literal["COARSE_ALIGNMENT", "UNTRUSTED_SOURCE", "VISUAL_UNVERIFIED",
                  "MISSING_DEPENDENCY", "SUBTITLE_UNAVAILABLE", "SEMANTIC_REVIEW", "QA_UNAVAILABLE"]
    level: Literal["REVIEW", "HARD"]
    rowRefs: list[Id]
    unitRefs: list[Id]
    message: Text


class ValidationReport(Contract):
    validationVersion: Text
    candidateHash: Hash
    hardPassed: StrictBool
    issueRefs: list[Id]


class QualityReport(Contract):
    candidateHash: Hash
    passed: StrictBool
    overallScore: Annotated[float, Field(ge=0, le=1)]
    issueRefs: list[Id]


class EditingScriptV1(Contract):
    scriptSchemaVersion: Literal["1.0"]
    scriptId: Id
    revision: Positive
    projectId: Id
    generationTaskId: Id
    assetRef: AssetRef
    indexRef: IndexRef
    inputHash: Hash
    target: Target
    title: Text
    rows: list[ScriptRow] = Field(min_length=1)
    estimatedDurationMs: Positive
    captionCues: list[CaptionCue]
    executableActions: list[Action]
    packagingSuggestions: list[PackagingSuggestion]
    manualNotes: str
    riskItems: list[Risk]
    scriptHash: Hash
    validationReport: ValidationReport
    quality: QualityReport | None
    reviewStatus: Literal["DRAFT", "NEEDS_REVIEW", "READY"]


class AnalyzeInputV1(Contract):
    inputSchemaVersion: Literal["1.0"]
    requestId: Id
    assetId: Id
    taskName: Text
    target: Target


class TaskSubmissionV1(Contract):
    protocolVersion: Literal["1.0"]
    messageType: Literal["ANALYZE_REQUEST"]
    taskId: Id
    projectId: Id
    runId: Id
    attempt: Positive
    inputHash: Hash
    configVersion: Text
    input: AnalyzeInputV1
    assetRef: AssetRef
    mediaObjectKey: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_./-]*$")]
    callbackUrl: Annotated[str, Field(pattern=r"^https?://[^\s]+$")]


class TaskError(Contract):
    code: Literal["INVALID_INPUT", "UNSUPPORTED_INPUT", "CONSTRAINT_CONFLICT", "NO_CANDIDATE",
                  "MODEL_TIMEOUT", "MODEL_FAILED", "VALIDATION_FAILED", "CAPACITY_EXCEEDED",
                  "INTERNAL_ERROR", "SUBMISSION_UNCERTAIN"]
    message: Text
    retryable: StrictBool


class ResultRefs(Contract):
    analysis: ArtifactRef
    materialIndex: ArtifactRef
    script: ArtifactRef


class TaskEventV1(Contract):
    protocolVersion: Literal["1.0"]
    event: Literal["PROGRESS", "COMPLETED"]
    eventId: Id
    requestId: Id
    taskId: Id
    projectId: Id
    assetId: Id
    assetHash: Hash
    runId: Id
    attempt: Positive
    inputHash: Hash
    sequence: Positive
    heartbeatAt: Annotated[str, Field(pattern=r"^[1-9][0-9]{3}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")]
    phase: Phase
    progress: Annotated[int, Field(strict=True, ge=0, le=100), BeforeValidator(json_integer)]
    executionStatus: Literal["RUNNING", "SUCCESS", "FAILED"]
    analysisOutcome: Literal["NONE", "COMPLETE", "PARTIAL"]
    reviewStatus: Literal["NOT_AVAILABLE", "READY", "NEEDS_REVIEW"]
    resultRefs: ResultRefs | None
    error: TaskError | None


def canonical_hash(value: dict) -> str:
    """All hashed objects have ASCII keys and only safe integers, text, bool, null."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def index_hash(index: MaterialIndexV1) -> str:
    return canonical_hash(index.model_dump(exclude={"indexHash"}))


def input_hash(submission: TaskSubmissionV1) -> str:
    return canonical_hash({
        "projectId": submission.projectId,
        "assetRef": submission.assetRef.model_dump(),
        "configVersion": submission.configVersion,
        "input": submission.input.model_dump(exclude={"requestId"}),
    })


def script_hash(script: EditingScriptV1) -> str:
    return canonical_hash(script.model_dump(exclude={"scriptHash", "validationReport", "quality", "reviewStatus"}))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique(values, field):
    require(len(values) == len(set(values)), f"duplicate {field}")


def valid_range(value: Range, duration):
    require(value.startMs < value.endMs <= duration, "invalid source/output range")


def validate_index(index: MaterialIndexV1):
    require(index.indexHash == index_hash(index), "indexHash mismatch")
    unique([s.sceneId for s in index.scenes], "sceneId")
    unique([f.frameId for f in index.observations], "frameId")
    unique([t.transcriptId for t in index.transcripts], "transcriptId")
    unique([u.unitId for u in index.units], "unitId")
    scenes = {s.sceneId: s for s in index.scenes}
    frames = {f.frameId: f for f in index.observations}
    units = {u.unitId: u for u in index.units}
    transcripts = {t.transcriptId: t for t in index.transcripts}
    for transcript in index.transcripts:
        valid_range(transcript.sourceRange, index.assetRef.durationMs)
        require(transcript.source.mode in ("REAL", "SIMULATED", "MIXED"), "transcript requires attributed speech")
    next_start = 0
    for scene in index.scenes:
        valid_range(scene.sourceRange, index.assetRef.durationMs)
        require(scene.sourceRange.startMs == next_start, "scene index must cover the whole asset")
        next_start = scene.sourceRange.endMs
    require(next_start == index.assetRef.durationMs, "scene index must cover the whole asset")
    for frame in index.observations:
        scene = scenes.get(frame.sceneId)
        require(scene is not None and scene.sourceRange.startMs <= frame.timestampMs < scene.sourceRange.endMs,
                "frame must belong to its scene")
    previous_end = 0
    for unit in index.units:
        valid_range(unit.sourceRange, index.assetRef.durationMs)
        require(unit.sourceRange.startMs >= previous_end, "units must be ordered and nonoverlapping")
        previous_end = unit.sourceRange.endMs
        for values in [unit.transcriptRefs, unit.sceneRefs, unit.frameRefs]:
            unique(values, "unit reference")
        require(all(ref in scenes and scenes[ref].sourceRange.startMs < unit.sourceRange.endMs
                    and unit.sourceRange.startMs < scenes[ref].sourceRange.endMs for ref in unit.sceneRefs),
                "unit scene reference must overlap")
        require(all(ref in frames and frames[ref].sceneId in unit.sceneRefs
                    and unit.sourceRange.startMs <= frames[ref].timestampMs < unit.sourceRange.endMs
                    for ref in unit.frameRefs), "unit frame reference is foreign")
        if unit.kind == "SPEECH":
            require(bool(unit.originalText.strip()) and bool(unit.transcriptRefs) and unit.timingQuality != "NONE"
                    and unit.asrSource.mode in ("REAL", "SIMULATED", "MIXED"), "speech requires attributed transcript")
            require(all(ref in transcripts for ref in unit.transcriptRefs), "unknown transcript reference")
            records = [transcripts[ref] for ref in unit.transcriptRefs]
            require(unit.sourceRange.startMs == records[0].sourceRange.startMs
                    and unit.sourceRange.endMs == records[-1].sourceRange.endMs
                    and all(a.sourceRange.endMs == b.sourceRange.startMs for a, b in zip(records, records[1:])),
                    "unit must preserve whole contiguous transcript records")
            require(unit.originalText == "".join(t.text for t in records), "unit text differs from transcript evidence")
            ranks = {"COARSE_BLOCK": 1, "SENTENCE": 2, "WORD": 3, "MANUAL": 4}
            require(ranks[unit.timingQuality] <= min(ranks[t.timingQuality] for t in records), "cannot invent finer ASR alignment")
            modes = {t.source.mode for t in records}
            require(unit.asrSource.mode == (next(iter(modes)) if len(modes) == 1 else "MIXED"), "unit ASR provenance mismatch")
        else:
            require(unit.originalText == "" and not unit.transcriptRefs and unit.timingQuality == "NONE"
                    and unit.asrSource.mode in ("NO_SPEECH", "UNAVAILABLE"), "visual-only unit cannot invent speech")
            if unit.asrSource.mode == "NO_SPEECH":
                require(not any(t.sourceRange.startMs < unit.sourceRange.endMs and unit.sourceRange.startMs < t.sourceRange.endMs
                                for t in index.transcripts), "NO_SPEECH contradicts indexed transcript")
        unique([d.unitId for d in unit.dependencies], "dependency")
        require(all(d.unitId in units and d.unitId != unit.unitId for d in unit.dependencies), "unknown/self dependency")


def validate_decision(decision: DirectorDecisionV1, index: MaterialIndexV1):
    require(decision.indexRef == IndexRef(indexId=index.indexId, indexVersion=index.indexVersion,
                                        indexHash=index.indexHash), "decision index binding mismatch")
    unique([r.rowId for r in decision.rows], "rowId")
    unique([p.suggestionId for r in decision.rows for p in r.packagingSuggestions], "suggestionId")
    units = {u.unitId: u for u in index.units}
    selected = [ref for row in decision.rows for ref in row.sourceUnitRefs]
    unique(selected, "selected unit")
    require(all(ref in units for ref in selected), "unknown selected unit")
    previous_end = 0
    for row in decision.rows:
        row_units = [units[ref] for ref in row.sourceUnitRefs]
        require(row_units[0].sourceRange.startMs >= previous_end, "source order changed or overlaps")
        for left, right in zip(row_units, row_units[1:]):
            require(left.sourceRange.endMs == right.sourceRange.startMs, "noncontiguous units must use separate rows")
        previous_end = row_units[-1].sourceRange.endMs
    for ref in selected:
        require(all(d.level != "REQUIRED" or d.unitId in selected for d in units[ref].dependencies),
                "required dependency removed")


def validate_script(script: EditingScriptV1, index: MaterialIndexV1, decision: DirectorDecisionV1):
    require(script.assetRef == index.assetRef and script.indexRef == decision.indexRef
            and script.inputHash == decision.inputHash, "script input/index binding mismatch")
    require(script.scriptHash == script_hash(script), "scriptHash mismatch")
    require(script.validationReport.candidateHash == script.scriptHash, "validation belongs to another candidate")
    require(script.quality is None or script.quality.candidateHash == script.scriptHash, "QA belongs to another candidate")
    require(script.target.desiredDurationMs is None or script.target.desiredDurationMs <= script.target.maxDurationMs,
            "desired duration exceeds hard maximum")
    require([r.rowId for r in script.rows] == [r.rowId for r in decision.rows], "script rows differ from decision")
    unique([r.riskId for r in script.riskItems], "riskId")
    unique([c.cueId for c in script.captionCues], "cueId")
    unique([a.actionId for a in script.executableActions], "actionId")
    unique([p.suggestionId for p in script.packagingSuggestions], "suggestionId")
    units = {u.unitId: u for u in index.units}
    frames = {f.frameId: f for f in index.observations}
    rows = {r.rowId: r for r in script.rows}
    risks = {r.riskId: r for r in script.riskItems}
    selected = {ref for row in script.rows for ref in row.sourceUnitRefs}
    for risk in script.riskItems:
        unique(risk.rowRefs, "risk row reference")
        unique(risk.unitRefs, "risk unit reference")
        require(all(ref in rows for ref in risk.rowRefs) and all(ref in units for ref in risk.unitRefs),
                "unknown risk reference")
    require(set(script.validationReport.issueRefs) == set(risks), "validation must list all risks")
    require(script.validationReport.hardPassed == (not any(r.level == "HARD" for r in risks.values())),
            "hard gate and hard risks disagree")
    if script.quality is not None:
        unique(script.quality.issueRefs, "QA issue reference")
        require(all(ref in risks for ref in script.quality.issueRefs), "unknown QA risk reference")
        require(script.quality.passed or bool(script.quality.issueRefs), "failed QA requires risk references")
    elapsed = 0
    risky_source = False
    for number, (row, chosen) in enumerate(zip(script.rows, decision.rows), 1):
        require(row.shotNo == number and row.sourceUnitRefs == chosen.sourceUnitRefs
                and row.narrativeRole == chosen.narrativeRole and row.selectionReason == chosen.selectionReason,
                "script decision projection changed")
        row_units = [units[ref] for ref in row.sourceUnitRefs]
        require(row.sourceParts == [SourcePart(unitId=u.unitId, sourceRange=u.sourceRange) for u in row_units],
                "source parts must map whole index units")
        length = sum(u.sourceRange.endMs - u.sourceRange.startMs for u in row_units)
        require(row.outputRange == Range(startMs=elapsed, endMs=elapsed + length), "output time must be cumulative original speed")
        elapsed += length
        require(row.spokenQuotes == [SpokenQuote(unitId=u.unitId, text=u.originalText)
                                    for u in row_units if u.kind == "SPEECH"], "spoken quote differs from original")
        frame_ids = list(dict.fromkeys(ref for u in row_units for ref in u.frameRefs))
        require(row.visualEvidence == [VisualEvidence(frameId=ref, observedDescription=frames[ref].description)
                                       for ref in frame_ids], "visual fact differs from indexed observation")
        dependencies = list(dict.fromkeys(d.unitId for u in row_units for d in u.dependencies))
        require(row.dependencyRefs == dependencies, "dependency projection changed")
        unique(row.riskRefs, "row risk reference")
        require(set(row.riskRefs) == {r.riskId for r in risks.values() if row.rowId in r.rowRefs}, "row risk projection changed")
        for unit in row_units:
            codes = {r.code for r in risks.values() if row.rowId in r.rowRefs and unit.unitId in r.unitRefs}
            if unit.timingQuality == "COARSE_BLOCK":
                require("COARSE_ALIGNMENT" in codes, "coarse alignment must be disclosed")
            if unit.asrSource.mode not in ("REAL", "NO_SPEECH"):
                require("UNTRUSTED_SOURCE" in codes, "untrusted ASR must be disclosed")
                risky_source = True
            if not unit.frameRefs or any(frames[ref].source.mode != "REAL" for ref in unit.frameRefs):
                require("VISUAL_UNVERIFIED" in codes, "unverified visual evidence must be disclosed")
                risky_source = True
            if any(d.level == "REVIEW" and d.unitId not in selected for d in unit.dependencies):
                require("MISSING_DEPENDENCY" in codes, "missing review dependency must be disclosed")
    require(elapsed == script.estimatedDurationMs <= script.target.maxDurationMs, "duration must be exact and within hard maximum")
    cues = {c.cueId: c for c in script.captionCues}
    cue_units = set()
    previous_caption_end = 0
    for cue in script.captionCues:
        row = rows.get(cue.rowId)
        unit = units.get(cue.unitId)
        require(row is not None and cue.unitId in row.sourceUnitRefs and unit.kind == "SPEECH"
                and unit.asrSource.mode == "REAL" and cue.timingQuality == unit.timingQuality,
                "caption requires reliable original alignment")
        require(cue.unitId not in cue_units and cue.text == unit.originalText, "caption must quote an entire aligned unit once")
        cue_units.add(cue.unitId)
        offset = sum(units[ref].sourceRange.endMs - units[ref].sourceRange.startMs
                     for ref in row.sourceUnitRefs[:row.sourceUnitRefs.index(cue.unitId)])
        require(cue.outputRange == Range(startMs=row.outputRange.startMs + offset,
                                       endMs=row.outputRange.startMs + offset + unit.sourceRange.endMs - unit.sourceRange.startMs),
                "caption must use global output time")
        require(cue.outputRange.startMs >= previous_caption_end, "captions must be ordered without overlap")
        previous_caption_end = cue.outputRange.endMs
    if script.target.subtitleRequested:
        for row in script.rows:
            for ref in row.sourceUnitRefs:
                if units[ref].kind == "SPEECH" and ref not in cue_units:
                    require(any(r.code == "SUBTITLE_UNAVAILABLE" and row.rowId in r.rowRefs and ref in r.unitRefs
                                for r in risks.values()), "unmet subtitle requirement must be disclosed")
    used_cues = []
    audio_rows = []
    for action in script.executableActions:
        require(action.rowId in rows, "action references unknown row")
        if action.type == "CAPTION":
            require(action.cueId in cues and cues[action.cueId].rowId == action.rowId, "action references foreign caption")
            used_cues.append(action.cueId)
        else:
            require(action.cueId is None, "audio action cannot reference caption")
            audio_rows.append(action.rowId)
    require(sorted(used_cues) == sorted(cues), "each caption must have exactly one action")
    require(sorted(audio_rows) == sorted(rows), "each row must preserve original audio exactly once")
    proposed = [(r.rowId, p) for r in decision.rows for p in r.packagingSuggestions]
    require(len(proposed) == len(script.packagingSuggestions), "packaging projection changed")
    for (row_id, proposal), suggestion in zip(proposed, script.packagingSuggestions):
        require(suggestion.rowId == row_id and proposal.model_dump() == suggestion.model_dump(exclude={"rowId", "status"}),
                "packaging proposal changed")
    if script.reviewStatus == "READY":
        require(script.validationReport.hardPassed and not risks and not risky_source
                and script.quality is not None and script.quality.passed, "READY requires hard and semantic review")
    if script.quality is None:
        require(any(r.code == "QA_UNAVAILABLE" for r in risks.values()), "missing QA must be disclosed")


def validate_submission(submission: TaskSubmissionV1):
    require(submission.input.assetId == submission.assetRef.assetId, "selected asset mismatch")
    require(submission.inputHash == input_hash(submission), "inputHash mismatch")
    target = submission.input.target
    require(target.desiredDurationMs is None or target.desiredDurationMs <= target.maxDurationMs,
            "desired duration exceeds hard maximum")
    require(all(part not in ("", ".", "..") for part in submission.mediaObjectKey.split("/")),
            "media key must be an object key, not a filesystem path")


def validate_event(event: TaskEventV1, submission: TaskSubmissionV1):
    datetime.strptime(event.heartbeatAt, "%Y-%m-%dT%H:%M:%SZ")
    for field in ("taskId", "projectId", "runId", "attempt", "inputHash"):
        require(getattr(event, field) == getattr(submission, field), "event belongs to another run/input")
    require(event.requestId == submission.input.requestId and event.assetId == submission.assetRef.assetId
            and event.assetHash == submission.assetRef.assetHash, "event input identity mismatch")
    if event.event == "PROGRESS":
        require(event.executionStatus == "RUNNING" and event.progress < 100
                and event.phase not in ("COMPLETED", "FAILED") and event.analysisOutcome == "NONE"
                and event.reviewStatus == "NOT_AVAILABLE" and event.resultRefs is None and event.error is None,
                "progress cannot publish a terminal result")
    elif event.executionStatus == "SUCCESS":
        require(event.progress == 100 and event.phase == "COMPLETED" and event.analysisOutcome in ("COMPLETE", "PARTIAL")
                and event.reviewStatus in ("READY", "NEEDS_REVIEW") and event.resultRefs is not None and event.error is None,
                "successful completion requires qualified result references")
        require(event.analysisOutcome != "PARTIAL" or event.reviewStatus == "NEEDS_REVIEW", "partial result cannot be READY")
    else:
        require(event.executionStatus == "FAILED" and event.phase == "FAILED" and event.progress < 100
                and event.analysisOutcome == "NONE" and event.reviewStatus == "NOT_AVAILABLE"
                and event.resultRefs is None and event.error is not None, "failure cannot carry a normal result")


class ScriptContractBundleV1(Contract):
    """Conformance bundle supplies the immutable context needed for reference checks."""
    materialIndex: MaterialIndexV1 | None
    decision: DirectorDecisionV1 | None
    script: EditingScriptV1 | None
    submission: TaskSubmissionV1
    events: list[TaskEventV1]

    @model_validator(mode="after")
    def validate_bundle(self):
        validate_submission(self.submission)
        if self.materialIndex is not None:
            validate_index(self.materialIndex)
            require(self.materialIndex.assetRef == self.submission.assetRef, "index asset binding mismatch")
        if self.decision is not None:
            require(self.materialIndex is not None, "decision requires its index context")
            validate_decision(self.decision, self.materialIndex)
            require(self.decision.inputHash == self.submission.inputHash, "decision input binding mismatch")
        if self.script is not None:
            require(self.decision is not None, "script requires its decision context")
            validate_script(self.script, self.materialIndex, self.decision)
            require(self.script.projectId == self.submission.projectId
                    and self.script.generationTaskId == self.submission.taskId
                    and self.script.target == self.submission.input.target, "script task/target binding mismatch")
        unique([e.eventId for e in self.events], "accepted eventId")
        progress, sequence, terminal = 0, 0, False
        for event in self.events:
            validate_event(event, self.submission)
            require(not terminal and event.sequence > sequence and event.progress >= progress,
                    "accepted history cannot regress or revive a terminal task")
            progress, sequence = event.progress, event.sequence
            terminal = event.event == "COMPLETED"
            if event.executionStatus == "SUCCESS":
                require(self.script is not None and self.materialIndex is not None, "successful result requires artifacts")
                require(self.script.validationReport.hardPassed, "hard-invalid script cannot be a successful result")
                refs = event.resultRefs
                require(refs.analysis == self.materialIndex.analysisRef, "analysis result binding mismatch")
                require(refs.materialIndex == ArtifactRef(artifactId=self.materialIndex.indexId,
                        revision=self.materialIndex.indexVersion, contentHash=self.materialIndex.indexHash), "index result binding mismatch")
                require(refs.script == ArtifactRef(artifactId=self.script.scriptId,
                        revision=self.script.revision, contentHash=self.script.scriptHash), "script result binding mismatch")
                expected = "READY" if self.script.reviewStatus == "READY" else "NEEDS_REVIEW"
                require(event.reviewStatus == expected, "event review state differs from script")
            if event.executionStatus == "FAILED":
                require(self.script is None and self.decision is None and self.materialIndex is None,
                        "failed result cannot carry qualified artifacts")
        return self
