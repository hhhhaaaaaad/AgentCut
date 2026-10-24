"""Reproducible simulated ID-director example. No media, models, or environment files."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "AgentCut-ai"))

from app.analysis.material_index import MaterialEvidence, TranscriptDependency
from app.analysis.offline_id_director import OfflineDirectorInput, run_offline
from app.analysis.source_index import DetectorIdentity, build_source_index
from app.schemas.script_contracts_v1 import (
    AnalyzeInputV1, AssetRef, IndexTranscript, Observation, Provenance, Range,
    Target, TaskSubmissionV1, input_hash,
)


def build_request():
    simulated = Provenance(mode="SIMULATED", provider="hand-authored-fixture", model=None,
        reason="Fictional evidence for offline ID selection; no model or media processing")
    asset = AssetRef(assetId="id_director_fixture", assetHash="sha256:" + "a" * 64,
                     durationMs=20000, displayName="fictional-camera-demo.mp4")
    source = build_source_index(asset, [Range(startMs=t, endMs=t + 4000) for t in range(0, 20000, 4000)],
        DetectorIdentity(name="fixture", version="1", settingsHash="sha256:" + "b" * 64), simulated)
    transcripts = [IndexTranscript(transcriptId=ref, sourceRange=Range(startMs=start, endMs=end),
        text=text, timingQuality="COARSE_BLOCK", source=simulated)
        for ref, start, end, text in [
            ("intro", 500, 3500, "先装好镜头，确认卡口锁紧。"),
            ("demo", 4500, 7500, "取下镜头盖后，再开机测试镜头。"),
            ("ending", 18500, 19500, "关机收好相机。"),
        ]]
    evidence = MaterialEvidence(evidenceId="camera_evidence", assetRef=asset, transcripts=transcripts,
        observations=[Observation(frameId=f"frame_{i}", sceneId=source.scenes[i].sceneId,
            timestampMs=2000 + i * 4000, description="展示镜头操作", source=simulated) for i in range(2)],
        dependencies=[TranscriptDependency(transcriptId="demo", dependsOnTranscriptId="intro",
                                           kind="CONDITION", level="REQUIRED")])
    target = Target(mode="TOPIC_EXTRACT", topic="镜头", maxDurationMs=10000, desiredDurationMs=8000,
        aspectRatio="9:16", subtitleRequested=True, style="原声演示", contentType="TUTORIAL_INTERVIEW",
        editPolicy="ORIGINAL_ORDER_ORIGINAL_SPEED_HARD_CUT")
    submission = TaskSubmissionV1(protocolVersion="1.0", messageType="ANALYZE_REQUEST", taskId="task_camera",
        projectId="project_camera", runId="run_camera", attempt=1, inputHash="sha256:" + "0" * 64,
        configVersion="offline-id-fixture-1", input=AnalyzeInputV1(inputSchemaVersion="1.0", requestId="request_camera",
            assetId=asset.assetId, taskName="镜头使用演示", target=target), assetRef=asset,
        mediaObjectKey="fixtures/camera.mp4", callbackUrl="http://127.0.0.1:8080/unused-offline-callback")
    submission.inputHash = input_hash(submission)
    return OfflineDirectorInput(sourceIndex=source, evidence=evidence, submission=submission)


def render_files():
    request = build_request()
    result = run_offline(request)
    script = result.run.script
    summary = {"sourceScenes": len(result.materialBuild.materialIndex.scenes),
        "units": len(result.materialBuild.materialIndex.units), "status": result.run.status,
        "selectedUnits": [ref for r in result.run.decision.rows for ref in r.sourceUnitRefs],
        "sourceParts": [p.sourceRange.model_dump() for r in script.rows for p in r.sourceParts],
        "outputRanges": [r.outputRange.model_dump() for r in script.rows],
        "durationMs": script.estimatedDurationMs, "riskCodes": sorted({r.code for r in script.riskItems}),
        "reviewStatus": script.reviewStatus}
    return {
        ROOT / "docs/contracts/offline-id-director.input.json": request.model_dump_json(indent=2) + "\n",
        ROOT / "docs/contracts/offline-id-director.summary.json": json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        ROOT / "docs/contracts/offline-id-director.bundle.json": result.contract_bundle().model_dump_json(indent=2) + "\n",
    }


if __name__ == "__main__":
    for path, content in render_files().items():
        path.write_text(content, encoding="utf-8")
