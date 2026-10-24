"""Bounded, process-local online execution of prepared B2 inputs.

No media download, configuration import or model construction occurs here.
The default engine uses the rule director and explicitly unavailable semantic QA.
"""

import asyncio
import hashlib
import hmac
import json
import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import model_validator

from app.agents.model_json import model_json_object
from app.analysis.offline_id_director import OfflineDirectorInput, run_offline
from app.analysis.offline_script_review import ScriptReviewArtifact, review_offline
from app.schemas.script_contracts_v1 import (
    Contract, ScriptContractBundleV1, TaskError, TaskEventV1, require, validate_submission,
)

MAX_BODY_BYTES = 5_000_000
MAX_RESULT_BYTES = 20_000_000


class ScriptRunRequest(Contract):
    prepared: OfflineDirectorInput

    @model_validator(mode="after")
    def context(self):
        validate_submission(self.prepared.submission)
        require(self.prepared.sourceIndex.assetRef == self.prepared.submission.assetRef
                == self.prepared.evidence.assetRef, "prepared asset binding mismatch")
        return self


def execute_prepared(prepared, progress):
    progress("INDEXING", 10)
    initial = run_offline(prepared)
    progress("CHECKING", 70)
    return review_offline(initial)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ScriptRunService:
    def __init__(self, *, callback_base="http://127.0.0.1:8080", max_active=2, max_retained=64,
                 engine=execute_prepared, notify=None):
        require(1 <= max_active <= max_retained <= 256, "invalid capacity")
        self.callback_base = callback_base.rstrip("/")
        self.max_active, self.max_retained = max_active, max_retained
        self.engine, self.notify = engine, notify or self._post
        self.runs, self.tasks = {}, set()
        self.active = 0
        self.lock = threading.RLock()

    def _callback_allowed(self, submission):
        base, actual = urlsplit(self.callback_base), urlsplit(submission.callbackUrl)
        return (actual.scheme in {"http", "https"} and actual.scheme == base.scheme
                and actual.netloc == base.netloc and not actual.username and not actual.password
                and not actual.fragment and actual.path == base.path.rstrip("/")
                + f"/api/v1/script-tasks/{submission.taskId}/events"
                and re.fullmatch(r"token=[0-9a-f]{32}", actual.query) is not None)

    async def submit(self, request):
        # Copy before retention: callers cannot mutate a running input snapshot.
        request = ScriptRunRequest.model_validate(request.model_dump())
        submission = request.prepared.submission
        if not self._callback_allowed(submission):
            raise HTTPException(422, "callback destination is not configured")
        encoded = request.model_dump_json()
        if len(encoded.encode()) > MAX_BODY_BYTES:
            raise HTTPException(413, "prepared input exceeds capacity")
        fingerprint = hashlib.sha256(json.dumps(json.loads(encoded), sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            old = self.runs.get(submission.runId)
            if old is not None:
                if old["fingerprint"] != fingerprint:
                    raise HTTPException(409, "runId already binds another snapshot")
                return dict(old["acceptance"])
            if self.active >= self.max_active or len(self.runs) >= self.max_retained:
                raise HTTPException(503, "script run capacity exhausted")
            acceptance = dict(protocolVersion="1.0", runId=submission.runId, taskId=submission.taskId,
                inputHash=submission.inputHash, jobId=submission.runId, status="accepted")
            self.runs[submission.runId] = dict(fingerprint=fingerprint, request=request,
                acceptance=acceptance, status="PENDING", events=[], bundle=None, callbackDelivered=False)
            self.active += 1
            task = asyncio.create_task(self._run(submission.runId))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        return dict(acceptance)

    def _event(self, run, phase, progress, *, bundle=None, error=None, partial=False):
        s = run["request"].prepared.submission
        terminal = bundle is not None or error is not None
        sequence = len(run["events"]) + 1
        event = TaskEventV1(protocolVersion="1.0", event="COMPLETED" if terminal else "PROGRESS",
            eventId=f"{s.runId}_{sequence}", requestId=s.input.requestId, taskId=s.taskId,
            projectId=s.projectId, assetId=s.assetRef.assetId, assetHash=s.assetRef.assetHash,
            runId=s.runId, attempt=s.attempt, inputHash=s.inputHash, sequence=sequence,
            heartbeatAt=now(), phase=phase, progress=progress,
            executionStatus="FAILED" if error else "SUCCESS" if terminal else "RUNNING",
            analysisOutcome=("PARTIAL" if partial else "COMPLETE") if bundle else "NONE",
            reviewStatus=bundle.script.reviewStatus if bundle else "NOT_AVAILABLE",
            resultRefs=(dict(analysis=bundle.materialIndex.analysisRef.model_dump(),
                materialIndex=dict(artifactId=bundle.materialIndex.indexId,
                    revision=bundle.materialIndex.indexVersion, contentHash=bundle.materialIndex.indexHash),
                script=dict(artifactId=bundle.script.scriptId, revision=bundle.script.revision,
                    contentHash=bundle.script.scriptHash)) if bundle else None), error=error)
        history = [*run["events"], event.model_dump(mode="json")]
        values = (bundle.model_dump() if bundle else dict(materialIndex=None, decision=None, script=None,
            submission=s.model_dump(), events=[]))
        values["events"] = history
        checked = ScriptContractBundleV1.model_validate(values)
        if len(checked.model_dump_json().encode()) > MAX_RESULT_BYTES:
            raise ValueError("result exceeds online capacity")
        # Terminal and artifacts become visible together only after full validation.
        run["events"] = history
        if terminal:
            run["bundle"] = checked.model_dump(mode="json")
            run["status"] = event.executionStatus
        else:
            run["status"] = "RUNNING"
        return dict(event=event.model_dump(mode="json"), bundle=run["bundle"] if terminal else None)

    async def _deliver(self, run_id, envelope):
        with self.lock:
            url = self.runs[run_id]["request"].prepared.submission.callbackUrl
        try:
            delivered = await self.notify(url, envelope)
        except Exception:
            delivered = False
        if envelope["event"]["event"] == "COMPLETED":
            with self.lock:
                self.runs[run_id]["callbackDelivered"] = bool(delivered)

    async def _post(self, url, payload):
        # No redirects: only the configured callback origin receives the token/result.
        parsed = urlsplit(url)
        token = parse_qs(parsed.query)["token"][0]
        destination = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        async with asyncio.timeout(10):
            async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
                response = await client.post(destination, json=payload, headers={"X-AgentCut-Run-Token": token})
                return 200 <= response.status_code < 300

    async def _run(self, run_id):
        loop = asyncio.get_running_loop()
        deliveries = []

        def progress(phase, percent):
            with self.lock:
                run = self.runs[run_id]
                envelope = self._event(run, phase, percent)
            # The engine thread never directly mutates asyncio objects.
            future = asyncio.run_coroutine_threadsafe(self._deliver(run_id, envelope), loop)
            deliveries.append(future)

        try:
            with self.lock:
                request = self.runs[run_id]["request"].model_copy(deep=True)
            artifact = await asyncio.to_thread(self.engine, request.prepared.model_copy(deep=True), progress)
            artifact = ScriptReviewArtifact.model_validate(artifact.model_dump())
            require(artifact.initialArtifact.submission == request.prepared.submission,
                    "engine changed submission")
            built = artifact.initialArtifact.materialBuild
            require(built.sourceIndex == request.prepared.sourceIndex and built.evidence == request.prepared.evidence
                    and built.indexVersion == request.prepared.indexVersion, "engine changed evidence snapshot")
            if artifact.review.script is None:
                error = artifact.initialArtifact.run.error or TaskError(code="NO_CANDIDATE",
                    message="No qualified whole-unit selection was found", retryable=False)
                bundle = None
            else:
                bundle, error = artifact.contract_bundle(), None
            with self.lock:
                envelope = self._event(self.runs[run_id], "COMPLETED" if bundle else "FAILED",
                    100 if bundle else (self.runs[run_id]["events"][-1]["progress"]
                        if self.runs[run_id]["events"] else 0), bundle=bundle, error=error,
                    partial=built.status == "PARTIAL")
        except Exception:
            with self.lock:
                run = self.runs[run_id]
                percent = run["events"][-1]["progress"] if run["events"] else 0
                envelope = self._event(run, "FAILED", percent, error=TaskError(code="VALIDATION_FAILED",
                    message="Prepared script execution failed validation", retryable=False))
        finally:
            with self.lock:
                self.active -= 1
        # Failed/lost progress does not prevent terminal delivery. Waiting here bounds
        # callback work per run and avoids dropping tasks when a test/app shuts down.
        for delivery in deliveries:
            await asyncio.wrap_future(delivery)
        await self._deliver(run_id, envelope)

    def status(self, run_id):
        with self.lock:
            run = self.runs.get(run_id)
            if run is None:
                raise HTTPException(404, "run not retained in this process")
            return json.loads(json.dumps(dict(**run["acceptance"], executionStatus=run["status"],
                events=run["events"], bundle=run["bundle"], callbackDelivered=run["callbackDelivered"])))

    async def redeliver(self, run_id):
        status = self.status(run_id)
        if status["executionStatus"] not in {"SUCCESS", "FAILED"}:
            raise HTTPException(409, "run is not terminal")
        await self._deliver(run_id, dict(event=status["events"][-1], bundle=status["bundle"]))
        return {"callbackDelivered": self.status(run_id)["callbackDelivered"]}

    async def drain(self):
        if self.tasks:
            await asyncio.gather(*list(self.tasks))

    def authorize(self, run_id, token):
        with self.lock:
            run = self.runs.get(run_id)
            if run is None:
                raise HTTPException(404, "run not retained in this process")
            expected = parse_qs(urlsplit(run["request"].prepared.submission.callbackUrl).query)["token"][0]
            if token is None or not hmac.compare_digest(token, expected):
                raise HTTPException(403, "invalid run token")


def script_router(service):
    router = APIRouter(prefix="/v1/script-runs", tags=["script-runs"])

    @router.post("", status_code=202)
    async def submit(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                raise HTTPException(413, "prepared input exceeds capacity")
        try:
            # Duplicate object keys are rejected before typed validation.
            require(body.lstrip().startswith(b"{"), "JSON object required")
            values = model_json_object(body.decode("utf-8"))
            parsed = ScriptRunRequest.model_validate(values)
        except (ValueError, UnicodeError, TypeError, RecursionError):
            raise HTTPException(422, "invalid prepared script request") from None
        return await service.submit(parsed)

    @router.get("/{run_id}")
    async def status(run_id: str, request: Request):
        service.authorize(run_id, request.headers.get("X-AgentCut-Run-Token"))
        return service.status(run_id)

    @router.post("/{run_id}/callback")
    async def callback(run_id: str, request: Request):
        service.authorize(run_id, request.headers.get("X-AgentCut-Run-Token"))
        return await service.redeliver(run_id)

    return router


def create_script_app(service=None):
    """Isolated app for local integration, with no legacy config/model imports."""
    service = service or ScriptRunService(callback_base=os.environ.get("AGENTCUT_SCRIPT_CALLBACK_BASE", "http://127.0.0.1:8080"))

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await service.drain()

    app = FastAPI(title="AgentCut prepared script runs", lifespan=lifespan)
    app.include_router(script_router(service))
    return app
