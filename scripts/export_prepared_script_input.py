"""Place a validated offline B2 input in the operator-owned online task catalog.

This is an explicit local integration tool, not upload/file integrity admission.
No media is read and no model is invoked.
"""

import argparse
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "AgentCut-ai"))

from app.analysis.offline_id_director import OfflineDirectorInput
from app.schemas.script_contracts_v1 import input_hash, validate_submission


def export(source, catalog_dir, project_id):
    if not re.fullmatch(r"[1-9][0-9]*", project_id):
        raise ValueError("project-id must be an existing positive Java project ID")
    prepared = OfflineDirectorInput.model_validate_json(source.read_text(encoding="utf-8"))
    prepared.submission.projectId = project_id
    prepared.submission.inputHash = input_hash(prepared.submission)
    validate_submission(prepared.submission)
    target = catalog_dir / project_id / (prepared.submission.assetRef.assetId + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Immutable import: an existing asset entry must be deliberately versioned by
    # its owner; the helper never silently replaces it.
    with target.open("x", encoding="utf-8") as output:
        output.write(prepared.model_dump_json(indent=2) + "\n")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args()
    print(export(args.input, args.catalog_dir, args.project_id).resolve())


if __name__ == "__main__":
    main()
