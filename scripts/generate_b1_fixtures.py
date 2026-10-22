"""Fictional B1 conformance samples, never records of model calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZERO = "sha256:" + "0" * 64


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def seal(bundle):
    request = bundle["submission"]
    request["inputHash"] = digest({
        "projectId": request["projectId"], "assetRef": request["assetRef"], "configVersion": request["configVersion"],
        "input": {k: v for k, v in request["input"].items() if k != "requestId"},
    })
    index, decision, script = [bundle[key] for key in ("materialIndex", "decision", "script")]
    if index is not None:
        index["indexHash"] = digest({k: v for k, v in index.items() if k != "indexHash"})
    for value in (decision, script):
        if value is not None:
            value["inputHash"] = request["inputHash"]
            if index is not None:
                value["indexRef"]["indexHash"] = index["indexHash"]
    if script is not None:
        script["scriptHash"] = digest({k: v for k, v in script.items() if k not in
            ("scriptHash", "validationReport", "quality", "reviewStatus")})
        script["validationReport"]["candidateHash"] = script["scriptHash"]
        if script["quality"] is not None:
            script["quality"]["candidateHash"] = script["scriptHash"]
    for event in bundle["events"]:
        event["inputHash"] = request["inputHash"]
        if event["resultRefs"] is not None and index is not None and script is not None:
            event["resultRefs"] = {
                "analysis": deepcopy(index["analysisRef"]),
                "materialIndex": {"artifactId": index["indexId"], "revision": index["indexVersion"], "contentHash": index["indexHash"]},
                "script": {"artifactId": script["scriptId"], "revision": script["revision"], "contentHash": script["scriptHash"]},
            }
    return bundle


def base_bundle():
    asset = {"assetId": "asset_fixture", "assetHash": "sha256:" + "a" * 64, "durationMs": 12000, "displayName": "虚构采访.mp4"}
    real = {"mode": "REAL", "provider": "fixture", "model": "fixture-model", "reason": None}
    scenes = [{"sceneId": "scene_1", "sourceRange": {"startMs": 0, "endMs": 6000}},
              {"sceneId": "scene_2", "sourceRange": {"startMs": 6000, "endMs": 12000}}]
    observations = [{"frameId": f"frame_{i}", "sceneId": "scene_1" if i == 1 else "scene_2", "timestampMs": time,
                     "description": text, "source": deepcopy(real)} for i, time, text in
                    [(1, 1000, "受访者介绍主题。"), (2, 6500, "受访者解释观点。"), (3, 9000, "受访者总结。")]]
    units = []
    for i, text in enumerate(["不是越短越好。", "而是让观众更容易看懂。", "保留必要的上下文。"], 1):
        units.append({"unitId": f"unit_{i}", "kind": "SPEECH", "sourceRange": {"startMs": (i - 1) * 4000, "endMs": i * 4000},
                      "originalText": text, "timingQuality": "SENTENCE", "transcriptRefs": [f"asr_{i}"],
                      "sceneRefs": ["scene_1"] if i == 1 else ["scene_1", "scene_2"] if i == 2 else ["scene_2"],
                      "frameRefs": [f"frame_{i}"], "asrSource": deepcopy(real),
                      "dependencies": [{"unitId": "unit_1", "kind": "NEGATION", "level": "REQUIRED"}] if i == 2 else []})
    index = {"indexSchemaVersion": "1.0", "indexId": "index_fixture", "indexVersion": 3, "indexHash": ZERO,
             "assetRef": deepcopy(asset), "analysisRef": {"artifactId": "analysis_fixture", "revision": 2, "contentHash": "sha256:" + "b" * 64},
             "scenes": scenes, "observations": observations, "units": units}
    index["transcripts"] = [{"transcriptId": f"asr_{i}", "sourceRange": deepcopy(unit["sourceRange"]), "text": unit["originalText"],
                            "timingQuality": "SENTENCE", "source": deepcopy(real)} for i, unit in enumerate(units, 1)]
    index_ref = {"indexId": index["indexId"], "indexVersion": 3, "indexHash": ZERO}
    target = {"mode": "TOPIC_EXTRACT", "topic": "避免误删上下文", "maxDurationMs": 15000, "desiredDurationMs": 12000,
              "aspectRatio": "9:16", "subtitleRequested": True, "style": "原声采访", "contentType": "TUTORIAL_INTERVIEW",
              "editPolicy": "ORIGINAL_ORDER_ORIGINAL_SPEED_HARD_CUT"}
    proposal = {"suggestionId": "suggestion_1", "kind": "TITLE", "text": "建议标题：减少理解成本"}
    decision_rows = [{"rowId": "row_1", "sourceUnitRefs": ["unit_1", "unit_2"], "narrativeRole": "EXPLANATION",
                      "selectionReason": "完整保留不是与而是的转折。", "packagingSuggestions": [proposal]},
                     {"rowId": "row_2", "sourceUnitRefs": ["unit_3"], "narrativeRole": "CONCLUSION",
                      "selectionReason": "保留总结。", "packagingSuggestions": []}]
    decision = {"decisionSchemaVersion": "1.0", "decisionId": "decision_fixture", "indexRef": deepcopy(index_ref),
                "inputHash": ZERO, "rows": decision_rows}
    script_rows, captions, actions = [], [], []
    for i, chosen in enumerate(decision_rows, 1):
        row_units = [unit for unit in units if unit["unitId"] in chosen["sourceUnitRefs"]]
        script_rows.append({"rowId": chosen["rowId"], "shotNo": i, "sourceUnitRefs": deepcopy(chosen["sourceUnitRefs"]),
            "sourceParts": [{"unitId": unit["unitId"], "sourceRange": deepcopy(unit["sourceRange"])} for unit in row_units],
            "outputRange": {"startMs": 0 if i == 1 else 8000, "endMs": 8000 if i == 1 else 12000},
            "spokenQuotes": [{"unitId": unit["unitId"], "text": unit["originalText"]} for unit in row_units],
            "visualEvidence": [{"frameId": frame["frameId"], "observedDescription": frame["description"]}
                               for frame in observations if frame["frameId"] in [r for u in row_units for r in u["frameRefs"]]],
            "narrativeRole": chosen["narrativeRole"], "selectionReason": chosen["selectionReason"],
            "dependencyRefs": ["unit_1"] if i == 1 else [], "riskRefs": [], "treatmentNote": "", "audioTreatment": "ORIGINAL", "cutNotes": ""})
        actions.append({"actionId": f"audio_{i}", "type": "ORIGINAL_AUDIO", "rowId": chosen["rowId"], "cueId": None})
        for unit in row_units:
            cue_id = "cue_" + unit["unitId"]
            captions.append({"cueId": cue_id, "rowId": chosen["rowId"], "unitId": unit["unitId"], "text": unit["originalText"],
                             "outputRange": deepcopy(unit["sourceRange"]), "timingQuality": "SENTENCE"})
            actions.append({"actionId": "action_" + cue_id, "type": "CAPTION", "rowId": chosen["rowId"], "cueId": cue_id})
    script = {"scriptSchemaVersion": "1.0", "scriptId": "script_fixture", "revision": 1, "projectId": "project_fixture",
              "generationTaskId": "task_fixture", "assetRef": deepcopy(asset), "indexRef": deepcopy(index_ref), "inputHash": ZERO,
              "target": deepcopy(target), "title": "上下文比秒数更重要", "rows": script_rows, "estimatedDurationMs": 12000,
              "captionCues": captions, "executableActions": actions, "packagingSuggestions": [{**proposal, "rowId": "row_1", "status": "PROPOSED"}],
              "manualNotes": "", "riskItems": [], "scriptHash": ZERO,
              "validationReport": {"validationVersion": "b1-1.0", "candidateHash": ZERO, "hardPassed": True, "issueRefs": []},
              "quality": {"candidateHash": ZERO, "passed": True, "overallScore": 0.9, "issueRefs": []}, "reviewStatus": "READY"}
    submission = {"protocolVersion": "1.0", "messageType": "ANALYZE_REQUEST", "taskId": "task_fixture", "projectId": "project_fixture",
                  "runId": "run_fixture", "attempt": 1, "inputHash": ZERO, "configVersion": "config-1",
                  "input": {"inputSchemaVersion": "1.0", "requestId": "request_fixture", "assetId": "asset_fixture", "taskName": "虚构契约验收",
                            "target": deepcopy(target)}, "assetRef": deepcopy(asset), "mediaObjectKey": "projects/fixture/source.mp4",
                  "callbackUrl": "http://127.0.0.1:8080/api/v1/tasks/fixture/events"}
    events = []
    for i, progress, phase in [(1, 12, "PROBING"), (2, 70, "PLANNING"), (3, 100, "COMPLETED")]:
        terminal = i == 3
        events.append({"protocolVersion": "1.0", "event": "COMPLETED" if terminal else "PROGRESS", "eventId": f"event_{i}",
            "requestId": "request_fixture", "taskId": "task_fixture", "projectId": "project_fixture",
            "assetId": asset["assetId"], "assetHash": asset["assetHash"], "runId": "run_fixture", "attempt": 1,
            "inputHash": ZERO, "sequence": i, "heartbeatAt": f"2026-01-01T00:00:0{i}Z", "phase": phase, "progress": progress,
            "executionStatus": "SUCCESS" if terminal else "RUNNING", "analysisOutcome": "COMPLETE" if terminal else "NONE",
            "reviewStatus": "READY" if terminal else "NOT_AVAILABLE", "resultRefs": {} if terminal else None, "error": None})
    return seal({"materialIndex": index, "decision": decision, "script": script, "submission": submission, "events": events})


def patches(before, after, path=None):
    path = path or []
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(before.keys() - after.keys()):
            result.append({"op": "remove", "path": [*path, key]})
        for key, value in after.items():
            if key not in before:
                result.append({"op": "set", "path": [*path, key], "value": value})
            else:
                result.extend(patches(before[key], value, [*path, key]))
        return result
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [patch for i, (a, b) in enumerate(zip(before, after)) for patch in patches(a, b, [*path, i])]
    same = before == after and isinstance(before, bool) == isinstance(after, bool)
    return [] if same else [{"op": "set", "path": path, "value": after}]


def risk(bundle, code, row_id=None, unit_id=None, level="REVIEW"):
    script = bundle["script"]
    risk_id = "risk_" + str(len(script["riskItems"]) + 1)
    script["riskItems"].append({"riskId": risk_id, "code": code, "level": level,
        "rowRefs": [row_id] if row_id else [], "unitRefs": [unit_id] if unit_id else [], "message": "Fictional " + code})
    script["validationReport"]["issueRefs"].append(risk_id)
    if row_id:
        next(row for row in script["rows"] if row["rowId"] == row_id)["riskRefs"].append(risk_id)
    script["reviewStatus"] = "NEEDS_REVIEW"
    bundle["events"][-1]["reviewStatus"] = "NEEDS_REVIEW"
    return risk_id


def remove_caption(bundle, unit_id):
    cue_id = "cue_" + unit_id
    bundle["script"]["captionCues"] = [c for c in bundle["script"]["captionCues"] if c["unitId"] != unit_id]
    bundle["script"]["executableActions"] = [a for a in bundle["script"]["executableActions"] if a["cueId"] != cue_id]


def build_manifest():
    base = base_bundle()
    cases = []

    def case(name, valid, mutate=lambda b: None, after=lambda b: None):
        value = deepcopy(base)
        mutate(value)
        seal(value)
        after(value)
        cases.append({"name": name, "valid": valid, "patches": patches(base, value)})

    def set_at(path, value):
        def apply(bundle):
            node = bundle
            for key in path[:-1]: node = node[key]
            node[path[-1]] = deepcopy(value)
        return apply

    case("complete-real-ready", True)
    def qa_missing(b):
        b["script"]["quality"] = None
        risk(b, "QA_UNAVAILABLE")
    case("qa-unavailable-review-draft", True, qa_missing)
    def coarse(b):
        b["materialIndex"]["units"][0]["timingQuality"] = "COARSE_BLOCK"
        b["materialIndex"]["transcripts"][0]["timingQuality"] = "COARSE_BLOCK"
        remove_caption(b, "unit_1")
        risk(b, "COARSE_ALIGNMENT", "row_1", "unit_1")
        risk(b, "SUBTITLE_UNAVAILABLE", "row_1", "unit_1")
    case("coarse-whole-block-needs-review", True, coarse)
    def mixed(b):
        b["materialIndex"]["units"][0]["asrSource"]["mode"] = "SIMULATED"
        b["materialIndex"]["transcripts"][0]["source"]["mode"] = "SIMULATED"
        remove_caption(b, "unit_1")
        risk(b, "UNTRUSTED_SOURCE", "row_1", "unit_1")
        risk(b, "SUBTITLE_UNAVAILABLE", "row_1", "unit_1")
    case("simulated-transcript-is-marked-review", True, mixed)
    def partial(b):
        b["materialIndex"]["observations"].pop()
        b["materialIndex"]["units"][2]["frameRefs"] = []
        b["script"]["rows"][1]["visualEvidence"] = []
        risk(b, "VISUAL_UNVERIFIED", "row_2", "unit_3")
        b["events"][-1]["analysisOutcome"] = "PARTIAL"
    case("partial-visual-preserves-other-evidence", True, partial)
    def no_speech(b):
        b["materialIndex"]["transcripts"] = []
        for unit in b["materialIndex"]["units"]:
            unit.update(kind="VISUAL_ONLY", originalText="", timingQuality="NONE", transcriptRefs=[])
            unit["asrSource"]["mode"] = "NO_SPEECH"
        for row in b["script"]["rows"]: row["spokenQuotes"] = []
        b["script"]["captionCues"] = []
        b["script"]["executableActions"] = [a for a in b["script"]["executableActions"] if a["type"] == "ORIGINAL_AUDIO"]
    case("no-speech-does-not-invent-quotes", True, no_speech)
    def pending(b):
        b.update(materialIndex=None, decision=None, script=None)
        b["events"] = b["events"][:2]
    case("running-task-has-no-normal-result", True, pending)
    def failure(b):
        pending(b)
        event = b["events"][-1]
        event.update(event="COMPLETED", phase="FAILED", executionStatus="FAILED", progress=70,
                     error={"code": "NO_CANDIDATE", "message": "No legal candidate found in bounded search.", "retryable": False})
    case("failed-no-candidate-without-fake-script", True, failure)
    case("accepted-manual-suggestion-is-not-executed", True, set_at(["script", "packagingSuggestions", 0, "status"], "ACCEPTED_MANUAL"))
    case("desired-duration-is-a-preference", True, lambda b: (b["submission"]["input"]["target"].update(desiredDurationMs=14000), b["script"]["target"].update(desiredDurationMs=14000)))
    case("heartbeat-does-not-require-progress-change", True, set_at(["events", 1, "progress"], 12))
    def trimmed(b):
        b["decision"]["rows"] = b["decision"]["rows"][1:]
        b["script"]["rows"] = b["script"]["rows"][1:]
        b["script"]["rows"][0].update(shotNo=1, outputRange={"startMs": 0, "endMs": 4000})
        b["script"]["estimatedDurationMs"] = 4000
        b["script"]["captionCues"] = b["script"]["captionCues"][2:]
        b["script"]["captionCues"][0]["outputRange"] = {"startMs": 0, "endMs": 4000}
        b["script"]["executableActions"] = [a for a in b["script"]["executableActions"] if a["rowId"] == "row_2"]
        b["script"]["packagingSuggestions"] = []
    case("trimmed-output-has-independent-timebase", True, trimmed)
    case("subtitle-source-timestamp-after-trimming", False, lambda b: (trimmed(b), b["script"]["captionCues"][0].update(outputRange={"startMs": 8000, "endMs": 12000})))
    for name, path, value in [
        ("director-free-time", ["decision", "rows", 0, "sourceRange"], {"startMs": 1, "endMs": 2}),
        ("director-invented-quote", ["decision", "rows", 0, "spokenText"], "Made up"),
        ("director-command", ["decision", "rows", 0, "command"], "ffmpeg anything"),
        ("unknown-unit", ["decision", "rows", 0, "sourceUnitRefs", 0], "foreign_unit"),
        ("unknown-frame", ["materialIndex", "units", 0, "frameRefs", 0], "foreign_frame"),
        ("unknown-transcript", ["materialIndex", "units", 0, "transcriptRefs", 0], "foreign_asr"),
        ("forged-index-quote", ["materialIndex", "units", 0, "originalText"], "伪造的索引原话"),
        ("coarse-ASR-falsely-promoted", ["materialIndex", "transcripts", 0, "timingQuality"], "COARSE_BLOCK"),
        ("coarse-ASR-partially-selected", ["materialIndex", "transcripts", 0, "sourceRange", "endMs"], 5000),
        ("duplicate-scene-id", ["materialIndex", "scenes", 1, "sceneId"], "scene_1"),
        ("scene-coverage-gap", ["materialIndex", "scenes", 1, "sourceRange", "startMs"], 6001),
        ("scene-missing-tail", ["materialIndex", "scenes", 1, "sourceRange", "endMs"], 11999),
        ("unknown-index-version", ["decision", "indexRef", "indexVersion"], 999),
        ("foreign-source-hash", ["script", "assetRef", "assetHash"], ZERO),
        ("fractional-source-time", ["materialIndex", "units", 0, "sourceRange", "startMs"], 0.25),
        ("string-time", ["materialIndex", "units", 0, "sourceRange", "startMs"], "0"),
        ("boolean-time", ["materialIndex", "units", 0, "sourceRange", "startMs"], False),
        ("unsafe-integer-time", ["submission", "assetRef", "durationMs"], 9007199254740992),
        ("numeric-id", ["submission", "input", "assetId"], 101),
        ("empty-topic", ["submission", "input", "target", "topic"], "   "),
        ("boolean-string", ["submission", "input", "target", "subtitleRequested"], "true"),
        ("unsupported-speed", ["submission", "input", "target", "speed"], 2),
        ("partial-coarse-unit-cut", ["script", "rows", 0, "sourceParts", 0, "sourceRange", "startMs"], 1),
        ("quote-rewrite", ["script", "rows", 0, "spokenQuotes", 0, "text"], "模型改写的原话"),
        ("visual-invention", ["script", "rows", 0, "visualEvidence", 0, "observedDescription"], "受访者在跳舞"),
        ("output-time-gap", ["script", "rows", 1, "outputRange", "startMs"], 8001),
        ("wrong-total-duration", ["script", "estimatedDurationMs"], 11999),
        ("caption-source-time-instead-of-output", ["script", "captionCues", 2, "outputRange", "startMs"], 0),
        ("caption-rewrite", ["script", "captionCues", 0, "text"], "Rewrite"),
        ("unsupported-action", ["script", "executableActions", 0, "type"], "SPEED"),
        ("model-compiled-packaging", ["script", "packagingSuggestions", 0, "status"], "COMPILED"),
        ("wrong-archive-revision", ["script", "revision"], 0),
        ("path-traversal-key", ["submission", "mediaObjectKey"], "projects/../private.mp4"),
        ("absolute-filesystem-path", ["submission", "mediaObjectKey"], "/private/tmp/source.mp4"),
        ("unknown-message-version", ["submission", "protocolVersion"], "2.0"),
        ("selected-asset-mismatch", ["submission", "input", "assetId"], "another_asset"),
        ("wrong-generation-task", ["script", "generationTaskId"], "another_task"),
        ("progress-result-leak", ["events", 0, "resultRefs"], {}),
        ("progress-at-100", ["events", 0, "progress"], 100),
        ("unknown-phase", ["events", 0, "phase"], "RENDERING"),
        ("invalid-heartbeat-calendar", ["events", 0, "heartbeatAt"], "2026-02-30T00:00:00Z"),
        ("heartbeat-must-use-UTC", ["events", 0, "heartbeatAt"], "2026-01-01T08:00:00+08:00"),
        ("heartbeat-cannot-be-text", ["events", 0, "heartbeatAt"], "yesterday"),
        ("old-attempt-callback", ["events", 2, "attempt"], 2),
        ("foreign-run-callback", ["events", 2, "runId"], "another_run"),
        ("foreign-task-callback", ["events", 2, "taskId"], "another_task"),
        ("foreign-asset-callback", ["events", 2, "assetHash"], ZERO),
        ("progress-regression", ["events", 1, "progress"], 5),
        ("sequence-regression", ["events", 1, "sequence"], 1),
        ("duplicate-event-id", ["events", 1, "eventId"], "event_1"),
        ("terminal-without-results", ["events", 2, "resultRefs"], None),
        ("partial-cannot-be-ready", ["events", 2, "analysisOutcome"], "PARTIAL"),
        ("success-with-error", ["events", 2, "error"], {"code": "MODEL_FAILED", "message": "failure", "retryable": True}),
        ("qa-failure-without-risk", ["script", "quality", "passed"], False),
    ]:
        case(name, False, set_at(path, value))
    case("stale-input-hash", False, after=set_at(["events", 2, "inputHash"], ZERO))
    case("stale-index-hash", False, after=set_at(["decision", "indexRef", "indexHash"], ZERO))
    case("stale-script-hash", False, after=set_at(["script", "scriptHash"], ZERO))
    case("stale-qa-candidate", False, after=set_at(["script", "quality", "candidateHash"], ZERO))
    case("stale-validation-candidate", False, after=set_at(["script", "validationReport", "candidateHash"], ZERO))
    case("stale-result-hash", False, after=set_at(["events", 2, "resultRefs", "script", "contentHash"], ZERO))
    case("required-dependency-removed", False, lambda b: b["decision"]["rows"][0]["sourceUnitRefs"].remove("unit_1"))
    case("noncontiguous-units-hidden-in-one-row", False, set_at(["decision", "rows", 0, "sourceUnitRefs"], ["unit_1", "unit_3"]))
    case("duplicate-unit-selection", False, set_at(["decision", "rows", 1, "sourceUnitRefs"], ["unit_2"]))
    case("source-order-reversed", False, lambda b: b["decision"]["rows"].reverse())
    case("missing-required-nullable-field", False, lambda b: b["submission"]["input"]["target"].pop("desiredDurationMs"))
    case("duration-above-hard-max", False, lambda b: (b["submission"]["input"]["target"].update(maxDurationMs=11000, desiredDurationMs=None), b["script"]["target"].update(maxDurationMs=11000, desiredDurationMs=None)))
    case("coarse-cannot-have-precise-caption", False, set_at(["materialIndex", "units", 0, "timingQuality"], "COARSE_BLOCK"))
    case("no-speech-with-fabricated-dialogue", False, lambda b: (no_speech(b), b["materialIndex"]["units"][0].update(originalText="invented")))
    case("untrusted-source-cannot-be-ready", False, lambda b: (mixed(b), b["script"].update(reviewStatus="READY"), b["events"][-1].update(reviewStatus="READY")))
    def hard_failure(b):
        ref = risk(b, "SEMANTIC_REVIEW", "row_1", "unit_1", "HARD")
        b["script"]["validationReport"]["hardPassed"] = False
        b["script"]["quality"].update(passed=False, issueRefs=[ref])
    case("hard-invalid-cannot-be-success", False, hard_failure)
    def late(b):
        event = deepcopy(b["events"][0]); event.update(eventId="late_event", sequence=4, progress=100)
        b["events"].append(event)
    case("late-progress-cannot-revive-terminal", False, late)
    def failed_with_result(b):
        b["events"][-1].update(executionStatus="FAILED", phase="FAILED", progress=99, analysisOutcome="NONE",
                              reviewStatus="NOT_AVAILABLE", error={"code": "MODEL_FAILED", "message": "failed", "retryable": True})
    case("failure-cannot-carry-normal-results", False, failed_with_result)
    return {"fixtureVersion": "1.0", "fictional": True, "base": base, "cases": cases}


if __name__ == "__main__":
    target = ROOT / "docs/contracts/script-contracts-v1.fixtures.json"
    target.write_text(json.dumps(build_manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
