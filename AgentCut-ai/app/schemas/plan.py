"""剪辑方案 Pydantic 模型（app.schemas.plan）。

严格对齐 docs/plan-schema.json（跨语言契约，字段名 / 类型 / 必填不可改）：
- 顶层 Plan：schemaVersion / planVersion / projectId / title / source / global / timeline / transitions
- 操作 Operation 为判别联合，用 type 字段的 Literal 区分 speed / crop / subtitle / volume / mute
- 全部模型 extra="forbid"，对应 JSON Schema 的 additionalProperties: false

Python 关键字规避：global -> global_，from -> from_，通过 Field(alias=...) 映射，
序列化时 by_alias=True 输出契约原名字段（global / from）。
"""

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimeRange(BaseModel):
    """源时间区间（浮点秒）。"""

    model_config = ConfigDict(extra="forbid")

    start: float = Field(ge=0)
    end: float = Field(ge=0)


class Source(BaseModel):
    """源视频信息（来自 PyAV 探测 / ffprobe）。"""

    model_config = ConfigDict(extra="forbid")

    assetId: str
    url: str
    duration: float = Field(ge=0)
    fps: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class OutputConfig(BaseModel):
    """成片输出配置。"""

    model_config = ConfigDict(extra="forbid")

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    codec: str = Field(default="libx264")
    bitrate: Optional[str] = None


class Bgm(BaseModel):
    """背景音乐（全局级）。"""

    model_config = ConfigDict(extra="forbid")

    url: str
    volume: float = Field(default=0.3, ge=0, le=1)
    loop: bool = Field(default=True)


class SubtitleStyle(BaseModel):
    """字幕样式。"""

    model_config = ConfigDict(extra="forbid")

    fontSize: Optional[int] = Field(default=None, ge=1)
    color: Optional[str] = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    position: Optional[Literal["top", "bottom", "center"]] = None


class Global(BaseModel):
    """全局设置。"""

    model_config = ConfigDict(extra="forbid")

    output: OutputConfig
    bgm: Optional[Bgm] = None
    subtitleStyle: Optional[SubtitleStyle] = None


# ---------------------------------------------------------------------------
# 原子操作（判别联合，按 type 分派）
# ---------------------------------------------------------------------------


class OpSpeed(BaseModel):
    """变速：rate 为速度倍率（>0）。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["speed"]
    rate: float = Field(gt=0)


class OpCrop(BaseModel):
    """裁切：源像素坐标下的裁剪窗口。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["crop"]
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class OpSubtitle(BaseModel):
    """字幕：text 与段内时间范围（start/end 相对片段起点）。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["subtitle"]
    text: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class OpVolume(BaseModel):
    """音量调节：volume 0~1。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["volume"]
    volume: float = Field(ge=0, le=1)


class OpMute(BaseModel):
    """静音。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["mute"]


# 判别联合：与 plan-schema.json 的 operation.oneOf 一致
Operation = Annotated[
    Union[OpSpeed, OpCrop, OpSubtitle, OpVolume, OpMute],
    Field(discriminator="type"),
]


class Segment(BaseModel):
    """时间线片段（顺序即成片顺序；keep=false 表示剪掉）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    keep: bool
    sourceRange: TimeRange
    operations: list[Operation] = Field(default_factory=list)


class Transition(BaseModel):
    """片段间转场。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    type: Literal["fade", "none"]
    duration: float = Field(default=0.5, ge=0)


class Plan(BaseModel):
    """剪辑方案（跨语言契约，严格对齐 docs/plan-schema.json）。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schemaVersion: Literal["1.0"] = "1.0"
    planVersion: int = Field(ge=1)
    projectId: str
    title: Optional[str] = None
    source: Source
    global_: Global = Field(alias="global")
    timeline: list[Segment] = Field(min_length=1)
    transitions: list[Transition] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_references(self) -> "Plan":
        """转场引用的片段必须存在于 timeline（保证方案可执行）。"""
        ids = {seg.id for seg in self.timeline}
        for tr in self.transitions:
            if tr.from_ not in ids or tr.to not in ids:
                raise ValueError(f"transition 引用不存在的片段: {tr.from_} -> {tr.to}")
        return self

    def to_contract_dict(self) -> dict:
        """序列化为与 plan-schema.json 对齐的 dict。

        - by_alias：输出契约原名字段（global / from）
        - exclude_none：可选字段缺省时整体省略而非输出 null
          （plan-schema 中可选属性均为纯类型，不允许 null，如 title / bgm / subtitleStyle / bitrate）
        """
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)

    def to_contract_json(self) -> str:
        """序列化为与 plan-schema.json 对齐的 JSON 字符串。"""
        return self.model_dump_json(by_alias=True, exclude_none=True)
