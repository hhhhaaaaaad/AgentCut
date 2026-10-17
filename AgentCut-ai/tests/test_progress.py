"""进度上报链路的单元测试。

覆盖：
- AnalysisAgent._report 的 None 安全与异常吞掉（进度上报绝不能反过来打断分析）
- analyze._make_progress_cb 的区间映射与「单调不回退」钳制
  （LangGraph 下 frames 与 asr 是并行分支，进度会交错上报）
"""

import asyncio

from app.agents.analysis_agent import AnalysisAgent
from app.api import analyze
from app.schemas.plan import TimeRange
from app.tools import transcribe
from app.tools import vlm_understand


def _make_agent(tmp_path) -> AnalysisAgent:
    return AnalysisAgent(work_dir=str(tmp_path))


def test_report_is_noop_without_callback(tmp_path):
    agent = _make_agent(tmp_path)
    agent._progress_cb = None

    agent._report(50, "任意步骤")  # 不应抛出


def test_report_swallows_callback_exceptions(tmp_path):
    agent = _make_agent(tmp_path)

    def _boom(percent, step):
        raise RuntimeError("回调自身炸了")

    agent._progress_cb = _boom

    agent._report(50, "任意步骤")  # 必须被吞掉，不能影响分析主流程


def test_agent_run_reports_increasing_progress(tmp_path, monkeypatch):
    """run() 应把 progress_cb 贯穿整条流水线，且进度单调不回退。"""
    from app import config

    monkeypatch.setattr(config, "SIMULATE_FORCED", True)

    collected = []
    agent = AnalysisAgent(work_dir=str(tmp_path))
    agent.run(None, "asset_test", progress_cb=lambda p, s: collected.append(p))

    assert collected, "应至少上报一次进度"
    assert collected == sorted(collected), "进度必须单调不回退"
    assert collected[0] == AnalysisAgent._P_PROBE
    assert collected[-1] == AnalysisAgent._P_EXPERTS


def test_progress_cb_maps_to_global_range_and_is_monotonic():
    async def main():
        job_id = "job_progress_test"
        analyze._jobs[job_id] = analyze.JobStatus(
            jobId=job_id,
            status="running",
            progress=0,
            callbackUrl=None,  # 无回调地址 → _push_progress 只更新内存，不发 HTTP
            createdAt="",
            updatedAt="",
        )
        try:
            loop = asyncio.get_running_loop()
            cb = analyze._make_progress_cb(job_id, loop)

            cb(0, "start")
            await asyncio.sleep(0.02)
            after_zero = analyze._jobs[job_id].progress

            cb(50, "mid")
            await asyncio.sleep(0.02)
            after_mid = analyze._jobs[job_id].progress

            cb(30, "back")  # 回退：必须被忽略
            await asyncio.sleep(0.02)
            after_back = analyze._jobs[job_id].progress
            step_after_back = analyze._jobs[job_id].step

            cb(100, "done")
            await asyncio.sleep(0.02)
            after_full = analyze._jobs[job_id].progress

            return after_zero, after_mid, after_back, step_after_back, after_full
        finally:
            analyze._jobs.pop(job_id, None)

    after_zero, after_mid, after_back, step_after_back, after_full = asyncio.run(main())

    # 相对 0/50/100 映射到全局 10→72
    assert after_zero == analyze._ANALYZE_START
    assert after_mid > after_zero
    assert after_full == analyze._ANALYZE_END
    # 回退的 30 既不推进进度，也不覆盖步骤名
    assert after_back == after_mid
    assert step_after_back == "mid"


def test_progress_cb_clamps_out_of_range():
    async def main():
        job_id = "job_progress_clamp"
        analyze._jobs[job_id] = analyze.JobStatus(
            jobId=job_id,
            status="running",
            progress=0,
            callbackUrl=None,
            createdAt="",
            updatedAt="",
        )
        try:
            loop = asyncio.get_running_loop()
            cb = analyze._make_progress_cb(job_id, loop)
            cb(999, "over")
            await asyncio.sleep(0.02)
            return analyze._jobs[job_id].progress
        finally:
            analyze._jobs.pop(job_id, None)

    assert asyncio.run(main()) == analyze._ANALYZE_END


def test_forced_simulation_skips_local_asr_import(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "SIMULATE_FORCED", True)
    video = tmp_path / "fixture.mp4"
    video.write_bytes(b"not a real video")

    transcribe.transcribe(
        str(video),
        scenes=[TimeRange(start=0.0, end=1.0)],
    )

    provenance = transcribe.get_last_provenance()
    assert provenance["mode"] == "SIMULATED"
    assert provenance["reason"] == "simulate_forced"


def test_simulated_vlm_supports_single_scene(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "SIMULATE_FORCED", True)
    result = vlm_understand.understand_video(
        [TimeRange(start=0.0, end=1.0)],
        [],
        [],
        {},
    )

    assert result["simulated"] is True
    assert result["suggestions"][0]["sceneIndex"] == 0
