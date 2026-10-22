"""JSON fixture -> complete source index -> adaptive windows, without AI/config.

Run from AgentCut-ai: python -m app.analysis.offline_planning --input in.json --output out.json
"""

import argparse
import json
from pathlib import Path

from pydantic import StrictBool

from app.analysis.source_index import DetectorIdentity, build_source_index
from app.analysis.window_planner import PlanningResult, ProfileConfig, SilenceCue, WindowPolicy, plan_windows
from app.schemas.script_contracts_v1 import AssetRef, Contract, Provenance, Range


class OfflinePlanningInput(Contract):
    assetRef: AssetRef
    detector: DetectorIdentity
    detectorSource: Provenance
    detectedRanges: list[Range]
    noCuts: StrictBool = False
    profileConfig: ProfileConfig = ProfileConfig()
    silenceCues: list[SilenceCue] = []
    policy: WindowPolicy | None = None


def plan_fixture(data: dict) -> PlanningResult:
    request = OfflinePlanningInput.model_validate(data)
    index = build_source_index(request.assetRef, request.detectedRanges, request.detector,
                               request.detectorSource, no_cuts=request.noCuts)
    return plan_windows(index, request.profileConfig, silence_cues=request.silenceCues, policy=request.policy)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = plan_fixture(json.loads(args.input.read_text(encoding="utf-8")))
    # Serialization must pass the same reader used for persisted offline results.
    output = result.model_dump_json(indent=2)
    PlanningResult.model_validate_json(output)
    args.output.write_text(output + "\n", encoding="utf-8")
    print(json.dumps({"status": result.status, "scenes": len(result.sourceIndex.scenes),
                      "windows": len(result.windows), "plannedCoverageMs": result.plannedCoverageMs,
                      "detectionStatus": result.sourceIndex.detectionStatus,
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
