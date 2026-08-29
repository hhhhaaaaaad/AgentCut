"""多 Agent 架构单元测试：validator 12 条规则 + plan_agent 导演兜底 / QA 循环。"""

import json
from types import SimpleNamespace

import pytest

from app import config
from app.agents.plan_agent import PlanAgent
from app.agents.validator import DeterministicValidator
from app.schemas.analysis import AnalysisReport, Scene, TranscriptSegment
from app.schemas.expert import Argument, Chapter, KeySentence, NarrationAnalysis
from app.schemas.plan import (
    Global,
    OpCrop,
    OpSpeed,
    OpSubtitle,
    OutputConfig,
    Plan,
    Segment,
    Source,
    TimeRange,
    Transition,
)


# ---------------------------------------------------------------------------
# 构造工具
# ---------------------------------------------------------------------------


def _make_report(**kw) -> AnalysisReport:
    scenes = kw.get(
        "scenes",
        [
            Scene(index=0, start=0.0, end=5.0, importance=0.8),
            Scene(index=1, start=5.0, end=10.0, importance=0.9),
            Scene(index=2, start=10.0, end=12.0, importance=0.3),
        ],
    )
    transcripts = kw.get(
        "transcripts",
        [
            TranscriptSegment(index=0, start=0.5, end=4.0, text="大家好今天讲剪辑"),
            TranscriptSegment(index=1, start=5.5, end=9.0, text="核心论点很重要"),
        ],
    )
    narration = kw.get(
        "narration",
        NarrationAnalysis(
            keySentences=[KeySentence(sceneIndex=1, start=5.5, end=9.0, text="核心论点很重要", importance=0.9)],
            arguments=[Argument(index=0, claim="核心论点", sceneIndices=[1], importance=0.9)],
        ),
    )
    chapters = kw.get(
        "chapters",
        [Chapter(index=i, start=s.start, end=s.end, type="body") for i, s in enumerate(scenes)],
    )
    return AnalysisReport(
        assetId="asset_test",
        videoUrl="",
        duration=kw.get("duration", 12.0),
        width=1920,
        height=1080,
        fps=30.0,
        scenes=scenes,
        transcripts=transcripts,
        narration=narration,
        chapters=chapters,
    )


def _target(**kw) -> SimpleNamespace:
    return SimpleNamespace(
        aspectRatio="16:9", maxDuration=kw.get("maxDuration"), addSubtitle=False, style=""
    )


def _make_plan() -> Plan:
    return Plan(
        schemaVersion="1.0",
        planVersion=1,
        projectId="p",
        title="t",
        source=Source(assetId="a", url="", duration=12.0, fps=30.0, width=1920, height=1080),
        global_=Global(output=OutputConfig(width=1920, height=1080, fps=30.0)),
        timeline=[
            Segment(id="seg_1", keep=True, sourceRange=TimeRange(start=0.0, end=5.0)),
            Segment(id="seg_2", keep=True, sourceRange=TimeRange(start=5.0, end=10.0)),
            Segment(id="seg_3", keep=False, sourceRange=TimeRange(start=10.0, end=12.0)),
        ],
        transitions=[],
    )


def _validate(plan, report=None, target=None):
    return DeterministicValidator().validate(plan, report or _make_report(), target or _target())


# ---------------------------------------------------------------------------
# 校验闸：合法方案 + 确定性方案永远合法
# ---------------------------------------------------------------------------


def test_valid_plan_passes():
    res = _validate(_make_plan())
    assert res.valid, f"合法方案应通过: {res.errors}"


def test_deterministic_plan_always_valid():
    report = _make_report()
    target = _target()
    plan = PlanAgent()._build_deterministic(report, target, "p")
    res = _validate(plan, report, target)
    assert res.valid, f"确定性方案应永远合法: {res.errors}"


# ---------------------------------------------------------------------------
# R1~R12 逐条命中
# ---------------------------------------------------------------------------


def test_r1_source_range_bounds():
    plan = _make_plan()
    plan.timeline[0].sourceRange = TimeRange(start=0.0, end=999.0)
    assert any(e.rule == "source_range_bounds" for e in _validate(plan).errors)


def test_r2_timeline_order_overlap():
    plan = _make_plan()
    plan.timeline[1].sourceRange = TimeRange(start=4.0, end=10.0)  # 与 seg_1 重叠
    assert any(e.rule == "timeline_order_overlap" for e in _validate(plan).errors)


def test_r3_crop_bounds():
    plan = _make_plan()
    plan.timeline[0].operations.append(OpCrop(type="crop", x=0.0, y=0.0, width=9999.0, height=1080.0))
    assert any(e.rule == "crop_bounds" for e in _validate(plan).errors)


def test_r4_speed_warning():
    # 注：rate<=0 的 error 分支由 Pydantic(gt=0) 在构造期拦截，validator 的检查是防御性兜底（不可经 Pydantic 构造触发）
    plan = _make_plan()
    plan.timeline[0].operations.append(OpSpeed(type="speed", rate=3.0))
    res = _validate(plan)
    assert any(w.rule == "speed_valid" and w.severity == "warning" for w in res.warnings)


def test_r5_speed_order():
    plan = _make_plan()
    plan.timeline[0].operations = [
        OpSpeed(type="speed", rate=1.5),
        OpSubtitle(type="subtitle", text="x", start=0.0, end=1.0),
    ]
    assert any(w.rule == "speed_order" for w in _validate(plan).warnings)


def test_r6_subtitle_bounds():
    plan = _make_plan()
    plan.timeline[0].operations.append(OpSubtitle(type="subtitle", text="x", start=0.0, end=999.0))
    assert any(e.rule == "subtitle_bounds" for e in _validate(plan).errors)


def test_r7_subtitle_narration_match():
    # seg_3 (10~12s) 区间无转写，但带字幕 → warning
    plan = _make_plan()
    plan.timeline[2] = Segment(
        id="seg_3", keep=True, sourceRange=TimeRange(start=10.0, end=12.0),
        operations=[OpSubtitle(type="subtitle", text="无口播字幕", start=0.0, end=1.0)],
    )
    assert any(w.rule == "subtitle_narration_match" for w in _validate(plan).warnings)


def test_r8_keep_false_no_ops():
    plan = _make_plan()
    plan.timeline[2].operations.append(OpSpeed(type="speed", rate=1.5))
    assert any(e.rule == "keep_false_no_ops" for e in _validate(plan).errors)


def test_r9_transition_refs():
    plan = _make_plan()
    plan.transitions = [Transition(from_="seg_1", to="seg_3", type="fade")]  # seg_3 非 kept
    assert any(e.rule == "transition_refs" for e in _validate(plan).errors)


def test_r10_content_integrity():
    # narration 关键句在 5.5~9.0s，但只保留 0~5s 片段 → warning
    plan = _make_plan()
    plan.timeline[1].keep = False
    assert any(w.rule == "content_integrity" for w in _validate(plan).warnings)


def test_r11_duration_constraint():
    plan = _make_plan()
    target = _target(maxDuration=1.0)  # 成片 10s 远超 1s
    assert any(e.rule == "duration_constraint" for e in _validate(plan, target=target).errors)


def test_r12_id_unique():
    plan = _make_plan()
    plan.timeline[1].id = "seg_1"  # 重复 id
    assert any(e.rule == "id_unique" for e in _validate(plan).errors)


# ---------------------------------------------------------------------------
# plan_agent：导演兜底 / 校验闸回退 / QA 循环
# ---------------------------------------------------------------------------


class _GarbageLLM:
    """返回非法 JSON 的 LLM。"""

    def invoke(self, prompt):
        return SimpleNamespace(content="这不是合法 JSON {{{")


class _StubLLM:
    """导演 prompt 返回方案 JSON，QA prompt 返回评审 JSON。"""

    def __init__(self, director_json: str, qa_json: str):
        self.director_json = director_json
        self.qa_json = qa_json

    def invoke(self, prompt):
        if "质量监督" in prompt:
            return SimpleNamespace(content=self.qa_json)
        return SimpleNamespace(content=self.director_json)


def test_director_generate_returns_none_on_bad_json():
    pa = PlanAgent(llm=_GarbageLLM())
    plan = pa._director_generate(_make_report(), _target(), "p")
    assert plan is None


def test_gate_rejects_invalid_falls_back_deterministic():
    report = _make_report()
    target = _target()
    pa = PlanAgent()
    bad = _make_plan()
    bad.timeline[0].sourceRange = TimeRange(start=0.0, end=999.0)  # R1 非法
    result = pa._gate(bad, report, target, "p")
    # 回退确定性方案，且必然合法
    assert result is not None
    assert DeterministicValidator().validate(result, report, target).valid


def test_qa_loop_passes(monkeypatch):
    monkeypatch.setattr(config, "SIMULATE_FORCED", False)
    report = _make_report()
    target = _target()
    plan_json = PlanAgent()._build_deterministic(report, target, "p").model_dump_json()
    qa_dict = {"overallScore": 0.9, "passed": True, "issues": [], "dimensionScores": [], "summary": ""}
    stub = _StubLLM(plan_json, json.dumps(qa_dict, ensure_ascii=False))
    pa = PlanAgent(llm=stub)
    plan = pa._build_with_llm(report, target, "p")
    assert plan is not None
    assert pa.last_quality is not None
    assert pa.last_quality.passed is True
