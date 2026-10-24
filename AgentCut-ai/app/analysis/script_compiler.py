"""ID decisions -> B1 EditingScript. Only the program derives times and quotes."""

from app.analysis.source_index import stable_id
from app.schemas.script_contracts_v1 import (
    Action, CaptionCue, DirectorDecisionV1, EditingScriptV1, IndexRef, MaterialIndexV1,
    PackagingSuggestion, Range, Risk, ScriptRow, SourcePart, SpokenQuote,
    TaskSubmissionV1, ValidationReport, VisualEvidence, require, script_hash,
    validate_decision, validate_index, validate_script, validate_submission,
)

ZERO = "sha256:" + "0" * 64
VERSION = "id-script-compiler-0.1"


def index_ref(index: MaterialIndexV1) -> IndexRef:
    return IndexRef(indexId=index.indexId, indexVersion=index.indexVersion, indexHash=index.indexHash)


def compile_script(index: MaterialIndexV1, decision: DirectorDecisionV1,
                   submission: TaskSubmissionV1, *, selection_note: str = "规则基线草稿") -> EditingScriptV1:
    # Revalidate snapshots, including mutable nested models supplied by callers.
    index = MaterialIndexV1.model_validate(index.model_dump())
    decision = DirectorDecisionV1.model_validate(decision.model_dump())
    submission = TaskSubmissionV1.model_validate(submission.model_dump())
    validate_index(index)
    validate_submission(submission)
    validate_decision(decision, index)
    require(index.assetRef == submission.assetRef and decision.inputHash == submission.inputHash,
            "decision belongs to another asset/input")
    units = {u.unitId: u for u in index.units}
    frames = {f.frameId: f for f in index.observations}
    selected = {ref for row in decision.rows for ref in row.sourceUnitRefs}
    duration = sum(units[ref].sourceRange.endMs - units[ref].sourceRange.startMs for ref in selected)
    require(duration <= submission.input.target.maxDurationMs, "selected whole units exceed maxDurationMs")
    rows, risks, captions, actions, packaging = [], [], [], [], []

    def add_risk(code, message, row_id=None, unit_id=None):
        risk = Risk(
            riskId=stable_id("risk", {"compiler": VERSION, "code": code, "rowId": row_id, "unitId": unit_id}),
            code=code, level="REVIEW", rowRefs=[row_id] if row_id else [],
            unitRefs=[unit_id] if unit_id else [], message=message,
        )
        risks.append(risk)
        return risk.riskId

    cursor = 0
    for number, chosen in enumerate(decision.rows, 1):
        row_units = [units[ref] for ref in chosen.sourceUnitRefs]
        length = sum(u.sourceRange.endMs - u.sourceRange.startMs for u in row_units)
        frame_ids = list(dict.fromkeys(ref for unit in row_units for ref in unit.frameRefs))
        row = ScriptRow(
            rowId=chosen.rowId, shotNo=number, sourceUnitRefs=chosen.sourceUnitRefs,
            sourceParts=[SourcePart(unitId=u.unitId, sourceRange=u.sourceRange) for u in row_units],
            outputRange=Range(startMs=cursor, endMs=cursor + length),
            spokenQuotes=[SpokenQuote(unitId=u.unitId, text=u.originalText) for u in row_units if u.kind == "SPEECH"],
            visualEvidence=[VisualEvidence(frameId=ref, observedDescription=frames[ref].description) for ref in frame_ids],
            narrativeRole=chosen.narrativeRole, selectionReason=chosen.selectionReason,
            dependencyRefs=list(dict.fromkeys(d.unitId for u in row_units for d in u.dependencies)),
            riskRefs=[], treatmentNote="", audioTreatment="ORIGINAL", cutNotes="原序、原速、硬切；不推断句内边界",
        )
        offset = cursor
        for unit in row_units:
            def risk(code, message):
                row.riskRefs.append(add_risk(code, message, chosen.rowId, unit.unitId))

            if unit.timingQuality == "COARSE_BLOCK":
                risk("COARSE_ALIGNMENT", "仅有块级时间，整块选择，不提供句内切点")
            if unit.asrSource.mode not in {"REAL", "NO_SPEECH"}:
                risk("UNTRUSTED_SOURCE", "原声证据为模拟、降级或未知；不得作为已验证原话")
            if not unit.frameRefs or any(frames[ref].source.mode != "REAL" for ref in unit.frameRefs):
                risk("VISUAL_UNVERIFIED", "该单元缺少真实帧观察，需要回查原片")
            if any(d.level == "REVIEW" and d.unitId not in selected for d in unit.dependencies):
                risk("MISSING_DEPENDENCY", "未选择已声明的 REVIEW 上下文依赖，需要人工确认原意")
            if submission.input.target.subtitleRequested and unit.kind == "SPEECH":
                if unit.asrSource.mode == "REAL" and unit.timingQuality in {"SENTENCE", "WORD", "MANUAL"}:
                    cue_id = stable_id("cue", {"rowId": row.rowId, "unitId": unit.unitId})
                    captions.append(CaptionCue(
                        cueId=cue_id, rowId=row.rowId, unitId=unit.unitId, text=unit.originalText,
                        outputRange=Range(startMs=offset, endMs=offset + unit.sourceRange.endMs - unit.sourceRange.startMs),
                        timingQuality=unit.timingQuality,
                    ))
                    actions.append(Action(actionId="action_" + cue_id, type="CAPTION", rowId=row.rowId, cueId=cue_id))
                else:
                    risk("SUBTITLE_UNAVAILABLE", "请求了字幕，但缺少真实可靠的整条对齐；不按字数伪造时间")
            offset += unit.sourceRange.endMs - unit.sourceRange.startMs
        rows.append(row)
        actions.append(Action(actionId="audio_" + row.rowId, type="ORIGINAL_AUDIO", rowId=row.rowId, cueId=None))
        packaging.extend(PackagingSuggestion(**p.model_dump(), rowId=row.rowId, status="PROPOSED")
                         for p in chosen.packagingSuggestions)
        cursor += length
    add_risk("QA_UNAVAILABLE", "此版本尚未经过绑定候选的语义 QA，保留人工复核草稿")
    add_risk("SEMANTIC_REVIEW", "选题相关性及未声明的上下文依赖仍需回查；结构合法不证明原意完整")
    script = EditingScriptV1(
        scriptSchemaVersion="1.0", scriptId=stable_id("script", {
            "compiler": VERSION, "taskId": submission.taskId, "decisionId": decision.decisionId,
        }), revision=1, projectId=submission.projectId, generationTaskId=submission.taskId,
        assetRef=index.assetRef, indexRef=index_ref(index), inputHash=submission.inputHash,
        target=submission.input.target, title=submission.input.taskName,
        rows=rows, estimatedDurationMs=cursor, captionCues=captions, executableActions=actions,
        packagingSuggestions=packaging, manualNotes=selection_note + "；包装仅为建议，未执行；需人工回查原片与原话",
        riskItems=risks, scriptHash=ZERO,
        validationReport=ValidationReport(validationVersion=VERSION, candidateHash=ZERO, hardPassed=True,
                                          issueRefs=[r.riskId for r in risks]),
        quality=None, reviewStatus="NEEDS_REVIEW",
    )
    script.scriptHash = script_hash(script)
    script.validationReport.candidateHash = script.scriptHash
    validate_script(script, index, decision)
    return script
