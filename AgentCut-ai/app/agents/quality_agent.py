"""QualityAgent：质量监督 Reviewer（app.agents.quality_agent）。

对初版 Plan 做五维度结构化评审，输出 QualityReview；失败返回 None（上层跳过监督）。
"""

import json
import logging
from typing import Optional

from app import config
from app.schemas.analysis import AnalysisReport
from app.schemas.plan import Plan
from app.schemas.quality import QualityReview

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


class QualityAgent:
    """质量监督：Plan + report + target → Optional[QualityReview]。"""

    def __init__(self, llm=None):
        self.llm = llm if llm is not None else config.get_langchain_chat_model()

    def review(
        self, plan: Plan, report: AnalysisReport, target
    ) -> Optional[QualityReview]:
        if config.SIMULATE_FORCED or self.llm is None:
            return None
        try:
            prompt = self._build_prompt(plan, report, target)
            raw = self.llm.invoke(prompt)
            text = raw.content if hasattr(raw, "content") else str(raw)
            return self._parse(text)
        except Exception as exc:  # pragma: no cover - 评审失败跳过监督
            logger.warning("[quality] 评审失败，跳过监督：%s", exc)
            return None

    def _build_prompt(self, plan: Plan, report: AnalysisReport, target) -> str:
        schema_json = json.dumps(QualityReview.model_json_schema(), ensure_ascii=False)
        target_json = (
            target.model_dump(mode="json", by_alias=True)
            if hasattr(target, "model_dump")
            else vars(target)
        )
        narration = getattr(report, "narration", None)
        narration_json = narration.model_dump(mode="json") if narration else {}
        chapters = getattr(report, "chapters", [])
        chapters_json = [c.model_dump(mode="json") for c in chapters] if chapters else []
        return (
            "你是 AgentCut 的质量监督 Agent。请审查下面的剪辑方案，从五个维度打分并列出问题。\n"
            "五维度：timeline_continuity（时间轴连续性）/ content_integrity（内容完整性）/ "
            "pacing（节奏）/ narration_visual_match（口播-画面匹配）/ executability（可执行性）。\n"
            "只挑错、不改方案；每条 issue 必须给出可执行的 suggestion（具体到 segmentId/sceneIndex 与修改方向）。\n"
            "必须严格符合以下 JSON Schema：\n"
            f"{schema_json}\n\n"
            f"用户目标(target):\n{json.dumps(target_json, ensure_ascii=False)}\n"
            f"讲解内容(narration):\n{json.dumps(narration_json, ensure_ascii=False)}\n"
            f"章节(chapters):\n{json.dumps(chapters_json, ensure_ascii=False)}\n"
            f"剪辑方案(plan):\n{plan.model_dump_json(indent=2)}\n\n"
            "请只输出一个符合上述 JSON Schema 的 JSON 对象，不要输出任何解释、前后缀或代码块标记。"
        )

    def _parse(self, text: str) -> Optional[QualityReview]:
        try:
            return QualityReview.model_validate(json.loads(_extract_json(text)))
        except Exception as exc:  # pragma: no cover
            logger.warning("[quality] JSON 解析失败：%s", exc)
            return None
