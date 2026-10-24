"""Synthetic semantic QA/revision tests. Declared REAL paths test policy, not live model quality."""

import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.agents import script_review_agent as review_module
from app.agents.script_review_agent import ScriptReviewAgent, ScriptReviewPolicy, review_prompt
from app.analysis.offline_id_director import run_offline
from app.analysis.offline_script_review import (
    RecordedReplies, ScriptReviewArtifact, agent_from_replay, review_offline,
)
from app.analysis.script_review import review_candidate, review_content_hash
from app.analysis.source_index import build_source_index
from app.schemas.script_contracts_v1 import Provenance, ScriptContractBundleV1, input_hash, script_hash

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = runpy.run_path(str(ROOT / "scripts/generate_script_review_fixture.py"))
BASE = runpy.run_path(str(ROOT / "scripts/generate_id_director_fixture.py"))
SIMULATED = Provenance(mode="SIMULATED", provider="local-stub", model=None, reason="Synthetic offline test")
# Deliberately declared REAL only to exercise the release policy with fictional
# data. No network, SDK, credentials or real acceptance evidence is involved.
DECLARED_REAL = Provenance(mode="REAL", provider="fictional-policy-test", model=None, reason="Not a real model run")


class Stub:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        value = self.responses.pop(0)
        if callable(value):
            value = value(prompt)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(content=json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value)


def grade(score=0.95, passed=True, severity=None, **extra):
    def reply(prompt):
        candidate = json.loads(prompt.split("\n当前候选：", 1)[1].rsplit("\n只输出", 1)[0])
        issues = []
        if severity:
            issues.append(dict(code="CONTEXT_LOSS", severity=severity, rowRefs=[candidate["rows"][-1]["rowId"]],
                unitRefs=candidate["rows"][-1]["sourceUnitRefs"], evidenceRefs=[],
                reason="Synthetic context issue", suggestion="Recheck the neighboring original evidence"))
        return dict(candidateHash=re.search(r"candidateHash：(sha256:[0-9a-f]{64})", prompt)[1],
                    passed=passed, overallScore=score, issues=issues, summary="Local synthetic assessment") | extra
    return reply


@pytest.fixture
def initial():
    return FIXTURE["build_replay"]()[0]


def run(initial, qa, revisions=None, *, source=SIMULATED, policy=None):
    reviewer = Stub(qa)
    reviser = Stub(revisions) if revisions is not None else None
    agent = ScriptReviewAgent(reviewer, reviewer_source=source, reviser=reviser,
        reviser_source=source if reviser else None, policy=policy)
    return review_offline(initial, agent), reviewer, reviser


def valid_revision():
    return FIXTURE["build_replay"]()[1].reviser.responses[0]


def test_replay_fixes_selection_then_reassesses_a_new_candidate():
    initial, replies = FIXTURE["build_replay"]()
    result = review_offline(initial, agent_from_replay(replies))
    review = result.review
    assert len(review.rounds) == 2 and len(review.revisions) == 1
    assert review.selectedRound == 2
    assert len(review.script.rows) == 3 and review.script.estimatedDurationMs == 7000
    assert review.rounds[0].candidate.scriptHash != review.rounds[1].candidate.scriptHash
    assert review.rounds[1].assessment.candidateHash == review.rounds[1].candidate.scriptHash
    assert review.script.quality.candidateHash == review.script.scriptHash
    assert review.status == "NEEDS_REVIEW" and not review.script.quality.passed
    assert "QA_UNAVAILABLE" not in {r.code for r in review.script.riskItems}
    ScriptReviewArtifact.model_validate_json(result.model_dump_json())
    ScriptContractBundleV1.model_validate_json(result.contract_bundle().model_dump_json())


def test_publication_has_explicit_two_hash_binding_and_identical_reviewed_content(initial):
    result, _, _ = run(initial, [grade()])
    round_ = result.review.rounds[0]
    published = result.review.script
    assert round_.assessment.candidateHash == round_.candidate.scriptHash
    assert round_.assessment.candidateHash != published.scriptHash
    assert round_.publication.reviewedCandidateHash == round_.assessment.candidateHash
    assert round_.publication.publishedCandidateHash == published.scriptHash
    assert review_content_hash(round_.candidate) == review_content_hash(published) == round_.publication.unchangedContentHash
    assert round_.candidate.rows[0].spokenQuotes == published.rows[0].spokenQuotes
    assert round_.candidate.rows[0].sourceParts == published.rows[0].sourceParts


def test_review_prompt_contains_full_original_and_unselected_context(initial):
    index, submission = initial.materialBuild.materialIndex, initial.submission
    candidate = review_candidate(index, initial.run.decision, submission, mode="RULE_BASELINE", source=None, revision=1)
    prompt = review_prompt(candidate, index, submission)
    assert "关机收好相机。" in prompt  # unselected original evidence
    assert "nextUnitId" in prompt and "previousUnitId" in prompt
    assert "REQUIRED" in prompt and "COARSE_BLOCK" in prompt
    assert candidate.scriptHash in prompt


@pytest.mark.parametrize("extra", [
    {"candidateHash": "sha256:" + "0" * 64}, {"clearRisks": []}, {"overallScore": "0.95"},
    {"passed": "true"}, {"overallScore": float("nan")}, {"sourceRange": {"startMs": 0, "endMs": 1}},
])
def test_invalid_assessment_cannot_acquire_quality_or_mutate_the_draft(initial, extra):
    result, qa, _ = run(initial, [grade(**extra)])
    assert result.review.rounds[0].outcome == "INVALID_ASSESSMENT"
    assert result.review.rounds[0].assessment is None
    assert result.review.script.quality is None
    assert result.review.status == "NEEDS_REVIEW"
    assert len(qa.prompts) == 1


@pytest.mark.parametrize("field", ["rowRefs", "unitRefs", "evidenceRefs"])
def test_unknown_issue_reference_is_rejected(initial, field):
    def invalid(prompt):
        value = grade(passed=False, severity="HIGH")(prompt)
        value["issues"][0][field] = ["foreign"]
        return value
    result, _, _ = run(initial, [invalid])
    assert result.review.stopReason == "INVALID_ASSESSMENT"
    assert result.review.script.quality is None


@pytest.mark.parametrize("response", ["not JSON", '{"passed":true,"passed":false}', "[" * 2000 + "]" * 2000])
def test_malformed_json_keeps_hard_valid_draft(initial, response):
    result, _, _ = run(initial, [response])
    assert result.review.rounds[0].outcome == "INVALID_ASSESSMENT"
    assert result.review.script.validationReport.hardPassed
    assert result.review.script.quality is None


def test_simulated_pass_and_original_coarse_risks_cannot_be_laundered(initial):
    result, _, _ = run(initial, [grade(1.0, True)])
    assert result.review.rounds[0].assessment.passed
    assert not result.review.script.quality.passed
    codes = {r.code for r in result.review.script.riskItems}
    assert codes >= {"SEMANTIC_REVIEW", "COARSE_ALIGNMENT", "UNTRUSTED_SOURCE", "SUBTITLE_UNAVAILABLE", "VISUAL_UNVERIFIED"}
    assert result.review.status == "NEEDS_REVIEW"


@pytest.mark.parametrize("score,passed,severity", [(0.99, False, None), (0.5, True, None), (1.0, True, "HIGH")])
def test_score_pass_flag_and_high_issues_jointly_constrain_quality(initial, score, passed, severity):
    result, _, _ = run(initial, [grade(score, passed, severity)], source=DECLARED_REAL)
    assert not result.review.script.quality.passed
    assert result.review.script.quality.issueRefs
    assert result.review.status == "NEEDS_REVIEW"


def trusted_fictional_initial():
    request = BASE["build_request"]()
    real = DECLARED_REAL
    old_ids = {s.sceneId: i for i, s in enumerate(request.sourceIndex.scenes)}
    request.sourceIndex = build_source_index(request.sourceIndex.assetRef,
        [s.sourceRange for s in request.sourceIndex.scenes], request.sourceIndex.detector, real)
    for frame in request.evidence.observations:
        frame.sceneId = request.sourceIndex.scenes[old_ids[frame.sceneId]].sceneId
        frame.source = real
    for transcript in request.evidence.transcripts:
        transcript.source = real
        transcript.timingQuality = "SENTENCE"
    return run_offline(request)


def test_ready_requires_real_declared_review_and_no_remaining_risks():
    result, _, _ = run(trusted_fictional_initial(), [grade()], source=DECLARED_REAL)
    assert result.review.status == "READY"
    assert result.review.script.riskItems == []
    assert result.review.script.quality.passed
    ScriptContractBundleV1.model_validate_json(result.contract_bundle().model_dump_json())


def test_simulated_qa_cannot_publish_ready_even_with_trusted_declared_evidence():
    result, _, _ = run(trusted_fictional_initial(), [grade()], source=SIMULATED)
    assert result.review.status == "NEEDS_REVIEW"
    assert not result.review.script.quality.passed


def test_real_declared_qa_cannot_launder_a_simulated_revision():
    initial = trusted_fictional_initial()
    qa = Stub([grade(0.5, False), grade()])
    revision = {"rows": [row.model_dump() for row in initial.run.decision.rows]}
    agent = ScriptReviewAgent(qa, reviewer_source=DECLARED_REAL,
        reviser=Stub([revision]), reviser_source=SIMULATED)
    result = review_offline(initial, agent)
    assert result.review.script.quality.passed
    assert result.review.status == "NEEDS_REVIEW"
    assert any("选材来自模拟模型" in risk.message for risk in result.review.script.riskItems)


def test_zero_threshold_is_not_replaced_by_default():
    result, _, _ = run(trusted_fictional_initial(), [grade(0.0)], source=DECLARED_REAL,
                       policy=ScriptReviewPolicy(qualityThreshold=0))
    assert result.review.status == "READY"


def test_medium_issue_stays_a_risk_even_when_semantic_score_passes(initial):
    result, _, _ = run(initial, [grade(0.95, True, "MEDIUM")], source=DECLARED_REAL)
    assert result.review.script.quality.passed
    assert result.review.status == "NEEDS_REVIEW"
    assert any("MEDIUM/CONTEXT_LOSS" in r.message for r in result.review.script.riskItems)


def test_no_reviewer_keeps_unreviewed_valid_draft(initial):
    result = review_offline(initial)
    assert result.review.stopReason == "QA_UNAVAILABLE"
    assert result.review.script.quality is None
    assert result.review.script.validationReport.hardPassed


@pytest.mark.parametrize("error,outcome", [(TimeoutError(), "MODEL_TIMEOUT"), (RuntimeError("private-transport-detail"), "MODEL_FAILED")])
def test_review_transport_failure_never_publishes_raw_error(initial, error, outcome):
    result, _, _ = run(initial, [error])
    assert result.review.stopReason == outcome
    assert result.review.script.quality is None
    assert "private-transport-detail" not in result.model_dump_json()


def test_invalid_revision_uses_remaining_attempt_before_reassessment(initial):
    bad = {"rows": [{"rowId": "bad", "sourceUnitRefs": ["foreign"], "narrativeRole": "OTHER",
                     "selectionReason": "test", "packagingSuggestions": []}]}
    result, qa, reviser = run(initial, [grade(0.5, False, "HIGH"), grade()], [bad, valid_revision()])
    assert len(qa.prompts) == 2 and len(reviser.prompts) == 2
    assert [r.outcome for r in result.review.revisions] == ["INVALID_PROPOSAL", "VALIDATED"]
    assert result.review.selectedRound == 2
    assert "未知单元 ID" in reviser.prompts[1]


def test_revision_failure_preserves_previously_reviewed_best_draft(initial):
    result, qa, _ = run(initial, [grade(0.7, False)], ["bad JSON", RuntimeError("private-revision-detail")])
    assert len(qa.prompts) == 1
    assert result.review.selectedRound == 1
    assert result.review.script.quality.overallScore == 0.7
    assert "private-revision-detail" not in result.model_dump_json()


def test_revision_cannot_add_free_time_or_fake_quote(initial):
    bad = valid_revision()
    bad["rows"][0]["originalText"] = "fabricated"
    result, qa, _ = run(initial, [grade(0.7, False)], [bad, bad])
    assert len(qa.prompts) == 1
    assert result.review.selectedRound == 1
    assert [a.outcome for a in result.review.revisions] == ["INVALID_PROPOSAL", "INVALID_PROPOSAL"]


def test_refusing_revision_does_not_delete_a_valid_script(initial):
    result, _, _ = run(initial, [grade(0.7, False)], [{"rows": []}])
    assert result.review.stopReason == "NO_SELECTION"
    assert result.review.script is not None
    assert result.review.selectedRound == 1


def test_best_candidate_is_selected_with_its_own_review_not_latest_round(initial):
    result, qa, reviser = run(initial, [grade(0.7, False), grade(0.5, False), grade(0.6, False)],
                              [valid_revision(), valid_revision()])
    assert len(qa.prompts) == 3 and len(reviser.prompts) == 2
    assert result.review.selectedRound == 1
    assert result.review.script.revision == 1
    assert result.review.script.quality.overallScore == 0.7
    ScriptReviewArtifact.model_validate_json(result.model_dump_json())


def test_clean_passing_revision_beats_higher_score_with_unresolved_issues():
    initial = trusted_fictional_initial()
    rows = {"rows": [row.model_dump() for row in initial.run.decision.rows]}
    result, _, _ = run(initial, [grade(0.99, True, "MEDIUM"), grade(0.86, True)],
                        [rows], source=DECLARED_REAL)
    assert result.review.selectedRound == 2
    assert result.review.status == "READY"
    assert result.review.script.quality.overallScore == 0.86


def test_later_qa_timeout_keeps_prior_nonblocking_best(initial):
    result, qa, _ = run(initial, [grade(0.7, False), TimeoutError()], [valid_revision()])
    assert len(qa.prompts) == 2
    assert result.review.selectedRound == 1
    assert result.review.script.quality.overallScore == 0.7
    assert result.review.rounds[1].assessment is None


def test_shared_budget_discards_late_qa_result(initial, monkeypatch):
    clock = [0]
    monkeypatch.setattr(review_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def late(prompt):
        clock[0] = 181
        return grade()(prompt)

    result, qa, reviser = run(initial, [late], [valid_revision()])
    assert result.review.stopReason == "BUDGET_EXHAUSTED"
    assert result.review.script.quality is None
    assert len(qa.prompts) == 1 and reviser.prompts == []


def test_shared_budget_discards_late_revision_and_keeps_assessed_draft(initial, monkeypatch):
    clock = [0]
    monkeypatch.setattr(review_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def late(_):
        clock[0] = 181
        return valid_revision()

    result, qa, _ = run(initial, [grade(0.7, False)], [late])
    assert result.review.stopReason == "BUDGET_EXHAUSTED"
    assert result.review.selectedRound == 1
    assert len(qa.prompts) == 1


@pytest.mark.parametrize("policy", [ScriptReviewPolicy(maxContextUnits=1), ScriptReviewPolicy(maxPromptChars=1000)])
def test_full_context_limit_skips_call_without_silent_truncation(initial, policy):
    result, qa, _ = run(initial, [], policy=policy)
    assert qa.prompts == []
    assert result.review.stopReason == "CAPACITY_EXCEEDED"
    assert len(result.initialArtifact.materialBuild.materialIndex.scenes) == 5


def test_response_size_limit_preserves_draft(initial):
    result, _, _ = run(initial, ["x" * 101], policy=ScriptReviewPolicy(maxResponseChars=100))
    assert result.review.stopReason == "INVALID_ASSESSMENT"
    assert result.review.script.quality is None


def test_max_round_policy_is_respected(initial):
    result, qa, reviser = run(initial, [grade(0.5, False)], [valid_revision()], policy=ScriptReviewPolicy(maxRounds=1))
    assert len(qa.prompts) == 1 and reviser.prompts == []
    assert result.review.stopReason == "REVISIONS_EXHAUSTED"


def test_mutated_policy_cannot_expand_calls(initial):
    qa = Stub([])
    agent = ScriptReviewAgent(qa, reviewer_source=SIMULATED)
    agent.policy.maxRounds = 50
    with pytest.raises(ValueError):
        review_offline(initial, agent)
    assert qa.prompts == []


def test_no_candidate_never_calls_review_or_reviser():
    request = BASE["build_request"]()
    request.submission.input.target.topic = "火星采矿"
    request.submission.inputHash = input_hash(request.submission)
    result, qa, reviser = run(run_offline(request), [], [])
    assert result.review.status == "NO_CANDIDATE"
    assert result.review.script is None
    assert qa.prompts == reviser.prompts == []


def test_reusing_agent_does_not_share_attempts_or_previous_grade(initial):
    qa = Stub([grade(), TimeoutError()])
    agent = ScriptReviewAgent(qa, reviewer_source=SIMULATED)
    first = review_offline(initial, agent)
    second = review_offline(initial, agent)
    assert len(first.review.rounds) == len(second.review.rounds) == 1
    assert first.review.script.quality is not None and second.review.script.quality is None


@pytest.mark.parametrize("mutation", ["assessment_hash", "publication_hash", "content", "grade", "risk"])
def test_saved_review_artifact_rejects_tampering_even_when_script_is_resealed(initial, mutation):
    result, _, _ = run(initial, [grade()])
    if mutation == "assessment_hash":
        result.review.rounds[0].assessment.candidateHash = result.review.script.scriptHash
    elif mutation == "publication_hash":
        result.review.rounds[0].publication.publishedCandidateHash = "sha256:" + "0" * 64
    elif mutation == "content":
        result.review.script.rows[0].spokenQuotes[0].text = "fabricated"
    elif mutation == "grade":
        result.review.script.quality.passed = True
    else:
        result.review.script.riskItems = [r for r in result.review.script.riskItems if r.code != "COARSE_ALIGNMENT"]
        result.review.script.validationReport.issueRefs = [r.riskId for r in result.review.script.riskItems]
        for row in result.review.script.rows:
            row.riskRefs = [r.riskId for r in result.review.script.riskItems if row.rowId in r.rowRefs]
    result.review.script.scriptHash = script_hash(result.review.script)
    result.review.script.quality.candidateHash = result.review.script.scriptHash
    result.review.script.validationReport.candidateHash = result.review.script.scriptHash
    with pytest.raises(ValueError):
        ScriptReviewArtifact.model_validate_json(result.model_dump_json())


def test_cli_recorded_replies_cannot_claim_real_source():
    with pytest.raises(ValueError, match="SIMULATED"):
        RecordedReplies(source=DECLARED_REAL, responses=[{}])


@pytest.mark.parametrize("role", ["reviewer", "reviser"])
def test_model_adapter_without_attribution_is_rejected(role):
    with pytest.raises(ValueError, match="attribution"):
        ScriptReviewAgent(**{role: Stub([])})


def test_generated_replay_cli_and_imports_are_offline(initial, tmp_path):
    for path, content in FIXTURE["render_files"]().items():
        assert path.read_text(encoding="utf-8") == content
    input_path = tmp_path / "initial.json"
    input_path.write_text(initial.model_dump_json(), encoding="utf-8")
    output, bundle = tmp_path / "review.json", tmp_path / "bundle.json"
    completed = subprocess.run([sys.executable, "-m", "app.analysis.offline_script_review", "--input", str(input_path),
        "--replies", str(ROOT / "docs/contracts/offline-script-review.replies.json"), "--output", str(output),
        "--bundle-output", str(bundle)], cwd=ROOT / "AgentCut-ai", capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout)["durationMs"] == 7000
    ScriptReviewArtifact.model_validate_json(output.read_text())
    ScriptContractBundleV1.model_validate_json(bundle.read_text())
    check = subprocess.run([sys.executable, "-c", "import sys; import app.analysis.offline_script_review; "
        "assert 'app.config' not in sys.modules; assert 'openai' not in sys.modules; "
        "assert 'langchain_openai' not in sys.modules"], cwd=ROOT / "AgentCut-ai", capture_output=True, text=True)
    assert check.returncode == 0, check.stderr
