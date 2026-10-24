"""Hash-bound semantic assessment and deterministic publication metadata.

A model assesses an exact draft. Publication derives risks/quality from that
assessment without changing the reviewed content. Both hashes remain explicit.
"""

import math
from typing import Literal

from pydantic import Field

from app.analysis.script_compiler import VERSION as COMPILER_VERSION, compile_script
from app.analysis.source_index import stable_id
from app.schemas.script_contracts_v1 import (
    Contract, DirectorDecisionV1, EditingScriptV1, Hash, Id, MaterialIndexV1,
    Provenance, QualityReport, Risk, TaskSubmissionV1, Text, canonical_hash,
    require, script_hash, unique, validate_script,
)

VERSION = "script-semantic-review-0.1"


class SemanticIssue(Contract):
    code: Literal["TOPIC_RELEVANCE", "CONTEXT_LOSS", "UNSUPPORTED_CLAIM", "NARRATIVE_FLOW", "PACKAGING_RISK", "OTHER"]
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    rowRefs: list[Id] = Field(min_length=1, max_length=32)
    unitRefs: list[Id] = Field(min_length=1, max_length=32)
    evidenceRefs: list[Id] = Field(default_factory=list, max_length=64)
    reason: Text = Field(max_length=2000)
    suggestion: Text = Field(max_length=2000)


class ScriptAssessment(Contract):
    candidateHash: Hash
    passed: bool = Field(strict=True)
    overallScore: float = Field(ge=0, le=1, allow_inf_nan=False)
    issues: list[SemanticIssue] = Field(max_length=128)
    summary: str = Field(max_length=2000)


class ReviewPublication(Contract):
    reviewedCandidateHash: Hash
    publishedCandidateHash: Hash
    unchangedContentHash: Hash


def review_candidate(index, decision, submission, *, mode, source, revision):
    if mode == "RULE_BASELINE":
        note = "选材来源：规则基线；语义审核状态由 quality 与 reviewStatus 表示"
    else:
        require(source is not None and source.mode in {"REAL", "SIMULATED"}, "selection source missing")
        note = ("选材来源：模拟模型" if source.mode == "SIMULATED" else "选材来源：模型 ID 选择")
        note += "；语义审核状态由 quality 与 reviewStatus 表示"
    script = compile_script(index, decision, submission, selection_note=note)
    script.revision = revision
    script.scriptHash = script_hash(script)
    script.validationReport.candidateHash = script.scriptHash
    validate_script(script, index, decision)
    return script


def review_content_hash(script: EditingScriptV1):
    """Only derived review metadata is excluded. Times, quotes, notes stay bound."""
    value = script.model_dump(exclude={"riskItems", "quality", "validationReport", "reviewStatus", "scriptHash"})
    for row in value["rows"]:
        row.pop("riskRefs")
    return canonical_hash(value)


def validate_assessment(assessment, candidate, index):
    require(assessment.candidateHash == candidate.scriptHash, "assessment belongs to another candidate")
    rows = {r.rowId for r in candidate.rows}
    units = {u.unitId for u in index.units}
    evidence = {t.transcriptId for t in index.transcripts} | {f.frameId for f in index.observations} | {s.sceneId for s in index.scenes}
    for issue in assessment.issues:
        unique(issue.rowRefs, "semantic row reference")
        unique(issue.unitRefs, "semantic unit reference")
        unique(issue.evidenceRefs, "semantic evidence reference")
        require(set(issue.rowRefs) <= rows and set(issue.unitRefs) <= units, "semantic issue cites unknown evidence")
        require(set(issue.evidenceRefs) <= evidence, "semantic issue cites unknown raw evidence")


def semantic_passes(assessment, threshold):
    return (assessment is not None and assessment.passed and assessment.overallScore >= threshold
            and not any(i.severity == "HIGH" for i in assessment.issues))


def publish_review(candidate: EditingScriptV1, assessment: ScriptAssessment, index: MaterialIndexV1,
                   decision: DirectorDecisionV1, *, reviewer_source: Provenance, threshold: float,
                   selection_mode: str, selection_source: Provenance | None):
    """Project assessment into B1 metadata, preserving an explicit two-hash link.

    The raw model assessment is never rebound to the publication hash. Only the
    program-generated QualityReport describes the final metadata-bearing script.
    """
    candidate = EditingScriptV1.model_validate(candidate.model_dump())
    assessment = ScriptAssessment.model_validate(assessment.model_dump())
    validate_script(candidate, index, decision)
    validate_assessment(assessment, candidate, index)
    require(reviewer_source.mode in {"REAL", "SIMULATED"}, "review source missing")
    require(selection_mode in {"RULE_BASELINE", "MODEL_SELECTION"}
            and (selection_mode == "RULE_BASELINE" or
                 (selection_source is not None and selection_source.mode in {"REAL", "SIMULATED"})), "selection source missing")
    require(isinstance(threshold, (int, float)) and not isinstance(threshold, bool)
            and math.isfinite(threshold) and 0 <= threshold <= 1, "invalid review threshold")
    require(candidate.quality is None, "assessment must target an unreviewed draft")
    published = candidate.model_copy(deep=True)
    placeholders = {stable_id("risk", {"compiler": COMPILER_VERSION, "code": code, "rowId": None, "unitId": None})
                    for code in ("QA_UNAVAILABLE", "SEMANTIC_REVIEW")}
    require(placeholders <= {r.riskId for r in candidate.riskItems}, "review draft placeholders missing")
    published.riskItems = [r for r in published.riskItems if r.riskId not in placeholders]
    semantic_risks = []

    def add(message, *, rows=None, units=None, identity):
        risk = Risk(riskId=stable_id("risk", {"review": VERSION, "candidate": candidate.scriptHash, "issue": identity}),
                    code="SEMANTIC_REVIEW", level="REVIEW", rowRefs=rows or [], unitRefs=units or [], message=message)
        published.riskItems.append(risk)
        semantic_risks.append(risk.riskId)

    for issue in assessment.issues:
        add(f"[{issue.severity}/{issue.code}] {issue.reason}；建议：{issue.suggestion}",
            rows=issue.rowRefs, units=issue.unitRefs, identity=issue.model_dump())
    if not assessment.passed:
        add("语义评审未通过，保留可回查草稿", identity="QA_NOT_PASSED")
    if assessment.overallScore < threshold:
        add("语义评分低于当前质量阈值，仍需复核", identity="QA_BELOW_THRESHOLD")
    if reviewer_source.mode != "REAL":
        add("本轮语义评审为模拟来源，不能证明真实质量", identity="SIMULATED_REVIEW")
    if selection_mode == "MODEL_SELECTION" and selection_source.mode != "REAL":
        add("选材来自模拟模型，不能作为真实导演验收结果", identity="SIMULATED_SELECTION")
    for row in published.rows:
        row.riskRefs = [risk.riskId for risk in published.riskItems if row.rowId in risk.rowRefs]
    published.validationReport.issueRefs = [r.riskId for r in published.riskItems]
    published.scriptHash = script_hash(published)
    published.validationReport.candidateHash = published.scriptHash
    passed = semantic_passes(assessment, threshold) and reviewer_source.mode == "REAL"
    published.quality = QualityReport(candidateHash=published.scriptHash, passed=passed,
                                      overallScore=assessment.overallScore, issueRefs=semantic_risks)
    published.reviewStatus = "READY" if passed and not published.riskItems else "NEEDS_REVIEW"
    require(review_content_hash(candidate) == review_content_hash(published), "review projection changed content")
    validate_script(published, index, decision)
    return published, ReviewPublication(reviewedCandidateHash=candidate.scriptHash,
        publishedCandidateHash=published.scriptHash, unchangedContentHash=review_content_hash(candidate))
