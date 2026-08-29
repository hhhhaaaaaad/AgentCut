"""TimelineAgent：时间轴分析师（app.agents.timeline_agent）。

规则为主：场景边界 + ASR 密度 → 章节切分 + 废话区间 + 语速密度。
章节标题用 LLM 轻量填充（失败 / 模拟降级留空），规则兜底保证无 LLM 也可用。
"""

import json
import logging
from typing import Dict, List

from app import config
from app.agents._common import detect_silence
from app.schemas.analysis import TranscriptSegment
from app.schemas.expert import Chapter, TimelineAnalysis
from app.schemas.plan import TimeRange

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> str:
    """剥离可能的 Markdown 代码块包裹，返回纯 JSON 文本。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


def _parse_chapter_titles(text: str) -> Dict[int, str]:
    """解析章节标题 JSON：{"titles": {"0": "开场", ...}} → {int: str}。"""
    data = json.loads(_extract_json(text))
    raw = data.get("titles", {}) if isinstance(data, dict) else {}
    titles: Dict[int, str] = {}
    for k, v in raw.items():
        try:
            titles[int(k)] = str(v).strip()[:16]
        except (TypeError, ValueError):
            continue
    return titles


class TimelineAgent:
    """时间轴分析师：场景 + transcript + meta → TimelineAnalysis。"""

    def __init__(self, llm=None):
        self.llm = llm if llm is not None else config.get_langchain_chat_model()

    def run(self, scenes, transcripts, meta) -> TimelineAnalysis:
        chapters = self._merge_boundaries(scenes, transcripts)
        chapters = self._title_chapters(chapters, transcripts)
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

    def _title_chapters(self, chapters: List[Chapter], transcripts) -> List[Chapter]:
        """LLM 为有口播的 body 章节填标题；失败 / 模拟降级留空。"""
        if config.SIMULATE_FORCED or self.llm is None:
            return chapters
        body_chapters = [c for c in chapters if c.type == "body"]
        if not body_chapters:
            return chapters
        try:
            prompt = self._build_title_prompt(body_chapters, transcripts)
            raw = self.llm.invoke(prompt)
            text = raw.content if hasattr(raw, "content") else str(raw)
            titles = _parse_chapter_titles(text)
            for c in chapters:
                if c.index in titles:
                    c.title = titles[c.index]
        except Exception as exc:  # pragma: no cover - 标题生成失败降级留空
            logger.warning("[timeline] 章节标题生成失败，留空：%s", exc)
        return chapters

    def _build_title_prompt(self, body_chapters: List[Chapter], transcripts) -> str:
        lines = []
        for c in body_chapters:
            text = " ".join(
                t.text for t in transcripts if t.start < c.end and t.end > c.start
            ).strip()
            lines.append(f"- 章节{c.index}（{c.start:.0f}s~{c.end:.0f}s）：{text[:80]}")
        body = "\n".join(lines)
        return (
            "你是视频章节标题生成器。请为下面每个章节起一个 2~8 字的简短标题，概括其内容。\n"
            f"{body}\n\n"
            "只输出 JSON 对象，格式：{\"titles\": {\"章节索引\": \"标题\", ...}}。"
            "不要输出任何解释、前后缀或 Markdown 代码块标记。"
        )

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
