"""Program-built B1 artifacts and adversarial ID proposals; no model/network calls."""

import json
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agents import id_director_agent as director_module
from app.agents.id_director_agent import (
    DirectorPolicy, IDDirectorAgent, decision_from_rows, select_rule_baseline,
)
from app.analysis.material_index import MaterialBuild, build_material_index, evidence_from_legacy
from app.analysis.offline_id_director import OfflineDirectorArtifact, run_offline
from app.analysis.script_compiler import compile_script
from app.schemas.analysis import AnalysisReport, Scene, TranscriptSegment
from app.schemas.script_contracts_v1 import (
    DecisionRow, PackagingProposal, Provenance, Range, ScriptContractBundleV1,
    index_hash, input_hash,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = runpy.run_path(str(ROOT / "scripts/generate_id_director_fixture.py"))
MODEL_SOURCE = Provenance(mode="SIMULATED", provider="local-stub", model=None,
                          reason="Offline test only; no model was called")


@pytest.fixture
def request_data():
    return FIXTURE["build_request"]()


def reseal(request):
    request.submission.inputHash = input_hash(request.submission)
    return request


def indexed(request):
    return build_material_index(request.sourceIndex, request.evidence).materialIndex


def speech(index, transcript_id):
    return next(u for u in index.units if transcript_id in u.transcriptRefs)


def decision(index, submission, refs, *, combine=False):
    rows = [DecisionRow(rowId=f"row_{i}", sourceUnitRefs=group, narrativeRole="OTHER",
                       selectionReason="local test", packagingSuggestions=[])
            for i, group in enumerate([refs] if combine else [[ref] for ref in refs], 1)]
    return decision_from_rows(rows, index, submission)


class StubModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(content=json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else result)


def proposal(request):
    result = select_rule_baseline(indexed(request), request.submission)
    return {"rows": [row.model_dump() for row in result.rows]}


def test_build_retains_full_source_and_original_blocks(request_data):
    result = build_material_index(request_data.sourceIndex, request_data.evidence)
    assert result.status == "INDEXED"
    assert len(result.materialIndex.scenes) == 5
    assert result.selectableCoverageMs == 20000
    unit = speech(result.materialIndex, "demo")
    assert unit.originalText == request_data.evidence.transcripts[1].text
    assert unit.sourceRange == Range(startMs=4500, endMs=7500)
    assert unit.timingQuality == "COARSE_BLOCK"
    assert all(u.asrSource.mode == "UNAVAILABLE" for u in result.materialIndex.units if u.kind == "VISUAL_ONLY")
    MaterialBuild.model_validate_json(result.model_dump_json())


def test_cross_scene_transcript_stays_whole(request_data):
    request_data.evidence.dependencies = []
    request_data.evidence.transcripts = request_data.evidence.transcripts[:1]
    request_data.evidence.transcripts[0].sourceRange = Range(startMs=1000, endMs=6500)
    index = indexed(request_data)
    unit = speech(index, "intro")
    assert len(unit.sceneRefs) == 2
    assert unit.sourceRange == Range(startMs=1000, endMs=6500)


def test_stable_speech_ids_survive_unrelated_frame_and_version_changes(request_data):
    before = build_material_index(request_data.sourceIndex, request_data.evidence)
    request_data.evidence.observations = []
    after = build_material_index(request_data.sourceIndex, request_data.evidence, index_version=2)
    assert speech(before.materialIndex, "intro").unitId == speech(after.materialIndex, "intro").unitId
    assert before.materialIndex.indexHash != after.materialIndex.indexHash


def test_overlapping_blocks_retained_but_excluded_without_trimming(request_data):
    request_data.evidence.dependencies = []
    request_data.evidence.transcripts[0].sourceRange = Range(startMs=1000, endMs=6000)
    request_data.evidence.transcripts[1].sourceRange = Range(startMs=5000, endMs=8000)
    result = build_material_index(request_data.sourceIndex, request_data.evidence)
    assert result.status == "PARTIAL"
    assert result.excludedRanges[0].sourceRange == Range(startMs=1000, endMs=8000)
    assert result.excludedRanges[0].transcriptRefs == ["intro", "demo"]
    assert len(result.materialIndex.transcripts) == 3
    assert {ref for u in result.materialIndex.units for ref in u.transcriptRefs} == {"ending"}
    assert result.selectableCoverageMs == 13000
    assert all(u.sourceRange.endMs <= 1000 or u.sourceRange.startMs >= 8000 for u in result.materialIndex.units)
    request_data.submission.input.target.topic = "相机"
    artifact = run_offline(reseal(request_data))
    assert artifact.run.status == "DRAFT"
    assert artifact.run.script.estimatedDurationMs == 1000
    assert len(artifact.materialBuild.materialIndex.transcripts) == 3


def test_entirely_overlapping_evidence_returns_no_candidate(request_data):
    request_data.evidence.dependencies = []
    request_data.evidence.transcripts = request_data.evidence.transcripts[:2]
    for record in request_data.evidence.transcripts:
        record.sourceRange = Range(startMs=0, endMs=20000)
    artifact = run_offline(request_data)
    assert artifact.materialBuild.materialIndex is None
    assert artifact.run.status == "NO_CANDIDATE"
    assert artifact.run.script is None
    assert artifact.run.error.code == "NO_CANDIDATE"


def test_declared_dependency_to_excluded_evidence_is_rejected(request_data):
    request_data.evidence.transcripts[0].sourceRange.endMs = 6000
    with pytest.raises(ValueError, match="excluded overlapping"):
        indexed(request_data)


@pytest.mark.parametrize("mutation", ["asset", "duration", "frame_scene", "frame_time", "duplicate_transcript", "duplicate_frame"])
def test_foreign_or_duplicate_evidence_is_rejected(request_data, mutation):
    if mutation == "asset":
        request_data.evidence.assetRef.assetId = "foreign"
    elif mutation == "duration":
        request_data.evidence.transcripts[0].sourceRange.endMs = 20001
    elif mutation == "frame_scene":
        request_data.evidence.observations[0].sceneId = "foreign"
    elif mutation == "frame_time":
        request_data.evidence.observations[0].timestampMs = 9000
    elif mutation == "duplicate_transcript":
        request_data.evidence.transcripts.append(request_data.evidence.transcripts[0])
    else:
        request_data.evidence.observations.append(request_data.evidence.observations[0])
    with pytest.raises(ValueError):
        indexed(request_data)


def test_build_replay_rejects_resealed_fabricated_original_text(request_data):
    built = build_material_index(request_data.sourceIndex, request_data.evidence)
    unit = speech(built.materialIndex, "intro")
    unit.originalText = "fabricated quote"
    built.materialIndex.indexHash = index_hash(built.materialIndex)
    with pytest.raises(ValueError, match="replay mismatch"):
        MaterialBuild.model_validate_json(built.model_dump_json())


def test_rule_selection_preserves_required_context_and_program_times(request_data):
    request_data.submission.input.target.topic = "开机"
    reseal(request_data)
    artifact = run_offline(request_data)
    script = artifact.run.script
    assert [p.sourceRange for row in script.rows for p in row.sourceParts] == [
        Range(startMs=500, endMs=3500), Range(startMs=4500, endMs=7500)]
    assert [row.outputRange for row in script.rows] == [Range(startMs=0, endMs=3000), Range(startMs=3000, endMs=6000)]
    assert script.rows[0].narrativeRole == "CONTEXT"
    assert script.estimatedDurationMs == 6000
    assert script.captionCues == []
    assert script.reviewStatus == "NEEDS_REVIEW"
    assert {risk.code for risk in script.riskItems} >= {
        "COARSE_ALIGNMENT", "SUBTITLE_UNAVAILABLE", "UNTRUSTED_SOURCE", "QA_UNAVAILABLE", "SEMANTIC_REVIEW"}
    ScriptContractBundleV1.model_validate_json(artifact.contract_bundle().model_dump_json())


@pytest.mark.parametrize("topic,maximum", [("火星采矿", 10000), ("开机", 5000), ("镜头", 1500)])
def test_no_rule_match_or_fit_returns_explicit_no_candidate(request_data, topic, maximum):
    request_data.submission.input.target.topic = topic
    request_data.submission.input.target.maxDurationMs = maximum
    request_data.submission.input.target.desiredDurationMs = None
    artifact = run_offline(reseal(request_data))
    assert artifact.run.status == "NO_CANDIDATE"
    assert artifact.run.error.code == "NO_CANDIDATE"
    assert "不可行证明" in artifact.run.error.message


def test_required_dependency_cycle_has_finite_closure(request_data):
    from app.analysis.material_index import TranscriptDependency
    request_data.evidence.dependencies.append(TranscriptDependency(
        transcriptId="intro", dependsOnTranscriptId="demo", kind="CONDITION", level="REQUIRED"))
    assert run_offline(request_data).run.script.estimatedDurationMs == 6000


def test_missing_review_dependency_is_disclosed(request_data):
    request_data.evidence.dependencies[0].level = "REVIEW"
    request_data.submission.input.target.topic = "开机"
    script = run_offline(reseal(request_data)).run.script
    assert len(script.rows) == 1
    assert any(r.code == "MISSING_DEPENDENCY" for r in script.riskItems)


def test_real_aligned_caption_uses_output_time_after_deleted_prefix(request_data):
    request_data.evidence.dependencies = []
    record = request_data.evidence.transcripts[1]
    record.timingQuality = "SENTENCE"
    record.source.mode = "REAL"
    index = indexed(request_data)
    chosen = decision(index, request_data.submission, [speech(index, "demo").unitId])
    script = compile_script(index, chosen, request_data.submission)
    assert script.captionCues[0].outputRange == Range(startMs=0, endMs=3000)
    assert script.captionCues[0].text == record.text
    assert script.rows[0].sourceParts[0].sourceRange.startMs == 4500


def test_subtitle_not_requested_produces_no_caption_actions(request_data):
    request_data.submission.input.target.subtitleRequested = False
    script = run_offline(reseal(request_data)).run.script
    assert script.captionCues == []
    assert all(a.type == "ORIGINAL_AUDIO" for a in script.executableActions)


def test_noncontiguous_units_cannot_be_combined_into_one_row(request_data):
    index = indexed(request_data)
    with pytest.raises(ValueError, match="noncontiguous"):
        decision(index, request_data.submission, [speech(index, "intro").unitId, speech(index, "demo").unitId], combine=True)


def test_packaging_stays_manual_and_cannot_become_an_executable_action(request_data):
    index = indexed(request_data)
    chosen = select_rule_baseline(index, request_data.submission)
    chosen.rows[0].packagingSuggestions.append(PackagingProposal(
        suggestionId="title", kind="TITLE", text="人工标题建议；不执行任何命令"))
    script = compile_script(index, chosen, request_data.submission)
    assert script.packagingSuggestions[0].status == "PROPOSED"
    assert {a.type for a in script.executableActions} == {"ORIGINAL_AUDIO"}


@pytest.mark.parametrize("mutation", ["unknown", "repeat", "reorder", "dependency", "source_time", "fake_quote", "command"])
def test_invalid_model_proposals_are_rejected_then_revised(request_data, mutation):
    good = proposal(request_data)
    bad = json.loads(json.dumps(good))
    if mutation == "unknown":
        bad["rows"][0]["sourceUnitRefs"] = ["foreign"]
    elif mutation == "repeat":
        bad["rows"][1]["sourceUnitRefs"] = bad["rows"][0]["sourceUnitRefs"]
    elif mutation == "reorder":
        bad["rows"].reverse()
    elif mutation == "dependency":
        bad["rows"] = bad["rows"][1:]
    else:
        key = {"source_time": "sourceRange", "fake_quote": "originalText", "command": "command"}[mutation]
        bad["rows"][0][key] = "not allowed"
    model = StubModel([bad, good])
    artifact = run_offline(request_data, IDDirectorAgent(model, model_source=MODEL_SOURCE))
    assert artifact.run.selectedMode == "MODEL_SELECTION"
    assert [attempt.code for attempt in artifact.run.attempts] == ["INVALID_PROPOSAL", "VALIDATED_DRAFT"]
    assert "上次硬校验反馈" in model.prompts[1]
    if mutation == "unknown":
        assert "未知单元 ID" in model.prompts[1]
    assert artifact.run.script.reviewStatus == "NEEDS_REVIEW"
    assert "模拟模型" in artifact.run.script.manualNotes


@pytest.mark.parametrize("invalid", ["not JSON", '{"rows":[],"rows":[]}', '{"rows":NaN}', "[" * 2000 + "]" * 2000])
def test_malformed_model_json_keeps_rule_fallback(request_data, invalid):
    model = StubModel([invalid] * 3)
    artifact = run_offline(request_data, IDDirectorAgent(model, model_source=MODEL_SOURCE))
    assert artifact.run.selectedMode == "RULE_BASELINE"
    assert len(artifact.run.attempts) == 3
    assert artifact.run.script.estimatedDurationMs == 6000


def test_model_over_budget_cannot_shorten_or_accelerate_units(request_data):
    good = proposal(request_data)
    request_data.submission.input.target.maxDurationMs = 3000
    request_data.submission.input.target.desiredDurationMs = None
    model = StubModel([good] * 3)
    artifact = run_offline(reseal(request_data), IDDirectorAgent(model, model_source=MODEL_SOURCE))
    assert artifact.run.selectedMode == "RULE_BASELINE"
    assert artifact.run.script.estimatedDurationMs == 3000
    assert len(artifact.run.script.rows) == 1


def test_model_errors_preserve_fallback_and_do_not_publish_raw_error(request_data):
    model = StubModel([RuntimeError("private transport detail"), TimeoutError(), RuntimeError()])
    artifact = run_offline(request_data, IDDirectorAgent(model, model_source=MODEL_SOURCE))
    assert artifact.run.selectedMode == "RULE_BASELINE"
    assert [a.code for a in artifact.run.attempts] == ["MODEL_FAILED", "MODEL_TIMEOUT", "MODEL_FAILED"]
    assert "private transport detail" not in artifact.model_dump_json()


def test_model_requires_explicit_attribution():
    with pytest.raises(ValueError, match="explicit"):
        IDDirectorAgent(StubModel([]))


def test_model_can_decline_without_fabricating_a_script(request_data):
    request_data.submission.input.target.topic = "火星采矿"
    model = StubModel([{"rows": []}])
    artifact = run_offline(reseal(request_data), IDDirectorAgent(model, model_source=MODEL_SOURCE))
    assert artifact.run.status == "NO_CANDIDATE"
    assert artifact.run.script is None
    assert artifact.run.attempts[0].code == "MODEL_NO_SELECTION"
    assert len(model.prompts) == 1


def test_capacity_limit_does_not_silently_drop_index_units(request_data):
    model = StubModel([])
    artifact = run_offline(request_data, IDDirectorAgent(model, model_source=MODEL_SOURCE,
        policy=DirectorPolicy(maxCandidateUnits=1)))
    assert model.prompts == []
    assert artifact.run.stopReason == "CAPACITY_EXCEEDED"
    assert artifact.run.selectedMode == "RULE_BASELINE"
    assert len(artifact.materialBuild.materialIndex.scenes) == 5


def test_mutated_policy_cannot_bypass_iteration_limit(request_data):
    model = StubModel([])
    agent = IDDirectorAgent(model, model_source=MODEL_SOURCE)
    agent.policy.maxIterations = 100
    with pytest.raises(ValueError):
        agent.run(indexed(request_data), request_data.submission)
    assert model.prompts == []


@pytest.mark.parametrize("mutation", ["asset", "input_hash"])
def test_stale_or_foreign_submission_is_rejected_before_model(request_data, mutation):
    index = indexed(request_data)
    if mutation == "asset":
        request_data.submission.assetRef.assetId = "foreign"
    else:
        request_data.submission.inputHash = "sha256:" + "f" * 64
    model = StubModel([])
    with pytest.raises(ValueError):
        IDDirectorAgent(model, model_source=MODEL_SOURCE).run(index, request_data.submission)
    assert model.prompts == []


def test_prompt_and_response_limits_keep_fallback(request_data):
    index = indexed(request_data)
    prompt_model = StubModel([])
    result = IDDirectorAgent(prompt_model, model_source=MODEL_SOURCE,
        policy=DirectorPolicy(maxPromptChars=1000)).run(index, request_data.submission)
    assert result.stopReason == "CAPACITY_EXCEEDED"
    assert prompt_model.prompts == []
    response_model = StubModel(["x" * 101] * 3)
    result = IDDirectorAgent(response_model, model_source=MODEL_SOURCE,
        policy=DirectorPolicy(maxResponseChars=100)).run(index, request_data.submission)
    assert result.selectedMode == "RULE_BASELINE"
    assert len(result.attempts) == 3


def test_late_model_candidate_is_discarded_after_budget_exhaustion(request_data, monkeypatch):
    clock = [0]
    monkeypatch.setattr(director_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    model = StubModel([proposal(request_data)])
    invoke = model.invoke

    def slow(prompt):
        clock[0] = 121
        return invoke(prompt)

    model.invoke = slow
    artifact = run_offline(request_data, IDDirectorAgent(model, model_source=MODEL_SOURCE))
    assert artifact.run.selectedMode == "RULE_BASELINE"
    assert artifact.run.stopReason == "BUDGET_EXHAUSTED"
    assert artifact.run.attempts[0].code == "BUDGET_EXHAUSTED"
    assert len(model.prompts) == 1


def test_reused_agent_does_not_retain_previous_attempts(request_data):
    model = StubModel([proposal(request_data), RuntimeError(), RuntimeError(), RuntimeError()])
    agent = IDDirectorAgent(model, model_source=MODEL_SOURCE)
    first = run_offline(request_data, agent)
    second = run_offline(request_data, agent)
    assert len(first.run.attempts) == 1
    assert len(second.run.attempts) == 3
    assert second.run.selectedMode == "RULE_BASELINE"


def test_resealed_script_cannot_change_program_derived_quote(request_data):
    artifact = run_offline(request_data)
    artifact.run.script.rows[0].spokenQuotes[0].text = "fabricated"
    with pytest.raises(ValueError):
        OfflineDirectorArtifact.model_validate_json(artifact.model_dump_json())


@pytest.mark.parametrize("simulated,expected", [(False, "MIXED"), (True, "SIMULATED")])
def test_legacy_bridge_preserves_block_text_without_inventing_frames(request_data, simulated, expected):
    report = AnalysisReport(assetId=request_data.sourceIndex.assetRef.assetId, videoUrl="",
        duration=20, simulated=simulated, scenes=[Scene(index=0, start=0, end=20, description="No exact frame time")],
        transcripts=[TranscriptSegment(index=0, start=1, end=4, text="  镜头原话\n不改写  ")],
        provenance={"asr": {"mode": "SIMULATED" if simulated else "REAL"}})
    evidence = evidence_from_legacy(report, request_data.sourceIndex, evidence_id="legacy")
    assert evidence.observations == []
    assert evidence.transcripts[0].text == report.transcripts[0].text
    assert evidence.transcripts[0].source.mode == expected
    assert evidence.transcripts[0].timingQuality == "COARSE_BLOCK"
    assert evidence.upstreamAnalysisHash.startswith("sha256:")


def test_legacy_visual_fallback_does_not_mislabel_real_asr(request_data):
    report = AnalysisReport(assetId=request_data.sourceIndex.assetRef.assetId, videoUrl="", duration=20,
        simulated=True, transcripts=[TranscriptSegment(index=0, start=1, end=4, text="镜头原话")],
        provenance={"asr": {"mode": "REAL", "provider": "original-provider", "model": "original-model"},
                    "vlm": {"mode": "SIMULATED"}})
    source = evidence_from_legacy(report, request_data.sourceIndex, evidence_id="legacy").transcripts[0].source
    assert source.mode == "MIXED"
    assert source.provider == "original-provider"
    assert source.model == "original-model"


def test_generated_fixture_is_reproducible_and_cli_is_offline(tmp_path):
    for path, content in FIXTURE["render_files"]().items():
        assert path.read_text(encoding="utf-8") == content
    output = tmp_path / "artifact.json"
    bundle = tmp_path / "bundle.json"
    result = subprocess.run([sys.executable, "-m", "app.analysis.offline_id_director", "--input",
        str(ROOT / "docs/contracts/offline-id-director.input.json"), "--output", str(output),
        "--bundle-output", str(bundle)], cwd=ROOT / "AgentCut-ai", capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["durationMs"] == 6000
    OfflineDirectorArtifact.model_validate_json(output.read_text())
    ScriptContractBundleV1.model_validate_json(bundle.read_text())
    check = subprocess.run([sys.executable, "-c",
        "import sys; import app.analysis.offline_id_director; "
        "assert 'app.config' not in sys.modules; assert 'openai' not in sys.modules; "
        "assert 'langchain_openai' not in sys.modules"], cwd=ROOT / "AgentCut-ai", capture_output=True, text=True)
    assert check.returncode == 0, check.stderr


def test_legacy_report_cli_materializes_conservative_evidence(request_data, tmp_path):
    report = AnalysisReport(assetId=request_data.sourceIndex.assetRef.assetId, videoUrl="",
        duration=20, transcripts=[TranscriptSegment(index=0, start=1, end=4, text="镜头使用说明")])
    paths = {}
    for name, value in [("source", request_data.sourceIndex), ("report", report), ("submission", request_data.submission)]:
        paths[name] = tmp_path / (name + ".json")
        paths[name].write_text(value.model_dump_json(), encoding="utf-8")
    output = tmp_path / "legacy-output.json"
    subprocess.run([sys.executable, "-m", "app.analysis.offline_id_director", "--source-index", str(paths["source"]),
        "--legacy-report", str(paths["report"]), "--submission", str(paths["submission"]), "--output", str(output)],
        cwd=ROOT / "AgentCut-ai", capture_output=True, text=True, check=True)
    artifact = OfflineDirectorArtifact.model_validate_json(output.read_text())
    assert artifact.run.status == "DRAFT"
    assert artifact.materialBuild.evidence.transcripts[0].source.mode == "MIXED"
    assert artifact.materialBuild.evidence.observations == []
