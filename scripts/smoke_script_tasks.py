"""Offline-evidence HTTP smoke check against explicitly started local services."""

import argparse
import json
from pathlib import Path
import sys
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "AgentCut-ai"))
from app.schemas.script_contracts_v1 import ScriptContractBundleV1


def smoke(base_url, project_id, input_file):
    def http(path, body=None, expected=200):
        request = Request(base_url.rstrip("/") + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=10) as response:
                code, data = response.status, response.read()
        except HTTPError as error:
            code, data = error.code, error.read()
        assert code == expected, (path, code, data[:200])
        return json.loads(data)

    def wait(task_id):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status = http("/api/v1/script-tasks/" + task_id)
            if status["status"] in {"SUCCESS", "NEEDS_REVIEW", "FAILED"}:
                return status
            time.sleep(0.1)
        raise AssertionError("local task did not complete within 20s")

    input_ = json.loads(input_file.read_text(encoding="utf-8"))["submission"]["input"]
    input_["requestId"] = "smoke_" + uuid.uuid4().hex
    path = f"/api/v1/projects/{project_id}/script-tasks"
    first = http(path, input_, 202)
    second = http(path, input_, 202)
    assert first["taskId"] == second["taskId"]
    changed = dict(input_, taskName=input_["taskName"] + " conflict")
    assert http(path, changed, 409)["code"] == "REQUEST_ID_CONFLICT"
    status = wait(first["taskId"])
    assert status["status"] == "NEEDS_REVIEW" and status["progress"] == 100
    result = http("/api/v1/script-tasks/" + first["taskId"] + "/result")
    bundle = ScriptContractBundleV1.model_validate(result)
    script = http("/api/v1/script-tasks/" + first["taskId"] + "/script")
    assert script == bundle.script.model_dump(mode="json")
    assert script["quality"] is None and any(r["code"] == "QA_UNAVAILABLE" for r in script["riskItems"])
    assert "token=" not in json.dumps(result) and "token=" not in json.dumps(status)
    failed_input = json.loads(json.dumps(input_))
    failed_input["requestId"] += "_no_match"
    failed_input["target"]["topic"] = "deliberatelyunmatchedtopic"
    failed = http(path, failed_input, 202)
    failure = wait(failed["taskId"])
    assert failure["status"] == "FAILED" and failure["progress"] < 100
    failed_bundle = http("/api/v1/script-tasks/" + failed["taskId"] + "/result")
    ScriptContractBundleV1.model_validate(failed_bundle)
    assert failed_bundle["script"] is None and failed_bundle["events"][-1]["error"]["code"] == "NO_CANDIDATE"
    assert http("/api/v1/script-tasks/" + failed["taskId"] + "/script", expected=409)["code"] == "SCRIPT_NOT_AVAILABLE"
    page = http(path + "?offset=0&limit=2")
    assert page["items"][0]["taskId"] == failed["taskId"]
    return dict(status=status["status"], rows=len(script["rows"]), durationMs=script["estimatedDurationMs"],
        scriptHash=script["scriptHash"], duplicateReturnedSameTask=True, conflictingRequestRejected=True,
        noCandidateStatus=failure["status"], source="fictional prepared evidence; no live model/media calls")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(smoke(args.base_url, args.project_id, args.input), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
