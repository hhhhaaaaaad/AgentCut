"""The same fictional corpus is exercised by Python, Java, and TypeScript."""
import copy
import json
from pathlib import Path
import runpy

import pytest
from pydantic import ValidationError

from app.schemas.script_contracts_v1 import ScriptContractBundleV1

ROOT = Path(__file__).resolve().parents[2]
CORPUS = json.loads((ROOT / "docs/contracts/script-contracts-v1.fixtures.json").read_text())


def apply_case(case):
    value = copy.deepcopy(CORPUS["base"])
    for patch in case["patches"]:
        node = value
        for key in patch["path"][:-1]:
            node = node[key]
        key = patch["path"][-1]
        if patch["op"] == "remove":
            del node[key]
        else:
            node[key] = copy.deepcopy(patch["value"])
    return value


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda case: case["name"])
def test_shared_b1_corpus(case):
    value = apply_case(case)
    if case["valid"]:
        result = ScriptContractBundleV1.model_validate(value)
        ScriptContractBundleV1.model_validate_json(result.model_dump_json())
    else:
        with pytest.raises(ValidationError):
            ScriptContractBundleV1.model_validate(value)


def test_generated_schemas_and_dtos_have_no_drift():
    generator = runpy.run_path(str(ROOT / "scripts/generate_b1_contracts.py"))
    for path, content in generator["render_files"]().items():
        assert path.read_text() == content, str(path.relative_to(ROOT))


def test_fictional_corpus_is_reproducible():
    generator = runpy.run_path(str(ROOT / "scripts/generate_b1_fixtures.py"))
    assert CORPUS == generator["build_manifest"]()


def test_document_and_execution_contracts_stay_separate():
    from app.schemas.plan import Plan
    with pytest.raises(ValidationError):
        Plan.model_validate(CORPUS["base"]["script"])
