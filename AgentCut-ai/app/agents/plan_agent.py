"""PlanAgent：分析报告 + 用户目标 → 剪辑方案 Plan（app.agents.plan_agent）。

两条路径：
- LLM 路径：ChatOpenAI.with_structured_output(Plan) 强制产出合法方案（字段对齐 plan-schema.json）
- 确定性路径：规则构建器，保证任何输入都输出契约合法的 Plan（模拟 / 兜底 / 无 key）

无长期记忆：用户意图通过 target 约束（aspectRatio / maxDuration / addSubtitle / style）
显式传入，不从历史学习。

target 参数为鸭子类型：只需提供 aspectRatio / maxDuration / addSubtitle / style 属性，
避免与 API 层请求模型形成循环依赖。
"""

import json
import logging
import math
from typing import List, Optional

from app import config
from app.schemas.analysis import AnalysisReport
from app.schemas.plan import (
    Global,
    OpCrop,
    OpSpeed,
    OpSubtitle,
    Operation,
    OutputConfig,
    Plan,
    Segment,
    Source,
    SubtitleStyle,
    TimeRange,
    Transition,
)

logger = logging.getLogger(__name__)

# 画幅预设（比例 → 输出分辨率）
_ASPECT_PRESETS = {
    (16, 9): (1920, 1080),
    (9, 16): (1080, 1920),
    (1, 1): (1080, 1080),
    (4, 3): (1080, 810),
    (3, 4): (1080, 1440),
}

# 变速上限：超过则改丢低重要度片段
_SPEED_CAP = 2.5

# 单段字幕文本长度上限
_MAX_SUBTITLE_LEN = 120


def _norm_aspect(s: str):
    """解析画幅字符串为最简 (宽, 高) 元组；非法输入回退 16:9。"""
    s = (s or "").strip()
    try:
        a, b = s.split(":")
        rw, rh = int(a), int(b)
    except Exception:
        return (16, 9)
    if rw <= 0 or rh <= 0:
        return (16, 9)
    g = math.gcd(rw, rh)
    return (rw // g, rh // g)


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _safe_max_duration(target) -> Optional[float]:
    try:
        v = getattr(target, "maxDuration", None)
        return float(v) if v is not None else None
    except Exception:
        return None


class PlanAgent:
    """剪辑方案规划 Agent：report + target → Plan。"""

    def __init__(self, llm=None, project_id: str = ""):
        self.llm = llm if llm is not None else config.get_langchain_chat_model()
        self.project_id = project_id

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------

    def run(
        self, report: AnalysisReport, target, project_id: Optional[str] = None
    ) -> Plan:
        """生成剪辑方案 Plan（LLM 结构化输出优先，否则确定性构建）。"""
        pid = project_id or self.project_id or report.assetId or "prj_default"
        if config.SIMULATE or self.llm is None:
            return self._build_deterministic(report, target, pid)
        return self._build_with_llm(report, target, pid)

    # ------------------------------------------------------------------
    # LLM 路径（with_structured_output 强制合法）
    # ------------------------------------------------------------------

    def _build_with_llm(self, report: AnalysisReport, target, project_id: str) -> Plan:
        prompt = self._build_prompt(report, target, project_id)
        structured = self.llm.with_structured_output(Plan)
        plan = structured.invoke(prompt)
        # 强制契约字段（LLM 可能自由发挥）
        plan.schemaVersion = "1.0"
        plan.planVersion = 1
        plan.projectId = project_id
        logger.info("[plan] LLM 生成方案，timeline=%d 段", len(plan.timeline))
        return plan

    def _build_prompt(self, report: AnalysisReport, target, project_id: str) -> str:
        schema_hint = (
            "剪辑方案必须符合 docs/plan-schema.json：\n"
            "- timeline 需覆盖源视频所有场景（顺序即成片顺序），不需要的片段 keep=false\n"
            "- 操作仅支持 speed(rate) / crop(x,y,width,height) / subtitle(text,start,end) / "
            "volume(volume) / mute\n"
            "- global.output 按 target.aspectRatio 设置，需要裁切时用 crop 操作\n"
            "- 加字幕时配合 global.subtitleStyle 与 timeline 内 subtitle 操作\n"
            "- transitions 可空，引用片段必须存在\n"
        )
        target_json = (
            target.model_dump(mode="json", by_alias=True)
            if hasattr(target, "model_dump")
            else vars(target)
        )
        return (
            "你是 AgentCut 的视频剪辑方案规划师。请根据分析报告与用户目标生成剪辑方案。\n"
            f"{schema_hint}\n"
            f"projectId: {project_id}\n"
            f"用户目标(target):\n{json.dumps(target_json, ensure_ascii=False)}\n"
            f"分析报告(report):\n{report.model_dump_json(indent=2)}\n"
            "请输出符合 plan-schema.json 的剪辑方案。"
        )

    # ------------------------------------------------------------------
    # 确定性路径（规则构建，兜底 / 模拟）
    # ------------------------------------------------------------------

    def _build_deterministic(
        self, report: AnalysisReport, target, project_id: str
    ) -> Plan:
        output = self._compute_output(report, target)
        crop = self._compute_crop(report, target)
        drafts = self._decide_segments(report, target, crop)
        self._apply_duration_constraint(drafts, _safe_max_duration(target))
        if _to_bool(getattr(target, "addSubtitle", False)):
            self._attach_subtitles(drafts, report)
        segments = [self._build_segment(d, i) for i, d in enumerate(drafts)]
        transitions = self._build_transitions(segments, target)
        global_ = self._build_global(output, target)
        source = Source(
            assetId=report.assetId,
            url=report.videoUrl,
            duration=report.duration,
            fps=report.fps or 30.0,
            width=report.width or 1920,
            height=report.height or 1080,
        )
        return Plan(
            schemaVersion="1.0",
            planVersion=1,
            projectId=project_id,
            title=report.title,
            source=source,
            global_=global_,
            timeline=segments,
            transitions=transitions,
        )

    def _compute_output(self, report: AnalysisReport, target) -> OutputConfig:
        """按 target.aspectRatio 计算成片输出分辨率。"""
        fps = report.fps or 30.0
        aspect = _norm_aspect(getattr(target, "aspectRatio", "") or "16:9")
        preset = _ASPECT_PRESETS.get(aspect)
        if preset:
            return OutputConfig(width=preset[0], height=preset[1], fps=fps)
        # 自定义比例：以源尺寸适配，长边不超过 1920
        r = aspect[0] / aspect[1]
        if r >= 1:
            h = 1080
            w = min(round(h * r), 1920)
        else:
            w = 1080
            h = min(round(w / r), 1920)
        return OutputConfig(width=max(w, 1), height=max(h, 1), fps=fps)

    def _compute_crop(self, report: AnalysisReport, target) -> Optional[OpCrop]:
        """源画幅与目标画幅不一致时，生成居中裁切 OpCrop（源像素坐标）。"""
        aspect = _norm_aspect(getattr(target, "aspectRatio", "") or "16:9")
        r = aspect[0] / aspect[1]
        sw, sh = report.width or 1920, report.height or 1080
        sr = sw / sh
        if abs(sr - r) < 0.01:
            return None
        if sr > r:  # 画面过宽 → 裁宽
            crop_w = max(1, int(round(sh * r)))
            x = max(0, (sw - crop_w) // 2)
            return OpCrop(type="crop", x=float(x), y=0.0, width=float(crop_w), height=float(sh))
        # 画面过窄 → 裁高
        crop_h = max(1, int(round(sw / r)))
        y = max(0, (sh - crop_h) // 2)
        return OpCrop(type="crop", x=0.0, y=float(y), width=float(sw), height=float(crop_h))

    def _decide_segments(
        self, report: AnalysisReport, target, crop: Optional[OpCrop]
    ) -> List[dict]:
        """逐场景决定保留 / 删除，并装配基础操作（draft 结构贯穿后续步骤）。"""
        style = (getattr(target, "style", "") or "").lower()
        fast = ("快" in style) or ("fast" in style)
        highlight_idx = {h.sceneIndex for h in report.highlights}
        delete_idx = {
            s.sceneIndex
            for s in report.suggestions
            if s.type == "delete" and s.sceneIndex is not None
        }

        drafts: List[dict] = []
        for i, scene in enumerate(report.scenes):
            keep = True
            if i in delete_idx:
                keep = False
            elif i in highlight_idx:
                keep = True
            elif fast and scene.importance < 0.3:
                keep = False
            ops: List[Operation] = []
            if keep and crop is not None:
                ops.append(crop)
            drafts.append(
                {
                    "scene": scene,
                    "keep": keep,
                    "importance": scene.importance,
                    "ops": ops,
                    "rate": 1.0,
                }
            )
        return drafts

    def _apply_duration_constraint(
        self, drafts: List[dict], max_duration: Optional[float]
    ) -> None:
        """按 maxDuration 压缩：优先变速，超限则丢弃低重要度片段。"""
        if not max_duration or max_duration <= 0:
            return
        while True:
            kept = [d for d in drafts if d["keep"]]
            if not kept:
                return
            total = sum(d["scene"].end - d["scene"].start for d in kept)
            if total <= max_duration + 1e-6:
                return
            rate = total / max_duration
            if len(kept) == 1 or rate <= _SPEED_CAP:
                for d in kept:
                    d["rate"] = rate
                return
            # 变速仍超限 → 丢弃重要度最低的保留片段
            drop = min(kept, key=lambda d: d["importance"])
            drop["keep"] = False
            drop["ops"] = []
            drop["rate"] = 1.0

    def _attach_subtitles(self, drafts: List[dict], report: AnalysisReport) -> None:
        """给保留片段装配 subtitle 操作（文本取片段区间内的转写）。"""
        for d in drafts:
            if not d["keep"]:
                continue
            sc = d["scene"]
            text = report.transcript_text(sc.start, sc.end, sep=" ")
            if not text:
                continue
            text = text[:_MAX_SUBTITLE_LEN]
            # 字幕 end 按变速后的成片时长
            out_dur = round((sc.end - sc.start) / max(d["rate"], 1e-6), 3)
            d["ops"].append(
                OpSubtitle(type="subtitle", text=text, start=0.0, end=out_dur)
            )

    def _build_segment(self, d: dict, i: int) -> Segment:
        """把 draft 组装为 Segment（变速操作追加在末尾，顺序执行）。"""
        sc = d["scene"]
        ops = list(d["ops"])
        if d["keep"] and d["rate"] > 1.0 + 1e-6:
            ops.append(OpSpeed(type="speed", rate=round(d["rate"], 3)))
        return Segment(
            id=f"seg_{i + 1:03d}",
            keep=d["keep"],
            sourceRange=TimeRange(start=sc.start, end=sc.end),
            operations=ops,
        )

    def _build_transitions(self, segments: List[Segment], target) -> List[Transition]:
        """竖屏 / 快节奏风格下，在相邻保留片段间加淡入淡出转场。"""
        style = (getattr(target, "style", "") or "").lower()
        aspect = _norm_aspect(getattr(target, "aspectRatio", "") or "16:9")
        portrait = aspect == (9, 16)
        fast = ("快" in style) or ("fast" in style)
        if not (portrait or fast):
            return []
        kept = [seg for seg in segments if seg.keep]
        if len(kept) < 2:
            return []
        return [
            Transition(from_=a.id, to=b.id, type="fade", duration=0.5)
            for a, b in zip(kept, kept[1:])
        ]

    def _build_global(self, output: OutputConfig, target) -> Global:
        subtitle_style = None
        if _to_bool(getattr(target, "addSubtitle", False)):
            subtitle_style = SubtitleStyle(
                fontSize=48, color="#FFFFFF", position="bottom"
            )
        # bgm 无来源 URL 时保持 None（契约允许）；后续接入素材库后由上层注入
        return Global(output=output, bgm=None, subtitleStyle=subtitle_style)
