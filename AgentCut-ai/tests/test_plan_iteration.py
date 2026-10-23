"""受控 Agent 决策回归：只注入本地 stub，不连接模型或读取凭证。"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import config
from app.agents import plan_agent as plan_module
from app.agents.plan_agent import PlanAgent
from app.agents.plan_run import candidate_hash
from app.agents.quality_agent import QualityAgent
from app.agents.validator import DeterministicValidator
from app.api import analyze
from app.schemas.analysis import AnalysisReport, HighlightClip, Scene, TranscriptSegment
from app.schemas.plan import OpSpeed, Plan
from app.schemas.quality import QualityReview


def report():
    return AnalysisReport(
        assetId="asset_test", videoUrl="file:///source.mp4", duration=10.0,
        width=1920, height=1080, fps=30.0,
        scenes=[Scene(index=10, start=0.0, end=5.0, description="桌上展示蓝色相机"),
                Scene(index=20, start=5.0, end=10.0, description="镜头盖操作")],
        transcripts=[TranscriptSegment(index=0, start=0.5, end=4.0, text="先取下镜头盖再开机")],
        provenance={"asr": {"mode": "REAL"}, "vlm": {"mode": "REAL"}},
    )


def target(**overrides):
    values = dict(aspectRatio="16:9", maxDuration=None, addSubtitle=False, style="", qualityThreshold=None)
    return SimpleNamespace(**(values | overrides))


def plan(title="first"):
    result = PlanAgent(llm=object())._build_deterministic(report(), target(), "p")
    result.title = title
    return result


def review(score=0.9, passed=True, *, high=False):
    return dict(
        overallScore=score, passed=passed, dimensionScores=[], summary="本地测试",
        issues=[dict(dimension="pacing", severity="high", reason="严重问题", suggestion="修正节奏")]
        if high else [],
    )


class StubLLM:
    def __init__(self, plans, reviews=()):
        self.plans = list(plans)
        self.reviews = list(reviews)
        self.director_prompts = []
        self.quality_prompts = []

    def invoke(self, prompt):
        if prompt.startswith("你是 AgentCut 的质量监督"):
            self.quality_prompts.append(prompt)
            item = self.reviews.pop(0)
        else:
            self.director_prompts.append(prompt)
            item = self.plans.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, Plan):
            text = item.to_contract_json()
        elif isinstance(item, dict):
            text = json.dumps(item, ensure_ascii=False)
        else:
            text = item
        return SimpleNamespace(content=text)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(config, "SIMULATE_FORCED", False)
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "QA_TIME_BUDGET_SECONDS", 600)


def execute(stub, **constraints):
    agent = PlanAgent(llm=stub)
    result = agent.run(report(), target(**constraints), "p")
    assert agent.last_run.selectedCandidateHash == candidate_hash(result)
    assert agent.last_run.validation.valid
    if agent.last_quality is not None:
        assert agent.last_quality.candidateHash == candidate_hash(result)
    return agent, result


def test_ready_requires_hard_and_semantic_review_of_same_candidate():
    stub = StubLLM([plan()], [review()])
    agent, result = execute(stub)
    assert agent.last_run.reviewStatus == "READY"
    assert agent.last_run.stopReason == "QUALITY_ACCEPTED"
    assert agent.last_run.selectedIteration == 1
    assert agent.last_run.reviewReasons == []
    assert agent.last_run.attempts[0].quality.candidateHash == candidate_hash(result)


def test_invalid_candidate_is_repaired_before_spending_qa_call():
    bad = plan("bad")
    bad.timeline[0].sourceRange.end = 99
    stub = StubLLM([bad, plan("fixed")], [review()])
    agent, result = execute(stub)
    assert result.title == "fixed"
    assert len(stub.quality_prompts) == 1
    assert "source_range_bounds" in stub.director_prompts[1]
    assert [a.outcome for a in agent.last_run.attempts] == ["VALIDATION_FAILED", "REVIEWED"]


def test_bad_json_can_be_revised_with_schema_feedback():
    stub = StubLLM(["not JSON", plan("fixed")], [review()])
    agent, result = execute(stub)
    assert result.title == "fixed"
    assert "JSON 结构校验" in stub.director_prompts[1]
    assert agent.last_run.attempts[0].outcome == "GENERATION_FAILED"


def test_later_generation_failures_preserve_prior_best_plan_and_qa():
    stub = StubLLM([plan("best"), "bad JSON", RuntimeError("offline failure")], [review(0.7, False)])
    agent, result = execute(stub)
    assert result.title == "best"
    assert agent.last_plan_source == "REAL"
    assert agent.last_quality.overallScore == 0.7
    assert agent.last_run.selectedIteration == 1
    assert agent.last_run.reviewStatus == "NEEDS_REVIEW"
    assert len(stub.director_prompts) == 3


def test_invalid_later_candidates_cannot_replace_valid_candidate():
    bad = plan("bad")
    bad.source.duration = 999
    stub = StubLLM([plan("best"), bad, bad], [review(0.7, False)])
    agent, result = execute(stub)
    assert result.title == "best"
    assert len(stub.quality_prompts) == 1
    assert agent.last_run.selectedIteration == 1


def test_candidate_with_no_blocking_issue_beats_higher_score_with_high_issue():
    stub = StubLLM([plan("best"), plan("blocked"), plan("worse")],
                   [review(0.7, False), review(0.99, True, high=True), review(0.6, False)])
    agent, result = execute(stub)
    assert result.title == "best"
    assert agent.last_quality.overallScore == 0.7


@pytest.mark.parametrize("qa,reason", [
    (review(0.99, False), "QA_NOT_PASSED"),
    (review(0.6, True), "QA_BELOW_THRESHOLD"),
    (review(0.99, True, high=True), "QA_BLOCKING_ISSUES"),
])
def test_score_flag_and_blocking_issues_all_constrain_acceptance(qa, reason):
    stub = StubLLM([plan("a"), plan("b"), plan("c")], [qa, qa, qa])
    agent, _ = execute(stub)
    assert len(stub.director_prompts) == 3
    assert agent.last_run.reviewStatus == "NEEDS_REVIEW"
    assert reason in agent.last_run.reviewReasons
    assert not agent.last_quality.passed
    assert agent.last_run.attempts[0].quality.passed == qa["passed"]


def test_zero_quality_threshold_is_preserved():
    agent, _ = execute(StubLLM([plan()], [review(0.0, True)]), qualityThreshold=0)
    assert agent.last_run.reviewStatus == "READY"


@pytest.mark.parametrize("qa", ["bad JSON", TimeoutError("offline timeout")])
def test_qa_unavailable_keeps_valid_draft_without_fabricating_review(qa):
    agent, result = execute(StubLLM([plan("draft")], [qa]))
    assert result.title == "draft"
    assert agent.last_quality is None
    assert agent.last_run.stopReason == "QA_UNAVAILABLE"
    assert agent.last_run.reviewStatus == "NEEDS_REVIEW"
    assert "QA_UNAVAILABLE" in agent.last_run.reviewReasons


def test_all_invalid_output_uses_validated_explicit_fallback():
    agent, _ = execute(StubLLM(["bad", "bad", "bad"]))
    assert agent.last_plan_source == "DETERMINISTIC_FALLBACK"
    assert agent.last_run.selectedIteration is None
    assert agent.last_run.stopReason == "NO_VALID_CANDIDATE"
    assert "DETERMINISTIC_FALLBACK" in agent.last_run.reviewReasons


def test_exhausted_budget_before_first_round_never_references_unassigned_plan(monkeypatch):
    monkeypatch.setattr(config, "QA_TIME_BUDGET_SECONDS", 0)
    stub = StubLLM([])
    agent, _ = execute(stub)
    assert stub.director_prompts == []
    assert agent.last_run.attempts == []
    assert agent.last_run.stopReason == "BUDGET_EXHAUSTED"


def test_expired_budget_after_generation_skips_new_qa_call_but_keeps_valid_draft(monkeypatch):
    clock = [0]
    monkeypatch.setattr(plan_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    stub = StubLLM([plan("draft")])
    invoke = stub.invoke

    def slow_director(prompt):
        clock[0] = 601
        return invoke(prompt)

    stub.invoke = slow_director
    agent, result = execute(stub)
    assert result.title == "draft"
    assert stub.quality_prompts == []
    assert agent.last_run.stopReason == "BUDGET_EXHAUSTED"
    assert agent.last_run.attempts[0].outcome == "BUDGET_EXHAUSTED"
    assert agent.last_quality is None


def test_sanitization_precedes_qa_and_does_not_change_reviewed_plan():
    evidence = report()
    evidence.highlights = [HighlightClip(sceneIndex=20, start=5, end=10)]
    draft = plan()
    draft.timeline[1].keep = False
    stub = StubLLM([draft], [review()])
    agent = PlanAgent(llm=stub)
    seen = []

    def inspect(candidate, *_):
        seen.append(candidate.to_contract_dict())
        return QualityReview.model_validate(review())

    agent.quality_agent.review = inspect
    result = agent.run(evidence, target(), "p")
    assert result.timeline[1].keep
    assert seen == [result.to_contract_dict()]
    assert agent.last_quality.candidateHash == candidate_hash(result)


def test_reusing_agent_clears_previous_review_and_attempts(monkeypatch):
    agent, _ = execute(StubLLM([plan()], [review()]))
    monkeypatch.setattr(config, "SIMULATE_FORCED", True)
    result = agent.run(report(), target(), "p")
    assert agent.last_quality is None
    assert agent.last_run.attempts == []
    assert agent.last_run.planSource == "DETERMINISTIC_FALLBACK"
    assert agent.last_run.selectedCandidateHash == candidate_hash(result)


def test_deterministic_mode_cannot_bypass_validator(monkeypatch):
    monkeypatch.setattr(config, "SIMULATE_FORCED", True)
    evidence = report()
    evidence.scenes[1].end = 11
    with pytest.raises(ValueError, match="兜底方案仍未通过校验"):
        PlanAgent(llm=object()).run(evidence, target(), "p")


@pytest.mark.parametrize("field,value", [
    ("assetId", "foreign"), ("url", "file:///other.mp4"), ("duration", 1000),
    ("width", 9999), ("height", 9999), ("fps", 60),
])
def test_model_cannot_change_trusted_source_metadata(field, value):
    candidate = plan()
    setattr(candidate.source, field, value)
    result = DeterministicValidator().validate(candidate, report(), target())
    assert not result.valid
    assert "source_identity" in [error.rule for error in result.errors]


def test_source_duration_spoof_cannot_hide_out_of_source_range():
    candidate = plan()
    candidate.source.duration = 1000
    candidate.timeline[1].sourceRange.end = 999
    result = DeterministicValidator().validate(candidate, report(), target())
    assert {error.rule for error in result.errors} >= {"source_identity", "source_range_bounds"}


def test_removed_ranges_still_require_valid_source_coordinates():
    candidate = plan()
    candidate.timeline[1].keep = False
    candidate.timeline[1].sourceRange.end = 999
    assert not DeterministicValidator().validate(candidate, report(), target()).valid


def test_empty_kept_timeline_is_rejected():
    candidate = plan()
    for segment in candidate.timeline:
        segment.keep = False
    result = DeterministicValidator().validate(candidate, report(), target())
    assert "kept_content" in [error.rule for error in result.errors]


def test_nonfinite_model_numbers_are_rejected_before_hashing():
    candidate = plan()
    candidate.global_.output.fps = float("inf")
    result = DeterministicValidator().validate(candidate, report(), target())
    assert "finite_numbers" in [error.rule for error in result.errors]
    agent, _ = execute(StubLLM([candidate, plan("fixed")], [review()]))
    assert agent.last_run.attempts[0].outcome == "GENERATION_FAILED"


def test_warning_or_simulated_evidence_requires_review_even_with_qa_pass():
    candidate = plan()
    candidate.timeline[0].operations.append(OpSpeed(type="speed", rate=3))
    agent, _ = execute(StubLLM([candidate], [review()]))
    assert "VALIDATOR_WARNINGS" in agent.last_run.reviewReasons
    evidence = report()
    evidence.simulated = True
    evidence.provenance["vlm"]["mode"] = "MIXED"
    agent = PlanAgent(llm=StubLLM([plan()], [review()]))
    agent.run(evidence, target(), "p")
    assert agent.last_run.reviewStatus == "NEEDS_REVIEW"
    assert "SIMULATED_ANALYSIS" in agent.last_run.reviewReasons
    assert "ANALYSIS_REQUIRES_REVIEW" in agent.last_run.reviewReasons


def test_qa_reads_original_evidence_and_hash_is_overwritten_by_program():
    qa = review() | {"candidateHash": "0" * 64}
    stub = StubLLM([], [qa])
    result = QualityAgent(llm=stub).review(plan(), report(), target())
    assert result.candidateHash == candidate_hash(plan())
    assert "先取下镜头盖再开机" in stub.quality_prompts[0]
    assert "桌上展示蓝色相机" in stub.quality_prompts[0]
    assert '"start": 0.5' in stub.quality_prompts[0]


@pytest.mark.parametrize("provenance", [{}, {"vlm": {"mode": "REAL"}}, {"asr": None, "vlm": {"mode": "REAL"}}])
def test_missing_analysis_provenance_is_not_ready(provenance):
    evidence = report()
    evidence.provenance = provenance
    agent = PlanAgent(llm=StubLLM([plan()], [review()]))
    agent.run(evidence, target(), "p")
    assert agent.last_run.reviewStatus == "NEEDS_REVIEW"
    assert "ANALYSIS_PROVENANCE_UNAVAILABLE" in agent.last_run.reviewReasons


def test_progress_is_monotonic_across_rewrites_and_completion():
    agent = PlanAgent(llm=StubLLM([plan("a"), plan("b")], [review(0.5, False), review()]))
    progress = []
    agent.run(report(), target(), "p", progress_cb=lambda value, _: progress.append(value))
    assert progress == sorted(progress)
    assert progress[-1] == 100


def test_api_result_carries_trace_and_bound_qa_in_saved_report(monkeypatch, tmp_path):
    stub = StubLLM([plan()], [review()])
    agent = PlanAgent(llm=stub)
    monkeypatch.setattr(analyze, "PlanAgent", lambda **_: agent)
    monkeypatch.setattr(config, "WORK_DIR", str(tmp_path))

    async def resolve(*_):
        return None

    monkeypatch.setattr(analyze, "_resolve_video", resolve)
    monkeypatch.setattr(analyze.AnalysisAgent, "run", lambda *_, **__: report())

    async def run():
        job_id = "job_agent_iteration"
        analyze._jobs[job_id] = analyze.JobStatus(
            jobId=job_id, status="pending", createdAt="", updatedAt="",
        )
        try:
            await analyze._run_job(job_id, analyze.AnalyzeRequest(videoUrl=""))
            await asyncio.sleep(0.01)  # 等工作线程投递的 progress 协程收尾
            status = analyze._jobs[job_id]
            assert status.status == "success"
            assert status.progress == 100
            assert status.result["analysis"]["planning"]["reviewStatus"] == "READY"
            actual_hash = candidate_hash(Plan.model_validate(status.result["plan"]))
            assert status.result["quality"]["candidateHash"] == actual_hash
            assert status.result["analysis"]["planning"]["selectedCandidateHash"] == actual_hash
        finally:
            analyze._jobs.pop(job_id, None)

    asyncio.run(run())
