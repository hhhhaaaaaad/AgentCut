"""Offline material index -> ID decision -> script artifact. Never constructs a model client."""

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import model_validator

from app.agents.id_director_agent import DirectorRun, IDDirectorAgent, selection_note
from app.analysis.material_index import MaterialBuild, MaterialEvidence, build_material_index, evidence_from_legacy
from app.analysis.script_compiler import compile_script
from app.analysis.source_index import SourceIndex
from app.schemas.analysis import AnalysisReport
from app.schemas.script_contracts_v1 import (
    Contract, Positive, ScriptContractBundleV1, TaskError, TaskSubmissionV1, require, validate_submission,
)


class OfflineDirectorInput(Contract):
    sourceIndex: SourceIndex
    evidence: MaterialEvidence
    submission: TaskSubmissionV1
    indexVersion: Positive = 1


class OfflineDirectorArtifact(Contract):
    artifactVersion: Literal["offline-id-director-0.1"] = "offline-id-director-0.1"
    materialBuild: MaterialBuild
    submission: TaskSubmissionV1
    run: DirectorRun

    def contract_bundle(self):
        return ScriptContractBundleV1(
            materialIndex=self.materialBuild.materialIndex, decision=self.run.decision,
            script=self.run.script, submission=self.submission, events=[],
        )

    @model_validator(mode="after")
    def check_context(self):
        validate_submission(self.submission)
        require(self.submission.assetRef == self.materialBuild.sourceIndex.assetRef,
                "artifact submission asset mismatch")
        self.contract_bundle()
        index = self.materialBuild.materialIndex
        if index is None:
            require(self.run.status == "NO_CANDIDATE", "empty index cannot publish a draft")
        if self.run.script is not None:
            expected = compile_script(index, self.run.decision, self.submission,
                selection_note=selection_note(self.run.selectedMode, self.run.modelSource))
            require(self.run.script == expected, "script differs from deterministic compiler output")
        return self


def run_offline(request: OfflineDirectorInput, agent=None):
    request = OfflineDirectorInput.model_validate(request.model_dump())
    validate_submission(request.submission)
    require(request.sourceIndex.assetRef == request.submission.assetRef, "submission asset mismatch")
    built = build_material_index(request.sourceIndex, request.evidence, index_version=request.indexVersion)
    if built.materialIndex is None:
        run = DirectorRun(status="NO_CANDIDATE", selectedMode="NONE", modelSource=None,
            stopReason="NO_SELECTABLE_UNITS", attempts=[], decision=None, script=None,
            error=TaskError(code="NO_CANDIDATE", retryable=False,
                            message="原始转写存在重叠且没有可安全选择的完整单元；未裁剪或编造原话"))
    else:
        run = (agent or IDDirectorAgent()).run(built.materialIndex, request.submission)
    return OfflineDirectorArtifact(materialBuild=built, submission=request.submission, run=run)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Complete offline input JSON")
    parser.add_argument("--source-index", type=Path, help="Standalone SourceIndex JSON for the legacy bridge")
    parser.add_argument("--legacy-report", type=Path, help="Existing AnalysisReport JSON; never reads media")
    parser.add_argument("--submission", type=Path, help="B1 TaskSubmissionV1 JSON for the legacy bridge")
    parser.add_argument("--evidence-id", default="legacy_evidence")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bundle-output", type=Path, help="Optional B1 conformance bundle, with no task events")
    args = parser.parse_args()
    legacy = [args.source_index, args.legacy_report, args.submission]
    if args.input:
        if any(legacy):
            parser.error("--input and legacy bridge paths are mutually exclusive")
        request = OfflineDirectorInput.model_validate_json(args.input.read_text(encoding="utf-8"))
    else:
        if not all(legacy):
            parser.error("provide --input or all of --source-index, --legacy-report, --submission")
        source = SourceIndex.model_validate_json(args.source_index.read_text(encoding="utf-8"))
        report = AnalysisReport.model_validate_json(args.legacy_report.read_text(encoding="utf-8"))
        request = OfflineDirectorInput(sourceIndex=source,
            evidence=evidence_from_legacy(report, source, evidence_id=args.evidence_id),
            submission=TaskSubmissionV1.model_validate_json(args.submission.read_text(encoding="utf-8")))
    artifact = run_offline(request)
    output = artifact.model_dump_json(indent=2)
    OfflineDirectorArtifact.model_validate_json(output)
    args.output.write_text(output + "\n", encoding="utf-8")
    if args.bundle_output:
        args.bundle_output.write_text(artifact.contract_bundle().model_dump_json(indent=2) + "\n", encoding="utf-8")
    script = artifact.run.script
    print(json.dumps({"status": artifact.run.status, "mode": artifact.run.selectedMode,
        "sourceScenes": len(artifact.materialBuild.sourceIndex.scenes),
        "selectableCoverageMs": artifact.materialBuild.selectableCoverageMs,
        "excludedRanges": len(artifact.materialBuild.excludedRanges),
        "rows": len(script.rows) if script else 0,
        "durationMs": script.estimatedDurationMs if script else 0,
        "reviewStatus": script.reviewStatus if script else "NOT_AVAILABLE",
        "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
