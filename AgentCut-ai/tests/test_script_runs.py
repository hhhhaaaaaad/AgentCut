"""Online mechanics with prepared fictional evidence; no media or model calls."""

import asyncio
import json
from pathlib import Path
import threading

import httpx
import pytest
from fastapi import HTTPException

from app.api.script_runs import ScriptRunRequest, ScriptRunService, create_script_app, execute_prepared
from app.schemas.script_contracts_v1 import ScriptContractBundleV1, input_hash

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def prepared_request():
    data = json.loads((ROOT / "docs/contracts/offline-id-director.input.json").read_text())
    data["submission"]["callbackUrl"] = ("http://127.0.0.1:8080/api/v1/script-tasks/"
        + data["submission"]["taskId"] + "/events?token=" + "a" * 32)
    return ScriptRunRequest.model_validate(dict(prepared=data))


def test_idempotent_completed_run_does_not_execute_again(prepared_request):
    async def check():
        calls, deliveries = [], []
        def engine(prepared, progress):
            calls.append(prepared.submission.runId)
            return execute_prepared(prepared, progress)
        async def notify(url, payload):
            deliveries.append(payload)
            return True
        service = ScriptRunService(engine=engine, notify=notify)
        first = await service.submit(prepared_request)
        assert await service.submit(prepared_request) == first
        await service.drain()
        assert await service.submit(prepared_request) == first
        assert len(calls) == 1
        status = service.status(first["runId"])
        assert status["executionStatus"] == "SUCCESS"
        assert status["bundle"]["script"]["reviewStatus"] == "NEEDS_REVIEW"
        assert status["bundle"]["script"]["quality"] is None
        assert status["callbackDelivered"] is True
        ScriptContractBundleV1.model_validate(status["bundle"])
        assert [p["event"]["sequence"] for p in deliveries] == [1, 2, 3]
        assert deliveries[-1]["event"]["progress"] == 100
        status["bundle"]["script"]["title"] = "tampered client response"
        assert service.status(first["runId"])["bundle"]["script"]["title"] != "tampered client response"
    asyncio.run(check())


@pytest.mark.parametrize("change", ["target", "evidence", "callback", "identity"])
def test_same_run_different_snapshot_conflicts(prepared_request, change):
    async def check():
        async def notify(*_): return True
        service = ScriptRunService(notify=notify)
        await service.submit(prepared_request)
        changed = prepared_request.model_copy(deep=True)
        if change == "target":
            changed.prepared.submission.input.target.topic += " changed"
            changed.prepared.submission.inputHash = input_hash(changed.prepared.submission)
        elif change == "evidence":
            changed.prepared.evidence.evidenceId += "_changed"
        elif change == "callback":
            changed.prepared.submission.callbackUrl = changed.prepared.submission.callbackUrl[:-1] + "b"
        else:
            changed.prepared.submission.input.requestId += "_new"
        with pytest.raises(HTTPException) as error:
            await service.submit(changed)
        assert error.value.status_code == 409
        await service.drain()
    asyncio.run(check())


def test_capacity_reservation_is_bounded_but_duplicate_still_accepted(prepared_request):
    async def check():
        entered, release = threading.Event(), threading.Event()
        def engine(prepared, progress):
            entered.set()
            assert release.wait(5)
            return execute_prepared(prepared, progress)
        async def notify(*_): return True
        service = ScriptRunService(max_active=1, max_retained=2, engine=engine, notify=notify)
        first = await service.submit(prepared_request)
        await asyncio.to_thread(entered.wait, 5)
        try:
            assert await service.submit(prepared_request) == first
            changed = prepared_request.model_copy(deep=True)
            changed.prepared.submission.runId += "_2"
            with pytest.raises(HTTPException) as error:
                await service.submit(changed)
            assert error.value.status_code == 503
        finally:
            release.set()
            await service.drain()
        await service.submit(changed)
        await service.drain()
        changed.prepared.submission.runId += "_3"
        with pytest.raises(HTTPException) as error:
            await service.submit(changed)
        assert error.value.status_code == 503
    asyncio.run(check())


def test_no_candidate_and_invalid_engine_never_publish_normal_artifacts(prepared_request):
    async def check():
        async def notify(*_): return False
        prepared_request.prepared.submission.input.target.topic = "completelyunmatchedkeyword"
        prepared_request.prepared.submission.inputHash = input_hash(prepared_request.prepared.submission)
        service = ScriptRunService(notify=notify)
        accepted = await service.submit(prepared_request)
        await service.drain()
        status = service.status(accepted["runId"])
        event = status["events"][-1]
        assert event["error"]["code"] == "NO_CANDIDATE"
        assert status["executionStatus"] == "FAILED"
        assert event["progress"] < 100
        assert all(status["bundle"][key] is None for key in ("script", "decision", "materialIndex"))
        ScriptContractBundleV1.model_validate(status["bundle"])
        def broken(*_): raise RuntimeError("provider secret must not escape")
        service = ScriptRunService(engine=broken, notify=notify)
        await service.submit(prepared_request)
        await service.drain()
        status = service.status(accepted["runId"])
        assert status["events"][-1]["error"]["code"] == "VALIDATION_FAILED"
        assert "secret" not in json.dumps(status)
        assert service.active == 0
    asyncio.run(check())


def test_callback_failure_is_reconcilable_and_explicit_redelivery_reports_actual_result(prepared_request):
    async def check():
        delivered = False
        async def notify(*_): return delivered
        service = ScriptRunService(notify=notify)
        first = await service.submit(prepared_request)
        await service.drain()
        assert not service.status(first["runId"])["callbackDelivered"]
        assert await service.redeliver(first["runId"]) == {"callbackDelivered": False}
        delivered = True
        assert await service.redeliver(first["runId"]) == {"callbackDelivered": True}
        assert service.status(first["runId"])["bundle"] is not None
    asyncio.run(check())


def test_engine_cannot_substitute_an_internally_valid_but_different_evidence_snapshot(prepared_request):
    async def check():
        async def notify(*_): return True
        def substituted(prepared, progress):
            prepared.evidence.evidenceId += "_foreign"
            return execute_prepared(prepared, progress)
        service = ScriptRunService(engine=substituted, notify=notify)
        acceptance = await service.submit(prepared_request)
        await service.drain()
        result = service.status(acceptance["runId"])
        assert result["executionStatus"] == "FAILED"
        assert result["bundle"]["script"] is None
        assert result["events"][-1]["error"]["code"] == "VALIDATION_FAILED"
    asyncio.run(check())


@pytest.mark.parametrize("url", ["http://evil.test/api", "http://127.0.0.1:8080/other?token=" + "a"*32,
    "http://127.0.0.1:8080/api/v1/script-tasks/x/events?token=" + "a"*32,
    "http://127.0.0.1:8080/api/v1/script-tasks/x/events?token=" + "a"*32 + "&redirect=evil"])
def test_callback_destination_is_not_client_controlled(prepared_request, url):
    async def check():
        prepared_request.prepared.submission.callbackUrl = url
        with pytest.raises(HTTPException) as error:
            await ScriptRunService().submit(prepared_request)
        assert error.value.status_code == 422
    asyncio.run(check())


def test_http_routes_reject_bad_inputs_and_return202_only_for_qualified_acceptance(prepared_request):
    async def check():
        async def notify(*_): return True
        service = ScriptRunService(notify=notify)
        app = create_script_app(service)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/script-runs", json=prepared_request.model_dump(mode="json"))
            assert response.status_code == 202
            await service.drain()
            run_id = response.json()["runId"]
            assert (await client.get("/v1/script-runs/" + run_id)).status_code == 403
            headers = {"X-AgentCut-Run-Token": "a" * 32}
            response = await client.get("/v1/script-runs/" + run_id, headers=headers)
            assert response.json()["executionStatus"] == "SUCCESS"
            assert (await client.get("/v1/script-runs/missing")).status_code == 404
            assert (await client.post("/v1/script-runs/" + run_id + "/callback", headers=headers)).json()["callbackDelivered"]
            assert (await client.post("/v1/script-runs", content='{"prepared":{},"prepared":{}}')).status_code == 422
            assert (await client.post("/v1/script-runs", content="```json\n{}\n```")).status_code == 422
            assert (await client.post("/v1/script-runs", content=b"x" * 5_000_001)).status_code == 413
            assert (await client.post("/v1/script-runs", json={})).status_code == 422
    asyncio.run(check())
