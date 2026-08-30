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
import time
from typing import List, Optional

from app import config
from app.agents.quality_agent import QualityAgent
from app.agents.validator import DeterministicValidator
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

# 质检闭环：达标阈值 / 最大迭代轮数 / 时间止损（秒）
_QA_THRESHOLD = 0.85
_MAX_QA_ITERATIONS = 3
_QA_TIME_BUDGET_SECONDS = 600.0  # 需容纳首轮导演生成（~3min）+ 至少一次重写


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


def _extract_json(text: str) -> str:
    """从 LLM 输出中剥离可能的 Markdown 代码块包裹，返回纯 JSON 文本。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


class PlanAgent:
    """剪辑方案规划 Agent：report + target → Plan。"""

    def __init__(self, llm=None, project_id: str = ""):
        self.llm = llm if llm is not None else config.get_langchain_chat_model()
        self.project_id = project_id
        self.validator = DeterministicValidator()
        self.quality_agent = QualityAgent(self.llm)
        # 最近一次 QA 评审结果（analyze.py 读取；SIMULATE 下为 None）
        self.last_quality = None

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------

    def run(
        self, report: AnalysisReport, target, project_id: Optional[str] = None
    ) -> Plan:
        """生成剪辑方案 Plan（LLM 结构化输出优先，否则确定性构建）。"""
        pid = project_id or self.project_id or report.assetId or "prj_default"
        if config.SIMULATE_FORCED or self.llm is None:
            return self._build_deterministic(report, target, pid)
        return self._build_with_llm(report, target, pid)

    # ------------------------------------------------------------------
    # LLM 路径（with_structured_output 强制合法）
    # ------------------------------------------------------------------

    def _build_with_llm(self, report: AnalysisReport, target, project_id: str) -> Plan:
        """生成→QA 评分→带 issue 重写 循环，最终过校验闸。"""
        v = getattr(target, "qualityThreshold", None)
        threshold = _QA_THRESHOLD if v is None else v  # 0 是合法值，不能用 or 吞掉
        best_plan, best_score = None, -1.0
        feedback = None
        prev_plan = None
        start = time.monotonic()
        for _ in range(_MAX_QA_ITERATIONS):
            if time.monotonic() - start > _QA_TIME_BUDGET_SECONDS:
                break
            plan = self._director_generate(report, target, project_id, feedback, prev_plan)
            if plan is None:
                logger.warning("[plan] 导演生成失败，回退确定性方案")
                return self._build_deterministic(report, target, project_id)
            review = self.quality_agent.review(plan, report, target)
            self.last_quality = review
            if review is None:  # QA 挂了 → 跳过监督，直接过闸
                return self._gate(plan, report, target, project_id)
            if review.overallScore > best_score:
                best_plan, best_score = plan, review.overallScore
            if review.passed or review.overallScore >= threshold:
                return self._gate(plan, report, target, project_id)
            feedback = review.issues
            prev_plan = plan  # 记录上一版，供下一轮定向修订
        # 迭代耗尽 / 超时 → 取历史最高分那版过闸
        return self._gate(best_plan or plan, report, target, project_id)

    def _director_generate(
        self, report: AnalysisReport, target, project_id: str, feedback=None,
        prev_plan: Optional[Plan] = None,
    ) -> Optional[Plan]:
        """导演单次生成：prompt→invoke→validate；失败返回 None（不抛异常）。"""
        prompt = self._director_prompt(report, target, project_id, feedback, prev_plan)
        # DeepSeek 等端点不支持 response_format（with_structured_output 依赖它），
        # 改为让 LLM 输出 JSON 文本后手动解析 + Pydantic 校验。
        prompt += "\n\n请直接输出一个符合上述 schema 的 JSON 对象，不要输出任何解释、前后缀或 Markdown 代码块标记。"
        try:
            raw = self.llm.invoke(prompt)
            text = raw.content if hasattr(raw, "content") else str(raw)
            plan = Plan.model_validate(json.loads(_extract_json(text)))
        except Exception as exc:
            logger.warning("[plan] 导演生成失败：%s", exc)
            return None
        # 强制契约字段（LLM 可能自由发挥）
        plan.schemaVersion = "1.0"
        plan.planVersion = 1
        plan.projectId = project_id
        logger.info("[plan] 导演生成方案，timeline=%d 段", len(plan.timeline))
        return plan

    def _gate(self, plan: Plan, report: AnalysisReport, target, project_id: str) -> Plan:
        """确定性校验闸：先兜底修复（恢复关键场景/去转场），再校验，非法则回退确定性构建。"""
        plan = self._sanitize_plan(plan, report)
        v = self.validator.validate(plan, report, target)
        if v.valid:
            return plan
        logger.warning("[plan] 校验闸拒绝，回退确定性方案：%s", v.errors)
        return self._build_deterministic(report, target, project_id)

    def _sanitize_plan(self, plan: Plan, report: AnalysisReport) -> Plan:
        """确定性兜底：恢复被误删的关键场景 + 去掉覆盖语音的转场。"""
        if plan is None:
            return plan
        plan = self._restore_protected_scenes(plan, report)
        if self.last_quality is not None and any(
            i.severity == "high" and i.dimension == "narration_visual_match"
            for i in self.last_quality.issues
        ):
            plan.transitions = []
        return plan

    def _protected_scene_indices(self, report: AnalysisReport) -> set:
        """关键场景（highlights + keySentences + 高 importance 论点的 sceneIndices）。"""
        protected = {h.sceneIndex for h in report.highlights}
        narration = getattr(report, "narration", None)
        if narration:
            for ks in narration.keySentences:
                protected.add(ks.sceneIndex)
            for arg in narration.arguments:
                if arg.importance >= 0.5:
                    protected.update(arg.sceneIndices)
        return protected

    def _restore_protected_scenes(self, plan: Plan, report: AnalysisReport) -> Plan:
        """确保 protected 场景的完整 [start, end] 区间被 keep（不被部分删除）。"""
        protected = self._protected_scene_indices(report)
        if not protected:
            return plan
        for si in protected:
            if si >= len(report.scenes):
                continue
            sc = report.scenes[si]
            s, e = sc.start, sc.end
            if any(
                seg.keep and seg.sourceRange.start <= s + 1e-3 and e - 1e-3 <= seg.sourceRange.end
                for seg in plan.timeline
            ):
                continue
            target = next(
                (seg for seg in plan.timeline
                 if seg.sourceRange.start < e and seg.sourceRange.end > s),
                None,
            )
            if target is not None:
                target.keep = True
                target.sourceRange.start = min(target.sourceRange.start, s)
                target.sourceRange.end = max(target.sourceRange.end, e)
            else:
                plan.timeline.append(Segment(
                    id=f"restore_{si}",
                    keep=True,
                    sourceRange=TimeRange(start=s, end=e),
                    operations=[],
                ))
        plan.timeline.sort(key=lambda seg: seg.sourceRange.start)
        return plan

    def _director_prompt(self, report, target, project_id, feedback=None, prev_plan: Optional[Plan] = None) -> str:
        # 用 Pydantic 生成精确 JSON Schema，让 LLM 严格对齐字段名（避免字段名漂移导致校验失败）
        schema_json = json.dumps(Plan.model_json_schema(), ensure_ascii=False)
        target_json = (
            target.model_dump(mode="json", by_alias=True)
            if hasattr(target, "model_dump")
            else vars(target)
        )
        base = (
            "你是 AgentCut 的视频剪辑方案规划师。请根据分析报告与用户目标生成剪辑方案。\n"
            "剪辑方案必须严格符合以下 JSON Schema（字段名、required 字段必须完全一致，不要输出 schema 之外的字段）：\n"
            f"{schema_json}\n\n"
            f"projectId: {project_id}\n"
            f"用户目标(target):\n{json.dumps(target_json, ensure_ascii=False)}\n"
            f"分析报告(report):\n{report.model_dump_json(indent=2)}\n"
        )
        base += "\n" + self._build_hard_constraints(report) + "\n"
        if prev_plan is not None:
            base += (
                "\n这是上一版剪辑方案，请在其基础上只修改评审指出的问题，其余保持不变：\n"
                f"{prev_plan.model_dump_json(indent=2)}\n"
            )
        if feedback:
            by_severity: dict = {"high": [], "medium": [], "low": []}
            for f in feedback:
                sev = getattr(f, "severity", "medium")
                by_severity.setdefault(sev, []).append(f.model_dump(mode="json"))
            parts = []
            if by_severity.get("high"):
                parts.append(
                    "【必须修复】high 问题，逐条修复后再输出：\n"
                    + json.dumps(by_severity["high"], ensure_ascii=False, indent=2)
                )
            if by_severity.get("medium"):
                parts.append(
                    "【建议修复】medium 问题：\n"
                    + json.dumps(by_severity["medium"], ensure_ascii=False, indent=2)
                )
            base += (
                "\n上一次质量评审发现以下问题，请逐条修复（high 必须修复，无法修复则说明原因）：\n"
                + "\n".join(parts) + "\n"
            )
        base += "\n请只输出一个符合上述 JSON Schema 的剪辑方案 JSON 对象，不要输出任何解释、前后缀或代码块标记。"
        return base

    def _build_hard_constraints(self, report) -> str:
        """从分析报告提取硬约束（必须保留/必须删除/硬性规则），消除语义断层。"""
        keep_items: List[str] = []
        seen_keep: set = set()

        def add_keep(si: int, label: str) -> None:
            if si not in seen_keep:
                seen_keep.add(si)
                keep_items.append(f"  sceneIndex={si}: {label}")

        for h in report.highlights[:10]:
            add_keep(h.sceneIndex, f"({h.start:.1f}s~{h.end:.1f}s) {h.reason}")
        narration = getattr(report, "narration", None)
        if narration:
            for ks in sorted(narration.keySentences, key=lambda k: k.importance, reverse=True)[:10]:
                add_keep(ks.sceneIndex, f"({ks.start:.1f}s~{ks.end:.1f}s) {ks.text[:40]}")
            # ① 补：高 importance 论点的依赖场景（arguments.sceneIndices）
            for arg in narration.arguments:
                if arg.importance >= 0.5:
                    for si in arg.sceneIndices:
                        add_keep(si, f"论点「{arg.claim[:30]}」依赖的铺垫/内容")

        delete_items: List[str] = []
        for s in report.suggestions:
            if s.type == "delete" and s.sceneIndex is not None:
                delete_items.append(f"  sceneIndex={s.sceneIndex}: {s.reason}")
        if narration:
            for rd in narration.redundancy[:10]:
                delete_items.append(
                    f"  sceneIndex={rd.sceneIndex} ({rd.start:.1f}s~{rd.end:.1f}s): {rd.reason or '冗余'}"
                )

        lines: List[str] = []
        if keep_items:
            lines.append(
                "【必须保留】以下 sceneIndex / 区间为核心内容，禁止删除或降速到不可读：\n"
                + "\n".join(keep_items)
            )
        if delete_items:
            lines.append(
                "【必须删除】以下区间为废话/冗余/静音，建议删除：\n" + "\n".join(delete_items)
            )
        lines.append(
            "【硬性规则】变速 rate ≤ 2.5；crop 不得越界且参数必须取整（整数像素）；"
            "keep=false 不得带 operations；时间轴连续无重叠；区间不得超出源时长。"
        )
        lines.append(
            "【转场规则】默认硬切（transitions 为空）；仅当相邻保留片段源素材连续、确有需要时才加 fade；"
            "fade 时长 ≤ 0.3s，且必须落在删除区/静音区，不得覆盖口播语音。"
        )
        lines.append(
            "【删减预算】仅删除明确标注的冗余/废话段；建议成片保留源内容 60%~80%，除非冗余段占比明显高于该比例。"
        )
        lines.append(
            "【切分规则】删除边界必须对齐到完整句子/场景边界，不得把一句话拆断；"
            "segment 的 start/end 对齐到 1/30s 帧边界（整数帧）。"
        )
        return "\n".join(lines)

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
        """逐场景决定保留 / 删除，并装配基础操作（draft 结构贯穿后续步骤）。

        优先级：protected（highlight + 讲解关键句/高重要性论点）强制保留 > delete > 快节奏低重要性。
        """
        style = (getattr(target, "style", "") or "").lower()
        fast = ("快" in style) or ("fast" in style)
        delete_idx = {
            s.sceneIndex
            for s in report.suggestions
            if s.type == "delete" and s.sceneIndex is not None
        }
        keep_idx = {
            s.sceneIndex
            for s in report.suggestions
            if s.type == "keep" and s.sceneIndex is not None
        }
        # protected：highlight + narration 关键句 / 高 importance 论点（内容完整性，禁止删）
        protected_idx = {h.sceneIndex for h in report.highlights} | keep_idx
        narration = getattr(report, "narration", None)
        if narration:
            for ks in narration.keySentences:
                protected_idx.add(ks.sceneIndex)
            for arg in narration.arguments:
                if arg.importance >= 0.5:
                    protected_idx.update(arg.sceneIndices)

        drafts: List[dict] = []
        for i, scene in enumerate(report.scenes):
            keep = True
            if i in protected_idx:
                keep = True  # 强制保留优先级最高，覆盖 delete
            elif i in delete_idx:
                keep = False
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
                    "protected": i in protected_idx,
                    "ops": ops,
                    "rate": 1.0,
                }
            )
        return drafts

    def _apply_duration_constraint(
        self, drafts: List[dict], max_duration: Optional[float]
    ) -> None:
        """按 maxDuration 压缩：优先变速，超限则丢弃低重要度片段（protected 豁免删除）。"""
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
            droppable = [d for d in kept if not d.get("protected", False)]
            # 终止条件：只剩 1 段 / 无非 protected 可删 / 变速已达标 → 强制变速收尾（rate 可超 _SPEED_CAP）
            if len(kept) == 1 or not droppable or rate <= _SPEED_CAP:
                for d in kept:
                    d["rate"] = rate
                return
            # 变速仍超限 → 丢弃非 protected 中重要度最低的片段
            drop = min(droppable, key=lambda d: d["importance"])
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
