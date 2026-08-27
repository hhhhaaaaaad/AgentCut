"""分析报告 Pydantic 模型（app.schemas.analysis）。

AnalysisReport 是 AnalysisAgent 的产物，描述"视频里有什么、哪里值得剪"，
供 PlanAgent 据此生成剪辑方案。仅服务内部使用，不对齐外部契约。
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Scene(BaseModel):
    """一个场景（镜头）及其语义描述。"""

    index: int
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    duration: Optional[float] = None
    description: str = ""
    keyFramePaths: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    importance: float = Field(default=0.5, ge=0, le=1)  # 0~1，越高越值得保留
    reasons: str = ""


class TranscriptSegment(BaseModel):
    """带时间戳的一段转写文本。"""

    index: int
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    speaker: Optional[str] = None


class HighlightClip(BaseModel):
    """亮点片段（候选保留片段）。"""

    sceneIndex: int
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    reason: str = ""
    score: float = Field(default=0.5, ge=0, le=1)


class SilenceRange(BaseModel):
    """静音区间（可作删除 / 去静音候选）。"""

    start: float = Field(ge=0)
    end: float = Field(ge=0)
    duration: Optional[float] = None


class EditingSuggestion(BaseModel):
    """剪辑建议（type 与 plan 的 op 类型对应）。"""

    type: Literal["keep", "delete", "speed", "crop", "subtitle", "volume", "mute"]
    sceneIndex: Optional[int] = None
    reason: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class AnalysisReport(BaseModel):
    """视频分析报告（AnalysisAgent 输出）。"""

    assetId: str
    videoUrl: str
    duration: float = Field(ge=0)
    width: int = Field(default=0, ge=0)
    height: int = Field(default=0, ge=0)
    fps: float = Field(default=0, ge=0)
    title: Optional[str] = None
    summary: str = ""
    simulated: bool = False  # 是否为占位 / 模拟数据（无真实环境时）
    scenes: list[Scene] = Field(default_factory=list)
    transcripts: list[TranscriptSegment] = Field(default_factory=list)
    highlights: list[HighlightClip] = Field(default_factory=list)
    silenceRanges: list[SilenceRange] = Field(default_factory=list)
    suggestions: list[EditingSuggestion] = Field(default_factory=list)
    narrationWordsPerMinute: Optional[float] = None
    vlmNotes: str = ""

    def transcript_text(self, start: float, end: float, sep: str = " ") -> str:
        """取 [start, end) 区间内的转写文本（用于拼字幕）。"""
        parts = [
            t.text.strip()
            for t in self.transcripts
            if t.start < end and t.end > start and t.text.strip()
        ]
        return sep.join(parts)
