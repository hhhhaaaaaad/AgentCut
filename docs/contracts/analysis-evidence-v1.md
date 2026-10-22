# AnalysisEvidence 1.0 contract

Status: B1 analysis-evidence contract. This is an additive contract. The running
analysis service still emits the legacy `AnalysisReport`, and `Plan 1.0` remains
the execution format. No implicit conversion between these documents is valid.

## Authority and fixtures

`analysis-evidence-v1.schema.json` is the structural JSON contract. It is
generated from `AgentCut-ai/app/schemas/analysis_evidence_v1.py`; a test checks
that the checked-in schema has not drifted. The JSON fixtures are fictional
examples, not records of model calls:

- `analysis-evidence-v1.valid.json`: complete evidence and a transcript crossing
  two adjacent analysis windows.
- `analysis-evidence-v1.needs-review.json`: one VLM window fails while the ASR
  evidence and successful window remain available.
- `analysis-evidence-v1.no-speech.json`: ASR explicitly reports no speech; empty
  transcripts are a complete audio result, with no invented transcript.
- `analysis-evidence-v1.mixed.json`: full time coverage includes one simulated
  frame description, so the outcome is `COMPLETE` but review is required.
- `analysis-evidence-v1.invalid-extra-time.json`: a model adds a free
  `sourceRange` to a frame observation; strict readers must reject it.

## Time, identity, and evidence

- All times are integer milliseconds in the original asset's global timebase.
  Every range is half open `[startMs, endMs)`. Display rounding must never be
  written back into this contract.
- `assetHash` and `configVersion` bind evidence to its source and settings.
  A changed asset or settings revision requires a new analysis document.
- Window primary ranges start at zero, are contiguous, and end at
  `durationMs`. Context ranges may overlap, but are not counted twice.
- `windowId`, `sceneId`, `frameId`, and `transcriptId` are stable string IDs.
  An array position is never a reference. A frame belongs to one selected
  window; an ASR segment may be referenced by multiple windows without copying
  or rewriting its original time range.
- `FrameObservation.timestampMs` must lie inside its window context. A window
  may refer only to its selected frame observations and to transcripts that
  overlap its primary range. Findings must point to evidence overlapping their
  stated range. Unknown, duplicate, and foreign references are rejected.
- `WindowCoverage.asrOverlapMs` is the union of the referenced transcript
  intervals clipped to that window's primary range. `visualComplete` requires
  at least one selected frame and a successful observation for every selected
  frame. `audioComplete` is an explicit result of ASR coverage review; a complete
  window without a transcript must record `provenance.asr.mode=NO_SPEECH`.
- `AnalysisProfile.requestedType` is never overridden when it is not `AUTO`.
  The system may set `effectiveType` only for `AUTO`; technical pace and budget
  fields still record any automatic adjustment.

## Outcome mapping

`executionStatus`, `analysisOutcome`, and `reviewStatus` describe separate
facts. An `AnalysisEvidenceV1` document is a completed result and therefore has
`executionStatus=SUCCESS`. A failed task may have diagnostic fragments but no
qualified evidence document. A complete result can still need semantic review.
Partial evidence always requires review; simulated, mixed, or unavailable
sources cannot be marked `READY`.

| New result | Existing Java task status while the old API is in use |
|---|---|
| `SUCCESS` + `COMPLETE` + `READY` | `SUCCESS` |
| `SUCCESS` + `COMPLETE/PARTIAL` + `NEEDS_REVIEW` | `NEEDS_REVIEW` |
| No qualified result and task failure | `FAILED` |

This mapping is for compatibility only. B1 does not change the existing task
endpoint or the current `Plan 1.0` parser. Applying this contract to live tasks
requires a separate migration with an explicit version discriminator.

## Scope boundary

This slice freezes the evidence shape and cross-language fixtures. Window
planning, VLM/ASR temporal fusion, rendering, and persistence changes remain
separate work. MaterialIndex, DirectorDecision, EditingScript and task protocol
contracts are defined in [script-task-v1.md](script-task-v1.md); they remain
separate from the running legacy endpoints.
