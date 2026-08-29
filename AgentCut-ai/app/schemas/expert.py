"""分析专家结构化产物（app.schemas.expert）。

时间轴分析师（TimelineAnalysis）与讲解内容分析师（NarrationAnalysis）的输出契约。
仅服务内部，不对齐外部契约；extra="ignore" 宽容 LLM 漂移字段，model_validate 失败由 agent 降级。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.plan import TimeRange


class Chapter(BaseModel):
    """一个章节（时间轴切分）。"""

    model_config = ConfigDict(extra="ignore")

    index: int
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    title: str = ""
    type: Literal["intro", "body", "transition", "filler", "outro", "summary"] = "body"


class TimelineAnalysis(BaseModel):
    """时间轴分析师产物：章节 / 废话区间 / 每场景语速密度。"""

    model_config = ConfigDict(extra="ignore")

    chapters: list[Chapter] = Field(default_factory=list)
    fillerRanges: list[TimeRange] = Field(default_factory=list)  # 废话/静音区间
    sceneSpeechDensity: list[float] = Field(default_factory=list)  # 每场景 0~1
    notes: str = ""


class Argument(BaseModel):
    """讲解中的一个论点。"""

    model_config = ConfigDict(extra="ignore")

    index: int
    claim: str = ""
    sceneIndices: list[int] = Field(default_factory=list)
    importance: float = Field(ge=0, le=1, default=0.5)


class KeySentence(BaseModel):
    """关键句（核心内容，需保留）。"""

    model_config = ConfigDict(extra="ignore")

    sceneIndex: int
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str = ""
    importance: float = Field(ge=0, le=1, default=0.5)


class RedundantRange(BaseModel):
    """冗余区间（可删除候选）。"""

    model_config = ConfigDict(extra="ignore")

    sceneIndex: int
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    reason: str = ""


class EmphasisPoint(BaseModel):
    """情绪强调点。"""

    model_config = ConfigDict(extra="ignore")

    sceneIndex: int
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    reason: str = ""


class NarrationAnalysis(BaseModel):
    """讲解内容分析师产物。"""

    model_config = ConfigDict(extra="ignore")

    theme: str = ""
    summary: str = ""
    arguments: list[Argument] = Field(default_factory=list)
    keySentences: list[KeySentence] = Field(default_factory=list)
    redundancy: list[RedundantRange] = Field(default_factory=list)
    emphasis: list[EmphasisPoint] = Field(default_factory=list)
