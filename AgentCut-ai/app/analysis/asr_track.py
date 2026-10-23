"""ASR adapter protocol and immutable chunk results; no model/client imports."""

import asyncio
import time
from typing import Annotated, Literal, Protocol

from pydantic import Field, StrictBool, model_validator

from app.analysis.audio_track import AudioChunk, AudioPlan, coverage_ms, overlap_ranges
from app.analysis.source_index import stable_id
from app.analysis.window_planner import PlanningResult
from app.schemas.analysis_evidence_v1 import TranscriptSegmentV1
from app.schemas.script_contracts_v1 import Contract, Hash, Id, Integer, Provenance, Range, Text


ASR_TRACK_VERSION = "asr-track-0.1"


class AsrError(Contract):
    code: Literal["ADAPTER_ERROR", "TIMEOUT", "EMPTY_RESPONSE", "MISSING_RESULT", "INVALID_RESPONSE"]
    message: Text
    retryable: StrictBool


class AsrChunkResult(Contract):
    chunkId: Id
    assetHash: Hash
    status: Literal["SUCCESS", "NO_SPEECH", "FAILED"]
    text: str | None
    source: Provenance
    error: AsrError | None

    @model_validator(mode="after")
    def validate_result(self) -> "AsrChunkResult":
        if self.status == "SUCCESS":
            if self.source.mode not in {"REAL", "SIMULATED"} or not self.text or not self.text.strip() or self.error is not None:
                raise ValueError("successful ASR requires original nonempty text and explicit source")
        elif self.status == "NO_SPEECH":
            if self.source.mode not in {"NO_SPEECH", "SIMULATED"} or self.text != "" or self.error is not None:
                raise ValueError("NO_SPEECH requires an explicit recognizer declaration, empty text and no error")
            if not self.source.reason:
                raise ValueError("NO_SPEECH must retain the recognizer reason")
        elif self.source.mode != "UNAVAILABLE" or self.text is not None or self.error is None:
            raise ValueError("failed ASR must retain error and cannot invent text")
        return self


def failed_chunk(chunk: AudioChunk, code: str, message: str, *, retryable: bool = False) -> AsrChunkResult:
    return AsrChunkResult(chunkId=chunk.chunkId, assetHash=chunk.assetHash, status="FAILED", text=None,
        source=Provenance(mode="UNAVAILABLE", provider=None, model=None, reason=message),
        error=AsrError(code=code, message=message, retryable=retryable))


class AsrAdapter(Protocol):
    async def transcribe(self, chunk: AudioChunk) -> AsrChunkResult:
        """Recognize requestRange; return ID-bound original block text.

        Implementations must be asynchronous and honor cancellation/timeouts.
        Timing is derived by the caller, never invented by the recognizer.
        """
        ...


class AsrExecutionPolicy(Contract):
    concurrency: Annotated[int, Field(strict=True, ge=1, le=2)] = 2
    timeoutSeconds: float = Field(default=30.0, gt=0, le=120, allow_inf_nan=False)


async def run_asr(plan: AudioPlan, adapter: AsrAdapter,
                  policy: AsrExecutionPolicy | None = None, *,
                  existing_results: list[AsrChunkResult] | None = None) -> list[AsrChunkResult]:
    """At most two in-flight chunks, with explicit same-plan result reuse.

    Supplying prior results requests only failed/missing chunks on this run.
    There are no within-run retries or shared mutable provenance.
    """
    plan = AudioPlan.model_validate(plan.model_dump())
    policy = AsrExecutionPolicy.model_validate(policy.model_dump()) if policy else AsrExecutionPolicy()
    existing = _canonical_results(plan, [AsrChunkResult.model_validate(r.model_dump())
                                        for r in (existing_results or [])])
    results = {r.chunkId: r for r in existing if r.status != "FAILED"}
    queue = asyncio.Queue()
    for chunk in plan.chunks:
        if chunk.chunkId not in results:
            queue.put_nowait(chunk)

    async def worker():
        while not queue.empty():
            chunk = queue.get_nowait()
            started = time.monotonic()
            try:
                value = await asyncio.wait_for(adapter.transcribe(chunk.model_copy(deep=True)), policy.timeoutSeconds)
                # A provider that suppresses cancellation must not publish a late result.
                if time.monotonic() - started > policy.timeoutSeconds:
                    raise TimeoutError()
                result = AsrChunkResult.model_validate(value.model_dump())
                if result.chunkId != chunk.chunkId or result.assetHash != chunk.assetHash:
                    raise ValueError("ASR response identity differs from its chunk")
            except TimeoutError:
                result = failed_chunk(chunk, "TIMEOUT", "ASR deadline exceeded; remote cancellation is not confirmed", retryable=True)
            except (AttributeError, TypeError, ValueError):
                result = failed_chunk(chunk, "INVALID_RESPONSE", "ASR adapter returned an invalid or misbound response")
            except Exception:
                result = failed_chunk(chunk, "ADAPTER_ERROR", "ASR adapter failed; other chunk results are retained")
            results[chunk.chunkId] = result
            queue.task_done()

    await asyncio.gather(*(worker() for _ in range(min(policy.concurrency, queue.qsize()))))
    return [results[c.chunkId] for c in plan.chunks]


class WindowAudioLink(Contract):
    windowId: Id
    transcriptRefs: list[Id]
    failedChunkRefs: list[Id]
    observedMs: Integer
    speechMs: Integer
    transcribedSpeechMs: Integer
    missingSpeechMs: Integer
    unknownMs: Integer
    status: Literal["COMPLETE", "NO_SPEECH", "PARTIAL", "UNAVAILABLE"]


class TextJoin(Contract):
    transcriptId: Id
    overlapWith: Id | None
    removedPrefix: str
    displayText: str


class AsrTrack(Contract):
    trackSchemaVersion: Literal[ASR_TRACK_VERSION] = ASR_TRACK_VERSION
    trackId: Id
    audioPlan: AudioPlan
    visualPlan: PlanningResult
    chunkResults: list[AsrChunkResult]
    transcripts: list[TranscriptSegmentV1]
    windowLinks: list[WindowAudioLink]
    textJoins: list[TextJoin]
    displayText: str
    transcribedSpeechMs: Integer
    missingSpeechMs: Integer
    status: Literal["COMPLETE", "NO_SPEECH", "PARTIAL", "UNAVAILABLE"]
    reviewReasons: list[Text]

    @model_validator(mode="after")
    def validate_track(self) -> "AsrTrack":
        expected = _track_fields(self.audioPlan, self.visualPlan, self.chunkResults)
        if any(getattr(self, key) != value for key, value in expected.items()):
            raise ValueError("ASR transcripts, coverage, identity or window references were changed")
        return self


def _canonical_results(plan: AudioPlan, results: list[AsrChunkResult]) -> list[AsrChunkResult]:
    chunks = {c.chunkId: c for c in plan.chunks}
    found = {}
    for result in results:
        if result.chunkId not in chunks or result.chunkId in found or result.assetHash != plan.vad.assetRef.assetHash:
            raise ValueError("unknown/duplicate ASR chunk or foreign assetHash")
        found[result.chunkId] = result
    return [found.get(c.chunkId) or failed_chunk(c, "MISSING_RESULT", "No ASR result was supplied for this chunk")
            for c in plan.chunks]


def _text_joins(transcripts: list[TranscriptSegmentV1]) -> list[TextJoin]:
    joins = []
    previous = None
    for current in transcripts:
        removed = ""
        if (previous and current.startMs < previous.endMs and previous.source.mode == current.source.mode
                and previous.source.provider == current.source.provider and previous.source.model == current.source.model):
            # Display-only exact suffix/prefix dedup. Original records and block
            # times remain intact; this does not create word-level alignment.
            for count in range(min(len(previous.text), len(current.text)), 7, -1):
                if previous.text[-count:] == current.text[:count]:
                    removed = current.text[:count]
                    break
        joins.append(TextJoin(transcriptId=current.transcriptId,
            overlapWith=previous.transcriptId if removed else None, removedPrefix=removed,
            displayText=current.text[len(removed):]))
        previous = current
    return joins


def _track_fields(audio: AudioPlan, visual: PlanningResult, supplied: list[AsrChunkResult]) -> dict:
    if audio.vad.assetRef != visual.sourceIndex.assetRef:
        raise ValueError("audio and visual plans must bind the same source asset")
    results = _canonical_results(audio, supplied)
    if results != supplied:
        raise ValueError("persisted chunk results must be complete and in source order")
    transcripts, real_requests = [], []
    review = []
    if not audio.vad.reliable or audio.unknownRanges:
        review.append("VAD_INCOMPLETE_SIMULATED_OR_UNRELIABLE")
    for chunk, result in zip(audio.chunks, results):
        if result.status == "SUCCESS":
            r = chunk.requestRange
            transcripts.append(TranscriptSegmentV1(
                transcriptId=stable_id("asr", {"chunkId": chunk.chunkId, "result": result.model_dump()}),
                startMs=r.startMs, endMs=r.endMs, text=result.text, timingQuality="COARSE_BLOCK",
                source=result.source.model_dump(),
            ))
            if result.source.mode == "REAL":
                real_requests.append(r)
        if result.status == "FAILED" and "ASR_CHUNKS_MISSING_OR_FAILED" not in review:
            review.append("ASR_CHUNKS_MISSING_OR_FAILED")
        if result.source.mode == "SIMULATED" and "SIMULATED_ASR" not in review:
            review.append("SIMULATED_ASR")
        if result.status == "NO_SPEECH" and "VAD_ASR_DISAGREEMENT" not in review:
            # Speech-positive VAD with empty recognition is not proof of silence.
            review.append("VAD_ASR_DISAGREEMENT")
    resolved = overlap_ranges(audio.vad.speechRanges, real_requests)
    transcribed_ms = coverage_ms(resolved)
    missing_ms = audio.speechMs - transcribed_ms
    links = []
    for window in visual.windows:
        primary = [Range(startMs=window.startMs, endMs=window.endMs)]
        observed = coverage_ms(overlap_ranges(primary, audio.vad.analyzedRanges))
        speech = coverage_ms(overlap_ranges(primary, audio.vad.speechRanges))
        transcribed = coverage_ms(overlap_ranges(primary, resolved))
        refs = [t.transcriptId for t in transcripts if t.startMs < window.endMs and t.endMs > window.startMs]
        failed = [c.chunkId for c, r in zip(audio.chunks, results) if r.status != "SUCCESS"
                  and c.requestRange.startMs < window.endMs and c.requestRange.endMs > window.startMs]
        unknown = window.endMs - window.startMs - observed
        simulated = any(t.source.mode == "SIMULATED" for t in transcripts if t.transcriptId in refs)
        if not observed:
            status = "UNAVAILABLE"
        elif unknown or not audio.vad.reliable or failed or simulated or speech > transcribed:
            status = "PARTIAL"
        else:
            status = "COMPLETE" if speech else "NO_SPEECH"
        links.append(WindowAudioLink(windowId=window.windowId, transcriptRefs=refs, failedChunkRefs=failed,
            observedMs=observed, speechMs=speech, transcribedSpeechMs=transcribed,
            missingSpeechMs=speech - transcribed, unknownMs=unknown, status=status))
    joins = _text_joins(transcripts)
    if audio.status == "NO_SPEECH":
        status = "NO_SPEECH"
    elif not audio.observedMs:
        status = "UNAVAILABLE"
    else:
        status = "PARTIAL" if review or missing_ms else "COMPLETE"
    return {"trackId": stable_id("asr_track", {"version": ASR_TRACK_VERSION, "audioPlanId": audio.planId,
        "visualWindows": [w.windowId for w in visual.windows], "results": [r.model_dump() for r in results]}),
        "transcripts": transcripts, "windowLinks": links, "textJoins": joins,
        "displayText": "\n".join(j.displayText for j in joins if j.displayText),
        "transcribedSpeechMs": transcribed_ms, "missingSpeechMs": missing_ms,
        "status": status, "reviewReasons": review}


def assemble_asr_track(audio: AudioPlan, visual: PlanningResult, results: list[AsrChunkResult]) -> AsrTrack:
    audio = AudioPlan.model_validate(audio.model_dump())
    visual = PlanningResult.model_validate(visual.model_dump())
    results = _canonical_results(audio, [AsrChunkResult.model_validate(r.model_dump()) for r in results])
    return AsrTrack(audioPlan=audio, visualPlan=visual, chunkResults=results, **_track_fields(audio, visual, results))
