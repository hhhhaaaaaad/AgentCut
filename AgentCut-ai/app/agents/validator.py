"""确定性校验闸（app.agents.validator）。

纯代码（无 LLM）校验剪辑方案 Plan：基础 R1~R12，加素材绑定、有限数字和保留内容检查。
error 级 → valid=False（上层修订或兜底）；warning 级不触发兜底，但要求人工复核。

规则清单见 .omc/plans/multi-agent-refactor.md §5。
"""

import logging
import math
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.analysis import AnalysisReport
from app.schemas.plan import OpCrop, OpSpeed, OpSubtitle, Plan, Segment

logger = logging.getLogger(__name__)

_EPS = 1e-3


class ValidationError(BaseModel):
    """单条校验问题。"""

    rule: str  # 规则 id，如 "source_range_bounds"
    severity: str  # "error" / "warning"
    segmentId: Optional[str] = None
    message: str = ""


class ValidationResult(BaseModel):
    """校验结果：无 error 级问题即 valid=True。"""

    valid: bool
    errors: List[ValidationError] = Field(default_factory=list)
    warnings: List[ValidationError] = Field(default_factory=list)


class DeterministicValidator:
    """校验闸：校验 Plan 的可执行性，不依赖任何模型。"""

    def validate(
        self,
        plan: Plan,
        report: AnalysisReport,
        target,
        *,
        max_speed: float = 2.5,
    ) -> ValidationResult:
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []

        # 使用探测报告作为信任边界，模型不能自行扩大 source.duration 绕过越界检查。
        expected = {
            "assetId": report.assetId, "url": report.videoUrl, "duration": report.duration,
            "width": report.width or 1920, "height": report.height or 1080,
            "fps": report.fps or 30.0,
        }
        if any(getattr(plan.source, key) != value for key, value in expected.items()):
            errors.append(ValidationError(
                rule="source_identity", severity="error",
                message="方案 source 必须与分析报告的素材标识、URL 和探测参数一致",
            ))

        def finite(value):
            if isinstance(value, float):
                return math.isfinite(value)
            if isinstance(value, dict):
                return all(finite(item) for item in value.values())
            if isinstance(value, list):
                return all(finite(item) for item in value)
            return True

        if not finite(plan.model_dump()):
            errors.append(ValidationError(rule="finite_numbers", severity="error", message="方案数字必须有限"))
            return ValidationResult(valid=False, errors=errors)

        kept = [seg for seg in plan.timeline if seg.keep]
        if not kept:
            errors.append(ValidationError(
                rule="kept_content", severity="error", message="方案至少需要一个保留片段",
            ))

        # R1: source_range_bounds
        self._check_source_range_bounds(plan.timeline, report.duration, errors)
        # R2: timeline_order_overlap
        self._check_order_overlap(kept, errors)
        # R12: id_unique
        self._check_id_unique(plan.timeline, errors)

        # 逐段操作检查（R3/R4/R5/R6/R7/R8）
        for seg in plan.timeline:
            self._check_ops(seg, plan.source, report, max_speed, errors, warnings)

        # R9: transition_refs
        self._check_transitions(plan, kept, errors)
        # R10: content_integrity
        self._check_content_integrity(plan, report, warnings)
        # R11: duration_constraint
        self._check_duration_constraint(kept, target, errors)

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    # ------------------------------------------------------------------
    # 各规则私有方法
    # ------------------------------------------------------------------

    @staticmethod
    def _seg_rate(seg: Segment) -> float:
        """片段变速倍率（无 speed 操作时 1.0）。"""
        for op in seg.operations:
            if isinstance(op, OpSpeed):
                return op.rate
        return 1.0

    def _check_source_range_bounds(
        self, kept: List[Segment], duration: float, errors: List[ValidationError]
    ) -> None:
        for seg in kept:
            s, e = seg.sourceRange.start, seg.sourceRange.end
            if not (0 <= s < e <= duration + _EPS):
                errors.append(
                    ValidationError(
                        rule="source_range_bounds",
                        severity="error",
                        segmentId=seg.id,
                        message=f"片段 {seg.id} 区间 [{s}, {e}] 越界（源时长 {duration}s）",
                    )
                )

    def _check_order_overlap(
        self, kept: List[Segment], errors: List[ValidationError]
    ) -> None:
        ordered = sorted(kept, key=lambda s: s.sourceRange.start)
        for a, b in zip(ordered, ordered[1:]):
            if b.sourceRange.start < a.sourceRange.end - _EPS:
                errors.append(
                    ValidationError(
                        rule="timeline_order_overlap",
                        severity="error",
                        segmentId=b.id,
                        message=(
                            f"片段 {a.id} 与 {b.id} 时间轴重叠 "
                            f"（{a.sourceRange.end:.2f} > {b.sourceRange.start:.2f}）"
                        ),
                    )
                )

    @staticmethod
    def _check_id_unique(timeline: List[Segment], errors: List[ValidationError]) -> None:
        seen = set()
        for seg in timeline:
            if seg.id in seen:
                errors.append(
                    ValidationError(
                        rule="id_unique",
                        severity="error",
                        segmentId=seg.id,
                        message=f"segment id 重复: {seg.id}",
                    )
                )
            seen.add(seg.id)

    def _check_ops(
        self,
        seg: Segment,
        source,
        report: AnalysisReport,
        max_speed: float,
        errors: List[ValidationError],
        warnings: List[ValidationError],
    ) -> None:
        rate = self._seg_rate(seg)
        out_dur = (seg.sourceRange.end - seg.sourceRange.start) / max(rate, 1e-6)

        if not seg.keep and seg.operations:
            errors.append(
                ValidationError(
                    rule="keep_false_no_ops",
                    severity="error",
                    segmentId=seg.id,
                    message=f"keep=false 片段 {seg.id} 不应携带 operations",
                )
            )

        for i, op in enumerate(seg.operations):
            if isinstance(op, OpCrop):  # R3
                if not (
                    op.x >= -_EPS
                    and op.y >= -_EPS
                    and op.x + op.width <= source.width + _EPS
                    and op.y + op.height <= source.height + _EPS
                ):
                    errors.append(
                        ValidationError(
                            rule="crop_bounds",
                            severity="error",
                            segmentId=seg.id,
                            message=(
                                f"crop 越界: x={op.x} y={op.y} w={op.width} h={op.height} "
                                f"超出源 {source.width}x{source.height}"
                            ),
                        )
                    )
            elif isinstance(op, OpSpeed):  # R4 + R5
                if op.rate <= 0:
                    errors.append(
                        ValidationError(
                            rule="speed_valid",
                            severity="error",
                            segmentId=seg.id,
                            message=f"speed rate={op.rate} 必须 > 0",
                        )
                    )
                elif op.rate > max_speed:
                    warnings.append(
                        ValidationError(
                            rule="speed_valid",
                            severity="warning",
                            segmentId=seg.id,
                            message=f"speed rate={op.rate} 超过上限 {max_speed}",
                        )
                    )
                if i != len(seg.operations) - 1:
                    warnings.append(
                        ValidationError(
                            rule="speed_order",
                            severity="warning",
                            segmentId=seg.id,
                            message="OpSpeed 不在 operations 末位",
                        )
                    )
            elif isinstance(op, OpSubtitle):  # R6
                if not (0 <= op.start < op.end <= out_dur + _EPS):
                    errors.append(
                        ValidationError(
                            rule="subtitle_bounds",
                            severity="error",
                            segmentId=seg.id,
                            message=f"字幕区间 [{op.start}, {op.end}] 超出成片时长 {out_dur:.2f}s",
                        )
                    )
                # R7: subtitle_narration_match（warning）
                self._check_subtitle_match(seg, op, report, warnings)

    def _check_subtitle_match(
        self,
        seg: Segment,
        op: OpSubtitle,
        report: AnalysisReport,
        warnings: List[ValidationError],
    ) -> None:
        if not op.text.strip():
            return
        spoken = report.transcript_text(seg.sourceRange.start, seg.sourceRange.end, sep="")
        if not spoken:
            warnings.append(
                ValidationError(
                    rule="subtitle_narration_match",
                    severity="warning",
                    segmentId=seg.id,
                    message=f"片段 {seg.id} 字幕有文本但区间内无转写（口播-字幕不匹配）",
                )
            )
            return
        overlap = _char_overlap(op.text, spoken)
        if overlap < 0.3:
            warnings.append(
                ValidationError(
                    rule="subtitle_narration_match",
                    severity="warning",
                    segmentId=seg.id,
                    message=f"字幕与口播重合度 {overlap:.2f} < 0.3",
                )
            )

    def _check_transitions(
        self, plan: Plan, kept: List[Segment], errors: List[ValidationError]
    ) -> None:
        kept_ids = {s.id for s in kept}
        for tr in plan.transitions:
            if tr.from_ not in kept_ids or tr.to not in kept_ids:
                errors.append(
                    ValidationError(
                        rule="transition_refs",
                        severity="error",
                        message=f"transition {tr.from_}->{tr.to} 引用了非保留片段",
                    )
                )

    def _check_content_integrity(
        self, plan: Plan, report: AnalysisReport, warnings: List[ValidationError]
    ) -> None:
        narration = getattr(report, "narration", None)
        if narration is None or not narration.keySentences:
            return
        kept = [s for s in plan.timeline if s.keep]
        top = sorted(narration.keySentences, key=lambda k: k.importance, reverse=True)[:3]
        for ks in top:
            covered = any(
                s.sourceRange.start <= ks.start + _EPS
                and ks.end - _EPS <= s.sourceRange.end
                for s in kept
            )
            if not covered:
                warnings.append(
                    ValidationError(
                        rule="content_integrity",
                        severity="warning",
                        message=(
                            f"关键句 sceneIndex={ks.sceneIndex} ({ks.start:.1f}s~{ks.end:.1f}s) "
                            "未被任何保留片段覆盖"
                        ),
                    )
                )

    def _check_duration_constraint(
        self, kept: List[Segment], target, errors: List[ValidationError]
    ) -> None:
        max_duration = getattr(target, "maxDuration", None)
        if max_duration is None or max_duration <= 0:
            return
        total = sum(
            (seg.sourceRange.end - seg.sourceRange.start) / self._seg_rate(seg)
            for seg in kept
        )
        if total > max_duration + _EPS:
            errors.append(
                ValidationError(
                    rule="duration_constraint",
                    severity="error",
                    message=f"成片时长 {total:.2f}s 超过 maxDuration {max_duration}s",
                )
            )


def _char_overlap(a: str, b: str) -> float:
    """字符集重合度（Jaccard，用于字幕-口播软匹配）。"""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa)
