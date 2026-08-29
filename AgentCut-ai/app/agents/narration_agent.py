"""NarrationAgent：讲解内容分析师（app.agents.narration_agent）。

吃完整 transcript（不再 800 字截断），用 LLM 抽取主题/论点/关键句/冗余/情绪强调点。
失败降级到规则兜底 _fallback。
"""

import json
import logging
from typing import List, Optional

from app import config
from app.schemas.analysis import TranscriptSegment
from app.schemas.expert import (
    Argument,
    EmphasisPoint,
    KeySentence,
    NarrationAnalysis,
    RedundantRange,
)

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


class NarrationAgent:
    """讲解内容分析师：完整 transcript + 场景 → NarrationAnalysis。"""

    def __init__(self, llm=None):
        self.llm = llm if llm is not None else config.get_langchain_chat_model()

    def run(self, transcripts, scenes, meta) -> NarrationAnalysis:
        if config.SIMULATE_FORCED or self.llm is None:
            return self._fallback(transcripts, scenes)
        try:
            prompt = self._build_prompt(transcripts, scenes)
            raw = self.llm.invoke(prompt)
            text = raw.content if hasattr(raw, "content") else str(raw)
            parsed = self._parse(text)
            if parsed is not None:
                return parsed
        except Exception as exc:  # pragma: no cover - 网络/解析异常降级
            logger.warning("[narration] LLM 抽取失败，回退规则：%s", exc)
        return self._fallback(transcripts, scenes)

    def _build_prompt(self, transcripts, scenes) -> str:
        schema_json = json.dumps(NarrationAnalysis.model_json_schema(), ensure_ascii=False)
        transcript_text = "\n".join(
            f"[{t.start:.1f}-{t.end:.1f}] {t.text}" for t in transcripts
        )
        scene_text = "\n".join(
            f"scene{i}: {s.start:.1f}-{s.end:.1f}" for i, s in enumerate(scenes)
        )
        return (
            "你是 AgentCut 的讲解内容分析师。请根据视频完整口播转写（含时间戳）与场景边界，"
            "抽取讲解内容的结构化信息。\n"
            "必须严格符合以下 JSON Schema（字段名、required 必须一致，不输出 schema 外字段）：\n"
            f"{schema_json}\n\n"
            f"场景边界：\n{scene_text}\n\n"
            f"完整转写：\n{transcript_text}\n\n"
            "请只输出一个符合上述 JSON Schema 的 JSON 对象，不要输出任何解释、前后缀或代码块标记。"
        )

    def _parse(self, text: str) -> Optional[NarrationAnalysis]:
        try:
            return NarrationAnalysis.model_validate(json.loads(_extract_json(text)))
        except Exception as exc:  # pragma: no cover
            logger.warning("[narration] JSON 解析失败：%s", exc)
            return None

    def _fallback(self, transcripts, scenes) -> NarrationAnalysis:
        """规则兜底：首句=主题、每场景最长句=关键句、无口播场景=冗余。"""
        texts = [t for t in transcripts if t.text.strip()]
        theme = texts[0].text.strip()[:30] if texts else ""

        key_sentences: List[KeySentence] = []
        redundancy: List[RedundantRange] = []
        arguments: List[Argument] = []

        for i, sc in enumerate(scenes):
            in_scene = [t for t in texts if t.start < sc.end and t.end > sc.start]
            if not in_scene:
                redundancy.append(
                    RedundantRange(sceneIndex=i, start=sc.start, end=sc.end, reason="无口播")
                )
                continue
            longest = max(in_scene, key=lambda t: len(t.text))
            key_sentences.append(
                KeySentence(
                    sceneIndex=i,
                    start=longest.start,
                    end=longest.end,
                    text=longest.text.strip()[:80],
                    importance=min(1.0, len(longest.text) / 120.0),
                )
            )
            claim = " ".join(t.text for t in in_scene)[:80]
            density = sum(len(t.text) for t in in_scene) / max(sc.end - sc.start, 1e-6)
            arguments.append(
                Argument(
                    index=len(arguments),
                    claim=claim,
                    sceneIndices=[i],
                    importance=min(1.0, density / 8.0),
                )
            )

        return NarrationAnalysis(
            theme=theme,
            summary=theme,
            arguments=arguments,
            keySentences=key_sentences,
            redundancy=redundancy,
            emphasis=[],
        )
