"""Offline window plan + declared hashes/local video -> selected frame evidence.

No settings, credentials, model clients or live task endpoints are loaded.
"""

import argparse
import json
from pathlib import Path

from app.analysis.frame_selection import (
    FrameSample, FrameSelectionConfig, FrameSelectionResult, select_frames,
)
from app.analysis.window_planner import PlanningResult
from app.schemas.script_contracts_v1 import Contract


class OfflineSamplesInput(Contract):
    config: FrameSelectionConfig = FrameSelectionConfig()
    samples: list[FrameSample]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--samples", type=Path, help="JSON with explicitly sourced frame hashes")
    sources.add_argument("--video", type=Path, help="Decode local video with byte-hash verification")
    parser.add_argument("--config", type=Path, help="Selection configuration for --video only")
    parser.add_argument("--max-frames", type=int, default=256, help="Local decode safety limit")
    args = parser.parse_args()
    plan = PlanningResult.model_validate_json(args.plan.read_text(encoding="utf-8"))
    if args.samples:
        if args.config:
            parser.error("--samples already contains its selection config; omit --config")
        request = OfflineSamplesInput.model_validate_json(args.samples.read_text(encoding="utf-8"))
        config, samples = request.config, request.samples
    else:
        from app.tools.window_frames import hash_video_candidates

        config = (FrameSelectionConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
                  if args.config else FrameSelectionConfig())
        samples = hash_video_candidates(str(args.video), plan, config, max_frames=args.max_frames)
    result = select_frames(plan, samples, config)
    output = result.model_dump_json(indent=2)
    FrameSelectionResult.model_validate_json(output)
    args.output.write_text(output + "\n", encoding="utf-8")
    print(json.dumps({"status": result.status, "candidates": len(result.candidates),
        "selectedFrames": sum(len(s.selectedFrameIds) for s in result.selections),
        "failedFrames": sum(len(s.failedFrameIds) for s in result.selections),
        "windows": len(result.selectedWindows), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
