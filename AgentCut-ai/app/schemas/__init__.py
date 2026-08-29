"""Pydantic 模型包（app.schemas）。

- plan.py     剪辑方案模型，严格对齐 docs/plan-schema.json（跨语言契约）
- analysis.py 视频分析报告模型（AnalysisAgent 产物，供 PlanAgent 使用）
"""

from app.schemas.analysis import (
    AnalysisReport,
    EditingSuggestion,
    HighlightClip,
    Scene,
    SilenceRange,
    TranscriptSegment,
)
from app.schemas.expert import (
    Argument,
    Chapter,
    EmphasisPoint,
    KeySentence,
    NarrationAnalysis,
    RedundantRange,
    TimelineAnalysis,
)
from app.schemas.quality import (
    DimensionScore,
    QualityDimension,
    QualityIssue,
    QualityReview,
    Severity,
)
from app.schemas.plan import (
    Bgm,
    Global,
    OpCrop,
    OpMute,
    OpSpeed,
    OpSubtitle,
    OpVolume,
    Operation,
    OutputConfig,
    Plan,
    Segment,
    Source,
    SubtitleStyle,
    TimeRange,
    Transition,
)

__all__ = [
    "Plan",
    "Segment",
    "Operation",
    "OpSpeed",
    "OpCrop",
    "OpSubtitle",
    "OpVolume",
    "OpMute",
    "Source",
    "OutputConfig",
    "Bgm",
    "SubtitleStyle",
    "Global",
    "TimeRange",
    "Transition",
    "AnalysisReport",
    "Scene",
    "TranscriptSegment",
    "HighlightClip",
    "SilenceRange",
    "EditingSuggestion",
    "TimelineAnalysis",
    "Chapter",
    "NarrationAnalysis",
    "Argument",
    "KeySentence",
    "RedundantRange",
    "EmphasisPoint",
    "QualityReview",
    "QualityIssue",
    "DimensionScore",
    "QualityDimension",
    "Severity",
]
