"""视频分析异步任务接口（app.api.analyze）。

- POST /analyze                    提交分析（videoUrl + target 约束 + callbackUrl），返回 jobId，异步执行
- GET  /analyze/{jobId}/status     查询任务状态 / 进度（轮询兜底）
- POST /analyze/{jobId}/callback   手动触发完成回调（供 Java 轮询到终态后调用）

MVP 实现：job 状态保存在进程内存字典（无状态单任务，不做持久化 / 记忆）。
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.agents.analysis_agent import AnalysisAgent
from app.agents.plan_agent import PlanAgent

logger = logging.getLogger(__name__)

# 路由路径写全（/analyze 前缀 + 子路径），避免依赖 FastAPI 前缀拼接对空路径的行为差异
router = APIRouter(tags=["analyze"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 请求 / 状态模型
# ---------------------------------------------------------------------------


class TargetConstraints(BaseModel):
    """用户意图（替代长期记忆，单次任务显式传入）。"""

    aspectRatio: str = Field(default="16:9", description="目标画幅，如 '9:16' / '16:9' / '1:1'")
    maxDuration: Optional[float] = Field(default=None, ge=1, description="目标时长上限（秒）")
    addSubtitle: Optional[bool] = Field(default=False, description="是否自动添加字幕")
    style: Optional[str] = Field(default="", description="风格意图（自由文本），如 '快节奏口播'")
    qualityThreshold: Optional[float] = Field(default=None, ge=0, le=1, description="脚本质量达标阈值（0~1），低于则迭代重写")


class AnalyzeRequest(BaseModel):
    videoUrl: str = Field(description="源视频 URL（http(s) 可下载；oss:// 需后续接入 OSS 客户端）")
    callbackUrl: Optional[str] = Field(default=None, description="分析完成后的回调地址")
    target: TargetConstraints = Field(default_factory=TargetConstraints)


class JobStatus(BaseModel):
    """任务状态（内存中更新）。"""

    jobId: str
    status: Literal["pending", "running", "success", "failed"]
    progress: int = Field(default=0, ge=0, le=100)
    step: str = ""
    error: Optional[str] = None
    callbackUrl: Optional[str] = None
    callbackSent: bool = False
    createdAt: str
    updatedAt: str
    result: Optional[dict] = None  # 成功时含 {analysis, plan}


# ---------------------------------------------------------------------------
# 内存任务存储（无状态单任务 MVP）
# ---------------------------------------------------------------------------

_jobs: Dict[str, JobStatus] = {}
_jobs_lock = asyncio.Lock()


async def _update_job(job_id: str, **fields: Any) -> None:
    async with _jobs_lock:
        st = _jobs.get(job_id)
        if st is None:
            return
        for k, v in fields.items():
            setattr(st, k, v)
        st.updatedAt = _now()


# ---------------------------------------------------------------------------
# 后台任务
# ---------------------------------------------------------------------------


async def _resolve_video(video_url: str, work_dir: str) -> Optional[str]:
    """把视频 URL 解析为本地路径；无法解析时返回 None（分析进入模拟）。"""
    if not video_url:
        return None
    # 规范化：剥掉 file:// 前缀（Java 后端本地存储的 ossUrl 携带该前缀）
    if video_url.lower().startswith("file://"):
        video_url = video_url[len("file://"):]
    low = video_url.lower()
    if low.startswith(("http://", "https://")):
        os.makedirs(work_dir, exist_ok=True)
        name = os.path.basename(video_url.split("?")[0]) or "video.mp4"
        local = os.path.join(work_dir, name)
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(video_url)
            resp.raise_for_status()
            with open(local, "wb") as fh:
                fh.write(resp.content)
        logger.info("已下载视频到 %s (%d bytes)", local, len(resp.content))
        return local
    if low.startswith("oss://"):
        if config.SIMULATE:
            return None
        raise NotImplementedError("oss:// 下载尚未接入，MVP 请传 http(s) URL 或本地路径")
    if os.path.exists(video_url):
        return video_url
    if config.SIMULATE:
        return None
    raise FileNotFoundError(f"无法解析视频路径: {video_url}")


async def _notify_callback(job_id: str, callback_url: str, payload: dict) -> None:
    """分析完成后向 callbackUrl 回传结果（失败仅告警，不阻断任务）。"""
    if not callback_url:
        return
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(callback_url, json=payload)
        logger.info("回调 %s -> %s status=%s", job_id, callback_url, resp.status_code)
        if resp.status_code < 400:
            await _update_job(job_id, callbackSent=True)
    except Exception as exc:
        logger.warning("回调失败 %s: %s", callback_url, exc)


def _asset_id(job_id: str) -> str:
    return "asset_" + job_id[-8:]


async def _run_job(job_id: str, req: AnalyzeRequest) -> None:
    """执行一次自包含分析任务：下载 → 分析 → 方案 → 回调。"""
    work_dir = os.path.join(config.WORK_DIR, job_id)
    await _update_job(job_id, status="running", progress=5, step="初始化")
    result: Optional[dict] = None
    try:
        video_path = await _resolve_video(req.videoUrl, work_dir)
        await _update_job(job_id, progress=10, step="解析视频")

        # ① 视频分析（抽帧 / 场景 / ASR / VLM）——耗时，丢线程池避免阻塞事件循环
        agent = AnalysisAgent(work_dir=work_dir)
        report = await asyncio.to_thread(agent.run, video_path, _asset_id(job_id))
        await _update_job(job_id, progress=75, step="生成剪辑方案")

        # ② 方案生成（report + target 约束）
        plan_agent = PlanAgent(project_id=report.assetId)
        plan = await asyncio.to_thread(plan_agent.run, report, req.target, report.assetId)

        result = {
            "analysis": report.model_dump(mode="json"),
            "plan": plan.to_contract_dict(),
            "quality": plan_agent.last_quality.model_dump(mode="json")
            if getattr(plan_agent, "last_quality", None)
            else None,
        }
        await _update_job(job_id, status="success", progress=100, step="完成", result=result)
    except Exception as exc:
        logger.exception("任务 %s 失败", job_id)
        await _update_job(
            job_id, status="failed", progress=100, step="失败", error=str(exc), result=result
        )
    finally:
        if req.callbackUrl:
            await _notify_callback(job_id, req.callbackUrl, _status_payload(_jobs.get(job_id)))


def _status_payload(st: Optional[JobStatus]) -> dict:
    return st.model_dump(mode="json") if st is not None else {}


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("/analyze", status_code=202)
async def submit_analyze(req: AnalyzeRequest) -> dict:
    """提交视频分析任务，返回 jobId（异步执行）。"""
    job_id = "job_" + uuid.uuid4().hex[:12]
    st = JobStatus(
        jobId=job_id,
        status="pending",
        progress=0,
        step="排队中",
        callbackUrl=req.callbackUrl,
        createdAt=_now(),
        updatedAt=_now(),
    )
    async with _jobs_lock:
        _jobs[job_id] = st
    asyncio.create_task(_run_job(job_id, req))
    return {"jobId": job_id, "status": "pending"}


@router.get("/analyze/{job_id}/status")
async def get_status(job_id: str) -> dict:
    """查询任务状态与进度。"""
    st = _jobs.get(job_id)
    if st is None:
        raise HTTPException(status_code=404, detail=f"job 不存在: {job_id}")
    return _status_payload(st)


@router.post("/analyze/{job_id}/callback")
async def trigger_callback(job_id: str) -> dict:
    """手动触发完成回调（Java 轮询到终态后调用，或用于重试回调）。"""
    st = _jobs.get(job_id)
    if st is None:
        raise HTTPException(status_code=404, detail=f"job 不存在: {job_id}")
    if st.status not in ("success", "failed"):
        raise HTTPException(status_code=409, detail=f"任务尚未终态: {st.status}")
    if not st.callbackUrl:
        raise HTTPException(status_code=400, detail="该任务未配置 callbackUrl")
    await _notify_callback(job_id, st.callbackUrl, _status_payload(st))
    return {"jobId": job_id, "callbackSent": True}
