"""AnalysisAgent：理解视频并产出 AnalysisReport（app.agents.analysis_agent）。

流水线（确定性工具 + VLM 决策）：
    抽帧(PyAV) → 场景检测(PySceneDetect) → ASR(FunASR) → VLM 理解(Qwen2.5-VL) → 组装报告

- 环境中装有 langgraph 且非模拟模式时用 StateGraph 编排；否则顺序执行（二者等价）。
- 无长期记忆：本 agent 无状态，输入视频路径 + 临时工作目录，输出 AnalysisReport。
"""

import logging
import os
from typing import List, Optional

from app import config
from app.schemas.analysis import (
    AnalysisReport,
    EditingSuggestion,
    HighlightClip,
    Scene,
    SilenceRange,
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


def _detect_silence(
    transcripts: List[TranscriptSegment], scenes: List[TimeRange]
) -> List[SilenceRange]:
    """启发式静音检测：无转写文本覆盖的场景视为静音（MVP 简化）。"""
    ranges: List[SilenceRange] = []
    for sc in scenes:
        has_speech = any(t.start < sc.end and t.end > sc.start for t in transcripts)
        if not has_speech:
            ranges.append(
                SilenceRange(
                    start=sc.start, end=sc.end, duration=round(sc.end - sc.start, 3)
                )
            )
    return ranges


class AnalysisAgent:
    """视频分析 Agent：抽帧 / 场景 / ASR / VLM → AnalysisReport。"""

    def __init__(self, work_dir: Optional[str] = None):
        self.work_dir = work_dir or os.path.join(config.WORK_DIR, "analysis")
        os.makedirs(self.work_dir, exist_ok=True)

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
        return vlm_understand.understand_video(scenes, frames, transcripts, meta)

    def _assemble(
        self,
        video_path: Optional[str],
        meta: dict,
        scenes: List[TimeRange],
        frames: List[str],
        transcripts: List[TranscriptSegment],
        vlm: dict,
        asset_id: str,
    ) -> AnalysisReport:
        """把各步骤产物组装为 AnalysisReport。"""
        descs = vlm.get("sceneDescriptions", [])
        tags = vlm.get("sceneTags", [])
        imps = vlm.get("sceneImportance", [])

        scene_objs: List[Scene] = []
        for i, sc in enumerate(scenes):
            scene_objs.append(
                Scene(
                    index=i,
                    start=sc.start,
                    end=sc.end,
                    duration=round(sc.end - sc.start, 3),
                    description=descs[i] if i < len(descs) else "",
                    keyFramePaths=frames[i : i + 1] if i < len(frames) else [],
                    tags=tags[i] if i < len(tags) else [],
                    importance=imps[i] if i < len(imps) else 0.5,
                )
            )

        highlights = [HighlightClip(**h) for h in vlm.get("highlights", [])]
        suggestions = [EditingSuggestion(**s) for s in vlm.get("suggestions", [])]
        silences = _detect_silence(transcripts, scenes)

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
        vlm = self._step_vlm(scenes, frames, transcripts, meta)
        return self._assemble(video_path, meta, scenes, frames, transcripts, vlm, asset_id)

    def _build_graph(self):
        """LangGraph StateGraph：probe → scene → frames/asr → vlm → assemble。"""

        class PipelineState(TypedDict):
            video_path: Optional[str]
            asset_id: str
            meta: dict
            scenes: list
            frames: list
            transcripts: list
            vlm: dict

        g = StateGraph(PipelineState)
        g.add_node("probe", lambda s: {"meta": self._step_probe(s["video_path"])})
        g.add_node("scene", lambda s: {"scenes": self._step_scene(s["video_path"], s["meta"])})
        g.add_node("frames", lambda s: {"frames": self._step_frames(s["video_path"], s["scenes"])})
        g.add_node("asr", lambda s: {"transcripts": self._step_asr(s["video_path"], s["scenes"])})
        g.add_node(
            "vlm",
            lambda s: {
                "vlm": self._step_vlm(s["scenes"], s["frames"], s["transcripts"], s["meta"])
            },
        )
        g.add_edge(START, "probe")
        g.add_edge("probe", "scene")
        g.add_edge("scene", "frames")
        g.add_edge("scene", "asr")
        g.add_edge("frames", "vlm")
        g.add_edge("asr", "vlm")
        g.add_edge("vlm", END)
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
            state["vlm"],
            asset_id,
        )
