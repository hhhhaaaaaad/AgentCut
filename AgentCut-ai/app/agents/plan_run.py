"""旧 Plan 1.0 决策闭环的执行记录；不替代 B1 EditingScript 契约。"""

import hashlib
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.agents.validator import ValidationResult
from app.schemas.plan import Plan
from app.schemas.quality import QualityReview


def candidate_hash(plan: Plan) -> str:
    """绑定实际交付方案（包括顺序、操作和 source），拒绝非有限 JSON 数字。"""
    payload = json.dumps(
        plan.to_contract_dict(), sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PlanAttempt(BaseModel):
    iteration: int = Field(ge=1, le=3)
    candidateHash: Optional[str] = None
    outcome: Literal[
        "GENERATION_FAILED", "VALIDATION_FAILED", "REVIEWED",
        "QA_UNAVAILABLE", "BUDGET_EXHAUSTED",
    ]
    validation: Optional[ValidationResult] = None
    quality: Optional[QualityReview] = None
    elapsedMs: int = Field(ge=0)


class PlanningRun(BaseModel):
    version: Literal["1.0"] = "1.0"
    strategy: Literal["LEGACY_PLAN"] = "LEGACY_PLAN"
    hashScope: Literal["PYTHON_PLAN_1_0"] = "PYTHON_PLAN_1_0"
    attempts: list[PlanAttempt] = Field(default_factory=list)
    selectedCandidateHash: str
    selectedIteration: Optional[int] = None
    planSource: Literal["REAL", "DETERMINISTIC_FALLBACK"]
    reviewStatus: Literal["READY", "NEEDS_REVIEW"]
    reviewReasons: list[str]
    validation: ValidationResult
    stopReason: Literal[
        "QUALITY_ACCEPTED", "ITERATIONS_EXHAUSTED", "BUDGET_EXHAUSTED",
        "QA_UNAVAILABLE", "NO_VALID_CANDIDATE", "DETERMINISTIC_MODE",
    ]
