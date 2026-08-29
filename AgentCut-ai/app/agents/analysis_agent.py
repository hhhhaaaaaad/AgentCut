"""AnalysisAgent：理解视频并产出 AnalysisReport（app.agents.analysis_agent）。

流水线（确定性工具 + 分析专家 + VLM）：
    抽帧(PyAV) → 场景检测(PySceneDetect) → ASR(FunASR) → 分析专家(时间轴/讲解内容) + VLM → 组装报告

- 两专家（TimelineAgent / NarrationAgent）+ VLM 产出，_assemble 只做信号装配，不做剪辑决策。
- 环境中装有 langgraph 且非模拟模式时用 StateGraph 编排；否则顺序执行（二者等价）。
- 无长期记忆：本 agent 无状态，输入视频路径 + 临时工作目录，输出 AnalysisReport。
"""

import logging
import os
from typing import List, Optional

from app import config
from app.agents._common import detect_silence
from app.agents.narration_agent import NarrationAgent
from app.agents.timeline_agent import TimelineAgent
from app.schemas.analysis import (
    AnalysisReport,
    EditingSuggestion,
    HighlightClip,
    Scene,
    TranscriptSegment,
)
from app.schemas.plan import TimeRange
from app.tools import frame_extract, scene_detect, transcribe, vlm_understand

logger = logging.getLogger(__name__)

# LangGraph 可选：缺失时顺序执行
try:  # pragma: no cover - 依赖缺失时的降级路径
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    _HAS_LANGGRAPH = True
except Exception as exc:  # pragma: no cover
    _HAS_LANGGRAPH = False
    logger.debug("langgraph 未安装，AnalysisAgent 使用顺序执行：%s", exc)


class AnalysisAgent:
    """视频分析 Agent：抽帧 / 场景 / ASR / 分析专家 + VLM → AnalysisReport。"""

    def __init__(self, work_dir: Optional[str] = None):
        self.work_dir = work_dir or os.path.join(config.WORK_DIR, "analysis")
        os.makedirs(self.work_dir, exist_ok=True)
        # 分析专家由 __init__ 构造注入（便于测试与复用，避免每次重新建 client）
        self._timeline_agent = TimelineAgent()
        self._narration_agent = NarrationAgent()

    # ------------------------------------------------------------------
    # 流水线步骤（可被顺序执行 / LangGraph 节点复用）
    # ------------------------------------------------------------------

    def _step_probe(self, video_path: Optional[str]) -> dict:
        meta = frame_extract.probe_video(video_path)
        logger.info("[analysis] 元数据: %s", meta)
        return meta

    def _step_scene(self, video_path: Optional[str], meta: dict) -> List[TimeRange]:
        scenes = scene_detect.detect_scenes(video_path)
        return scenes or [TimeRange(start=0.0, end=meta["duration"])]

    def _step_frames(self, video_path: Optional[str], scenes: List[TimeRange]) -> List[str]:
        frame_dir = os.path.join(self.work_dir, "frames")
        return frame_extract.extract_frames_by_scenes(video_path, scenes, frame_dir)

    def _step_asr(
        self, video_path: Optional[str], scenes: List[TimeRange]
    ) -> List[TranscriptSegment]:
        return transcribe.transcribe(video_path, scenes=scenes)

    def _step_vlm(
        self,
        scenes: List[TimeRange],
        frames: List[str],
        transcripts: List[TranscriptSegment],
        meta: dict,
    ) -> dict:
        """视觉语义（复用现有 vlm_understand；其 highlights/suggestions 不再被消费）。"""
        return vlm_understand.understand_video(scenes, frames, transcripts, meta)

    def _step_experts(
        self,
        scenes: List[TimeRange],
        frames: List[str],
        transcripts: List[TranscriptSegment],
        meta: dict,
    ) -> dict:
        """编排两分析专家 + VLM。"""
        timeline = self._timeline_agent.run(scenes, transcripts, meta)
        narration = self._narration_agent.run(transcripts, scenes, meta)
        vlm = self._step_vlm(scenes, frames, transcripts, meta)
        return {"timeline": timeline, "narration": narration, "vlm": vlm}

    def _assemble(
        self,
        video_path: Optional[str],
        meta: dict,
        scenes: List[TimeRange],
        frames: List[str],
        transcripts: List[TranscriptSegment],
        experts: dict,
        asset_id: str,
    ) -> AnalysisReport:
        """把各步骤产物组装为 AnalysisReport（只做信号装配，不做剪辑决策）。"""
        vlm = experts["vlm"]
        timeline = experts["timeline"]
        narration = experts["narration"]

        descs = vlm.get("sceneDescriptions", [])
        tags = vlm.get("sceneTags", [])
        imps = vlm.get("sceneImportance", [])

        # 重要性统一：视觉 + 讲解取高，讲解兜下限（视觉做参考、讲解兜下限）
        narration_imp: dict = {}
        protected = set()
        if narration:
            for ks in narration.keySentences:
                narration_imp[ks.sceneIndex] = max(
                    narration_imp.get(ks.sceneIndex, 0.0), ks.importance
                )
                protected.add(ks.sceneIndex)
            for arg in narration.arguments:
                for si in arg.sceneIndices:
                    narration_imp[si] = max(narration_imp.get(si, 0.0), arg.importance)
                if arg.importance >= 0.5:
                    protected.update(arg.sceneIndices)

        scene_objs: List[Scene] = []
        for i, sc in enumerate(scenes):
            visual_i = imps[i] if i < len(imps) else 0.5
            imp = max(visual_i, narration_imp.get(i, 0.0))
            if i in protected:
                imp = max(imp, 0.5)
            scene_objs.append(
                Scene(
                    index=i,
                    start=sc.start,
                    end=sc.end,
                    duration=round(sc.end - sc.start, 3),
                    description=descs[i] if i < len(descs) else "",
                    keyFramePaths=frames[i : i + 1] if i < len(frames) else [],
                    tags=tags[i] if i < len(tags) else [],
                    importance=round(imp, 3),
                )
            )

        # highlights：讲解关键句 Top-N
        highlights: List[HighlightClip] = []
        if narration:
            top_ks = sorted(narration.keySentences, key=lambda k: k.importance, reverse=True)[:5]
            for ks in top_ks:
                highlights.append(
                    HighlightClip(
                        sceneIndex=ks.sceneIndex,
                        start=ks.start,
                        end=ks.end,
                        reason=ks.text,
                        score=ks.importance,
                    )
                )

        # suggestions：删除（filler + redundancy 去重）+ 保留（高 importance 论点）
        suggestions: List[EditingSuggestion] = []
        seen = set()
        if timeline:
            for fr in timeline.fillerRanges:
                si = next(
                    (
                        i
                        for i, sc in enumerate(scenes)
                        if sc.start <= fr.start + 1e-3 < sc.end
                    ),
                    None,
                )
                key = (si, round(fr.start, 2))
                if key in seen:
                    continue
                seen.add(key)
                suggestions.append(
                    EditingSuggestion(
                        type="delete",
                        sceneIndex=si,
                        reason="静音/无口播",
                        params={"start": fr.start, "end": fr.end},
                    )
                )
        if narration:
            for rd in narration.redundancy:
                key = (rd.sceneIndex, round(rd.start, 2))
                if key in seen:
                    continue
                seen.add(key)
                suggestions.append(
                    EditingSuggestion(
                        type="delete",
                        sceneIndex=rd.sceneIndex,
                        reason=rd.reason or "冗余",
                        params={"start": rd.start, "end": rd.end},
                    )
                )
            for arg in narration.arguments:
                if arg.importance >= 0.6:
                    for si in arg.sceneIndices:
                        suggestions.append(
                            EditingSuggestion(
                                type="keep", sceneIndex=si, reason=arg.claim, params={}
                            )
                        )

        silences = detect_silence(transcripts, scenes)

        # 语速（字/分钟）
        total_words = sum(len(t.text) for t in transcripts)
        speech_sec = max(sum(t.end - t.start for t in transcripts), 1e-6)
        wpm = round(total_words / speech_sec * 60.0, 1) if transcripts else None

        return AnalysisReport(
            assetId=asset_id,
            videoUrl=video_path or "",
            duration=meta["duration"],
            width=meta["width"],
            height=meta["height"],
            fps=meta["fps"],
            title=vlm.get("title"),
            summary=vlm.get("summary", ""),
            simulated=vlm.get("simulated", config.SIMULATE),
            scenes=scene_objs,
            transcripts=transcripts,
            highlights=highlights,
            silenceRanges=silences,
            suggestions=suggestions,
            narrationWordsPerMinute=wpm,
            vlmNotes=vlm.get("notes", ""),
            chapters=timeline.chapters if timeline else [],
            narration=narration,
        )

    # ------------------------------------------------------------------
    # 编排：LangGraph（可用时）/ 顺序执行
    # ------------------------------------------------------------------

    def run(self, video_path: Optional[str], asset_id: str = "") -> AnalysisReport:
        """执行分析流水线，返回 AnalysisReport。"""
        if not asset_id:
            base = os.path.basename(video_path) if video_path else "mock"
            asset_id = "asset_" + base
        if _HAS_LANGGRAPH and not config.SIMULATE_FORCED:
            return self._run_with_graph(video_path, asset_id)
        return self._run_sequential(video_path, asset_id)

    def _run_sequential(
        self, video_path: Optional[str], asset_id: str
    ) -> AnalysisReport:
        meta = self._step_probe(video_path)
        scenes = self._step_scene(video_path, meta)
        frames = self._step_frames(video_path, scenes)
        transcripts = self._step_asr(video_path, scenes)
        experts = self._step_experts(scenes, frames, transcripts, meta)
        return self._assemble(video_path, meta, scenes, frames, transcripts, experts, asset_id)

    def _build_graph(self):
        """LangGraph StateGraph：probe → scene → frames/asr → experts → assemble。"""

        class PipelineState(TypedDict):
            video_path: Optional[str]
            asset_id: str
            meta: dict
            scenes: list
            frames: list
            transcripts: list
            experts: dict

        g = StateGraph(PipelineState)
        g.add_node("probe", lambda s: {"meta": self._step_probe(s["video_path"])})
        g.add_node("scene", lambda s: {"scenes": self._step_scene(s["video_path"], s["meta"])})
        g.add_node("frames", lambda s: {"frames": self._step_frames(s["video_path"], s["scenes"])})
        g.add_node("asr", lambda s: {"transcripts": self._step_asr(s["video_path"], s["scenes"])})
        g.add_node(
            "experts",
            lambda s: {
                "experts": self._step_experts(s["scenes"], s["frames"], s["transcripts"], s["meta"])
            },
        )
        g.add_edge(START, "probe")
        g.add_edge("probe", "scene")
        g.add_edge("scene", "frames")
        g.add_edge("scene", "asr")
        g.add_edge("frames", "experts")
        g.add_edge("asr", "experts")
        g.add_edge("experts", END)
        return g.compile()

    def _run_with_graph(self, video_path: Optional[str], asset_id: str) -> AnalysisReport:
        graph = self._build_graph()
        state = graph.invoke({"video_path": video_path, "asset_id": asset_id})
        return self._assemble(
            video_path,
            state["meta"],
            state["scenes"],
            state["frames"],
            state["transcripts"],
            state["experts"],
            asset_id,
        )
