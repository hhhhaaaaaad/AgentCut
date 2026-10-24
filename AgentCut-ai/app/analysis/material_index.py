"""Build selectable B1 units from complete source ranges and existing evidence.

No media decoding, ASR, model clients, or environment loading. Overlapping ASR
blocks stay in the evidence but cannot become independently selectable units.
"""

from bisect import bisect_left, bisect_right
from typing import Literal

from pydantic import Field, model_validator

from app.analysis.source_index import SourceIndex, planning_hash, seconds_to_ms, stable_id
from app.schemas.analysis import AnalysisReport
from app.schemas.script_contracts_v1 import (
    ArtifactRef, AssetRef, Contract, Dependency, Hash, Id, IndexTranscript, Integer,
    MaterialIndexV1, MaterialUnit, Observation, Positive, Provenance, Range,
    canonical_hash, index_hash, require, unique, valid_range, validate_index,
)

VERSION = "material-builder-0.1"
ZERO = "sha256:" + "0" * 64


class TranscriptDependency(Contract):
    transcriptId: Id
    dependsOnTranscriptId: Id
    kind: Literal["DEFINITION", "COREFERENCE", "CONDITION", "NEGATION", "CAUSE", "QUESTION_ANSWER"]
    level: Literal["REQUIRED", "REVIEW"]


class MaterialEvidence(Contract):
    evidenceVersion: Literal["material-evidence-0.1"] = "material-evidence-0.1"
    evidenceId: Id
    revision: Positive = 1
    assetRef: AssetRef
    upstreamAnalysisHash: Hash | None = None
    transcripts: list[IndexTranscript] = Field(default_factory=list, max_length=10000)
    observations: list[Observation] = Field(default_factory=list, max_length=10000)
    dependencies: list[TranscriptDependency] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def check_records(self):
        unique([t.transcriptId for t in self.transcripts], "transcriptId")
        unique([o.frameId for o in self.observations], "frameId")
        for record in self.transcripts:
            valid_range(record.sourceRange, self.assetRef.durationMs)
            require(record.source.mode in {"REAL", "SIMULATED", "MIXED"}, "speech provenance missing")
        refs = {t.transcriptId for t in self.transcripts}
        unique([(d.transcriptId, d.dependsOnTranscriptId) for d in self.dependencies], "dependency")
        for dependency in self.dependencies:
            require(dependency.transcriptId in refs and dependency.dependsOnTranscriptId in refs
                    and dependency.transcriptId != dependency.dependsOnTranscriptId, "unknown/self transcript dependency")
        return self


class ExcludedRange(Contract):
    sourceRange: Range
    transcriptRefs: list[Id]
    code: Literal["OVERLAPPING_TRANSCRIPTS"] = "OVERLAPPING_TRANSCRIPTS"


def _derive(source: SourceIndex, evidence: MaterialEvidence, version: int):
    require(source.assetRef == evidence.assetRef, "evidence asset binding mismatch")
    scenes = source.scenes
    by_scene = {s.sceneId: s for s in scenes}
    frames = sorted(evidence.observations, key=lambda o: (o.timestampMs, o.frameId))
    for frame in frames:
        scene = by_scene.get(frame.sceneId)
        require(scene is not None and scene.sourceRange.startMs <= frame.timestampMs < scene.sourceRange.endMs,
                "frame does not belong to source scene")
    records = sorted(evidence.transcripts, key=lambda t: (t.sourceRange.startMs, t.sourceRange.endMs, t.transcriptId))
    # Connected overlapping clusters cannot be represented as nonoverlapping,
    # whole-record units. Do not trim or deduplicate their original text.
    groups = []
    for record in records:
        if groups and record.sourceRange.startMs < groups[-1][1]:
            groups[-1][1] = max(groups[-1][1], record.sourceRange.endMs)
            groups[-1][2].append(record)
        else:
            groups.append([record.sourceRange.startMs, record.sourceRange.endMs, [record]])
    excluded = [ExcludedRange(sourceRange=Range(startMs=a, endMs=b),
                              transcriptRefs=[t.transcriptId for t in cluster])
                for a, b, cluster in groups if len(cluster) > 1]
    scene_starts = [s.sourceRange.startMs for s in scenes]
    scene_ends = [s.sourceRange.endMs for s in scenes]
    frame_times = [f.timestampMs for f in frames]
    units = []
    by_transcript = {}
    unknown = Provenance(mode="UNAVAILABLE", provider=None, model=None,
                         reason="No audio evidence establishes absence of speech in this visual interval")

    def append(start, end, record=None):
        selected_scenes = scenes[bisect_right(scene_ends, start):bisect_left(scene_starts, end)]
        selected_frames = frames[bisect_left(frame_times, start):bisect_left(frame_times, end)]
        identity = {"builder": VERSION, "assetHash": source.assetRef.assetHash,
                    "assetId": source.assetRef.assetId, "kind": "SPEECH" if record else "VISUAL_ONLY",
                    "range": {"startMs": start, "endMs": end},
                    "transcript": record.model_dump() if record else None}
        unit = MaterialUnit(
            unitId=stable_id("unit", identity), kind=identity["kind"],
            sourceRange=Range(startMs=start, endMs=end),
            originalText=record.text if record else "", timingQuality=record.timingQuality if record else "NONE",
            transcriptRefs=[record.transcriptId] if record else [],
            sceneRefs=[s.sceneId for s in selected_scenes], frameRefs=[f.frameId for f in selected_frames],
            asrSource=record.source.model_copy(deep=True) if record else unknown.model_copy(deep=True), dependencies=[],
        )
        units.append(unit)
        if record:
            by_transcript[record.transcriptId] = unit

    def visual_gap(start, end):
        for scene in scenes[bisect_right(scene_ends, start):bisect_left(scene_starts, end)]:
            append(max(start, scene.sourceRange.startMs), min(end, scene.sourceRange.endMs))

    cursor = 0
    for start, end, cluster in groups:
        if cursor < start:
            visual_gap(cursor, start)
        if len(cluster) == 1:
            append(start, end, cluster[0])
        cursor = end
    if cursor < source.assetRef.durationMs:
        visual_gap(cursor, source.assetRef.durationMs)
    require(len(units) <= 20000, "material unit capacity exceeded")
    for dependency in evidence.dependencies:
        require(dependency.transcriptId in by_transcript and dependency.dependsOnTranscriptId in by_transcript,
                "declared dependency refers to excluded overlapping transcript evidence")
        by_transcript[dependency.transcriptId].dependencies.append(Dependency(
            unitId=by_transcript[dependency.dependsOnTranscriptId].unitId,
            kind=dependency.kind, level=dependency.level,
        ))
    index = None
    if units:
        analysis_ref = ArtifactRef(artifactId=evidence.evidenceId, revision=evidence.revision,
                                   contentHash=canonical_hash(evidence.model_dump()))
        index = MaterialIndexV1(
            indexSchemaVersion="1.0", indexId=stable_id("material", {
                "builder": VERSION, "sourceIndexId": source.indexId, "evidenceId": evidence.evidenceId,
            }), indexVersion=version, indexHash=ZERO, assetRef=source.assetRef, analysisRef=analysis_ref,
            scenes=source.contract_scenes(), observations=frames, transcripts=records, units=units,
        )
        index.indexHash = index_hash(index)
        validate_index(index)
    return dict(
        materialIndex=index, excludedRanges=excluded,
        selectableCoverageMs=sum(u.sourceRange.endMs - u.sourceRange.startMs for u in units),
        status="NO_CANDIDATE" if index is None else "PARTIAL" if excluded else "INDEXED",
    )


class MaterialBuild(Contract):
    builderVersion: Literal["material-builder-0.1"] = VERSION
    sourceIndex: SourceIndex
    evidence: MaterialEvidence
    indexVersion: Positive = 1
    materialIndex: MaterialIndexV1 | None
    excludedRanges: list[ExcludedRange]
    selectableCoverageMs: Integer
    status: Literal["INDEXED", "PARTIAL", "NO_CANDIDATE"]

    @model_validator(mode="after")
    def replay(self):
        expected = _derive(self.sourceIndex, self.evidence, self.indexVersion)
        require(all(getattr(self, key) == value for key, value in expected.items()), "material build replay mismatch")
        return self


def build_material_index(source: SourceIndex, evidence: MaterialEvidence, *, index_version=1) -> MaterialBuild:
    source = SourceIndex.model_validate(source.model_dump())
    evidence = MaterialEvidence.model_validate(evidence.model_dump())
    # Validate version before building IDs/hashes.
    require(type(index_version) is int and 1 <= index_version <= 9007199254740991, "invalid index version")
    return MaterialBuild(sourceIndex=source, evidence=evidence, indexVersion=index_version,
                         **_derive(source, evidence, index_version))


def evidence_from_legacy(report: AnalysisReport, source: SourceIndex, *, evidence_id: str) -> MaterialEvidence:
    """Conservative bridge: no invented frame timestamps or sentence alignment.

    A legacy report has no verified asset hash. Keep simulated attribution;
    otherwise disclose MIXED binding, even if its original ASR claimed REAL.
    """
    report = AnalysisReport.model_validate(report.model_dump())
    source = SourceIndex.model_validate(source.model_dump())
    require(report.assetId == source.assetRef.assetId and seconds_to_ms(report.duration) == source.assetRef.durationMs,
            "legacy report asset/duration mismatch")
    original = report.provenance.get("asr", {})
    original_mode = original.get("mode") if isinstance(original, dict) else None
    # report.simulated may describe VLM only; a REAL ASR stage must not be
    # mislabeled SIMULATED just because the visual stage fell back.
    simulated = original_mode == "SIMULATED" or (original_mode is None and report.simulated)

    def attributed_text(key):
        value = original.get(key) if isinstance(original, dict) else None
        return value if isinstance(value, str) and value.strip() else None

    provenance = Provenance(
        mode="SIMULATED" if simulated else "MIXED",
        provider=attributed_text("provider") or "legacy-analysis-bridge", model=attributed_text("model"),
        reason="Legacy report has no independently verified asset hash or alignment quality; original blocks retained",
    )
    records = []
    for record in report.transcripts:
        records.append(IndexTranscript(
            transcriptId=stable_id("transcript", {"assetHash": source.assetRef.assetHash,
                "record": record.model_dump(), "adapter": VERSION}),
            sourceRange=Range(startMs=seconds_to_ms(record.start), endMs=seconds_to_ms(record.end)),
            text=record.text, timingQuality="COARSE_BLOCK", source=provenance.model_copy(deep=True),
        ))
    return MaterialEvidence(evidenceId=evidence_id, assetRef=source.assetRef,
                            upstreamAnalysisHash=planning_hash(report.model_dump()), transcripts=records)
