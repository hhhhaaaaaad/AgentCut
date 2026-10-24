"""Fictional QA -> ID revision -> QA replay; never evidence of real model quality."""

import json
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "AgentCut-ai"))

from app.agents.id_director_agent import decision_from_rows
from app.analysis.offline_id_director import run_offline
from app.analysis.offline_script_review import RecordedReplies, ReviewReplay, agent_from_replay, review_offline
from app.analysis.script_review import ScriptAssessment, SemanticIssue, review_candidate
from app.analysis.source_index import stable_id
from app.schemas.script_contracts_v1 import DecisionRow, Provenance


def build_replay():
    request = runpy.run_path(str(ROOT / "scripts/generate_id_director_fixture.py"))["build_request"]()
    initial = run_offline(request)
    index, submission = initial.materialBuild.materialIndex, initial.submission
    simulated = Provenance(mode="SIMULATED", provider="hand-authored-review-fixture", model=None,
        reason="Recorded fictional review/revision; no model endpoint or media was accessed")
    first = review_candidate(index, initial.run.decision, submission, mode="RULE_BASELINE", source=None, revision=1)
    ending = next(u for u in index.units if "ending" in u.transcriptRefs)
    issue = SemanticIssue(code="CONTEXT_LOSS", severity="HIGH", rowRefs=[first.rows[-1].rowId],
        unitRefs=[ending.unitId], evidenceRefs=["ending"],
        reason="所选片段没有包含原文中的关机收纳提醒", suggestion="追加该完整单元作为结尾，保持原序原速")
    first_review = ScriptAssessment(candidateHash=first.scriptHash, passed=False, overallScore=0.55,
                                    issues=[issue], summary="虚构评审：建议补回原文已有的结尾提醒")
    rows = [r.model_copy(deep=True) for r in initial.run.decision.rows] + [DecisionRow(
        rowId=stable_id("row", {"inputHash": submission.inputHash, "unitId": ending.unitId}),
        sourceUnitRefs=[ending.unitId], narrativeRole="CONCLUSION", selectionReason="保留原文中的关机收纳提醒",
        packagingSuggestions=[])]
    revised = decision_from_rows(rows, index, submission)
    second = review_candidate(index, revised, submission, mode="MODEL_SELECTION", source=simulated, revision=2)
    second_review = ScriptAssessment(candidateHash=second.scriptHash, passed=True, overallScore=0.95,
                                     issues=[], summary="虚构评审通过；模拟来源不能升级为真实验收")
    replies = ReviewReplay(reviewer=RecordedReplies(source=simulated,
        responses=[first_review.model_dump(), second_review.model_dump()]),
        reviser=RecordedReplies(source=simulated, responses=[{"rows": [r.model_dump() for r in rows]}]))
    return initial, replies


def render_files():
    initial, replies = build_replay()
    artifact = review_offline(initial, agent_from_replay(replies))
    run = artifact.review
    summary = {"status": run.status, "rounds": len(run.rounds), "revisions": len(run.revisions),
        "selectedRound": run.selectedRound, "stopReason": run.stopReason,
        "durationMs": run.script.estimatedDurationMs, "qualityPassed": run.script.quality.passed,
        "rows": len(run.script.rows), "riskCodes": sorted({r.code for r in run.script.riskItems}),
        "publications": [r.publication.model_dump() for r in run.rounds]}
    return {
        ROOT / "docs/contracts/offline-script-review.replies.json": replies.model_dump_json(indent=2) + "\n",
        ROOT / "docs/contracts/offline-script-review.summary.json": json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        ROOT / "docs/contracts/offline-script-review.bundle.json": artifact.contract_bundle().model_dump_json(indent=2) + "\n",
    }


if __name__ == "__main__":
    for path, content in render_files().items():
        path.write_text(content, encoding="utf-8")
