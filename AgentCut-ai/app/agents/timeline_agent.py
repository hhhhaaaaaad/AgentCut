"""TimelineAgent：时间轴分析师（app.agents.timeline_agent）。

规则为主：场景边界 + ASR 密度 → 章节切分 + 废话区间 + 语速密度。
LLM 仅填章节标题（可选，MVP 暂留空），规则兜底保证无 LLM 也可用。
"""

import logging
from typing import List

from app import config
from app.agents._common import detect_silence
from app.schemas.analysis import TranscriptSegment
from app.schemas.expert import Chapter, TimelineAnalysis
from app.schemas.plan import TimeRange

logger = logging.getLogger(__name__)


class TimelineAgent:
    """时间轴分析师：场景 + transcript + meta → TimelineAnalysis。"""

    def __init__(self, llm=None):
        self.llm = llm if llm is not None else config.get_langchain_chat_model()

    def run(self, scenes, transcripts, meta) -> TimelineAnalysis:
        chapters = self._merge_boundaries(scenes, transcripts)
        filler = self._detect_filler(scenes, transcripts)
        density = self._compute_density(scenes, transcripts)
        return TimelineAnalysis(
            chapters=chapters,
            fillerRanges=filler,
            sceneSpeechDensity=density,
            notes="",
        )

    def _merge_boundaries(self, scenes, transcripts) -> List[Chapter]:
        """场景边界 → 章节（MVP：一场景一章节，type 按是否有口播粗分）。"""
        chapters: List[Chapter] = []
        for i, sc in enumerate(scenes):
            has_speech = any(t.start < sc.end and t.end > sc.start for t in transcripts)
            chapters.append(
                Chapter(
                    index=i,
                    start=sc.start,
                    end=sc.end,
                    title="",
                    type="body" if has_speech else "filler",
                )
            )
        return chapters

    def _detect_filler(self, scenes, transcripts) -> List[TimeRange]:
        """静音/无口播区间 → 废话区间（复用 _common.detect_silence，SilenceRange→TimeRange）。"""
        silences = detect_silence(transcripts, scenes)
        return [TimeRange(start=s.start, end=s.end) for s in silences]

    def _compute_density(self, scenes, transcripts) -> List[float]:
        """每场景语速密度（字/秒，约 20 字/秒为满 1.0）。"""
        density: List[float] = []
        for sc in scenes:
            dur = max(sc.end - sc.start, 1e-6)
            chars = sum(
                len(t.text)
                for t in transcripts
                if t.start < sc.end and t.end > sc.start
            )
            density.append(min(1.0, chars / dur / 20.0))
        return density
