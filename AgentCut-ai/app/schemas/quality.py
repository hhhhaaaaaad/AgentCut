"""QA 质量监督产物（app.schemas.quality）。

质量监督 Agent 输出的结构化评审结果：五维度打分 + 问题清单。
内部契约，extra="ignore" 宽容、核心字段硬校验，model_validate 失败由 quality_agent 降级为 None。
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

QualityDimension = Literal[
    "timeline_continuity",
    "content_integrity",
    "pacing",
    "narration_visual_match",
    "executability",
]
Severity = Literal["high", "medium", "low"]


class QualityIssue(BaseModel):
    """一条质量问题。"""

    model_config = ConfigDict(extra="ignore")

    dimension: QualityDimension
    severity: Severity
    sceneIndex: Optional[int] = None
    reason: str = ""
    suggestion: str = ""


class DimensionScore(BaseModel):
    """单个维度的评分。"""

    model_config = ConfigDict(extra="ignore")

    dimension: QualityDimension
    score: float = Field(ge=0, le=1)


class QualityReview(BaseModel):
    """一次质量评审。"""

    model_config = ConfigDict(extra="ignore")

    overallScore: float = Field(ge=0, le=1)
    passed: bool
    issues: list[QualityIssue] = Field(default_factory=list)
    dimensionScores: list[DimensionScore] = Field(default_factory=list)
    summary: str = ""
