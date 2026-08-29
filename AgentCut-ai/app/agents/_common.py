"""分析层公共工具（app.agents._common）。

从 analysis_agent 抽取的共享函数，供 analysis_agent / timeline_agent 复用，
避免 timeline_agent 顶层 import analysis_agent 构成循环导入。
"""

from typing import List

from app.schemas.analysis import SilenceRange, TranscriptSegment
from app.schemas.plan import TimeRange


def detect_silence(
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
