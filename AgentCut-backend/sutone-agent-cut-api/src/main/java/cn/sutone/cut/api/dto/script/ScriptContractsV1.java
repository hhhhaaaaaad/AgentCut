package cn.sutone.cut.api.dto.script;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

import static cn.sutone.cut.api.dto.script.B1TypesV1.*;

/** Additive, context-bound B1 reader. It is not installed on the legacy endpoints. */
public final class ScriptContractsV1 {
    private static final ObjectMapper JSON = new ObjectMapper();
    private ScriptContractsV1() {}
    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalArgumentException(message);
    }
    private static String text(JsonNode node, String key) { return node.get(key).asText(); }
    private static long num(JsonNode node, String key) { return node.get(key).longValue(); }
    private static List<String> strings(JsonNode node) {
        List<String> result = new ArrayList<>();
        node.forEach(item -> result.add(item.asText()));
        return result;
    }
    private static void unique(List<String> values, String field) {
        require(values.size() == new HashSet<>(values).size(), "duplicate " + field);
    }
    private static Map<String, JsonNode> keyed(JsonNode values, String field) {
        Map<String, JsonNode> result = new LinkedHashMap<>();
        values.forEach(value -> require(result.put(text(value, field), value) == null, "duplicate " + field));
        return result;
    }
    private static ObjectNode object(Object... fields) {
        ObjectNode node = JSON.createObjectNode();
        for (int i = 0; i < fields.length; i += 2) node.set(fields[i].toString(), JSON.valueToTree(fields[i + 1]));
        return node;
    }
    private static ArrayNode array(List<?> values) { return JSON.valueToTree(values); }
    private static JsonNode without(JsonNode value, String... keys) {
        ObjectNode copy = value.deepCopy();
        copy.remove(List.of(keys));
        return copy;
    }
    private static JsonNode normalize(JsonNode node) {
        if (node.isObject()) {
            ObjectNode result = JSON.createObjectNode();
            Map<String, JsonNode> sorted = new TreeMap<>();
            node.fields().forEachRemaining(field -> sorted.put(field.getKey(), field.getValue()));
            sorted.forEach((key, value) -> result.set(key, normalize(value)));
            return result;
        }
        if (node.isArray()) {
            ArrayNode result = JSON.createArrayNode();
            node.forEach(value -> result.add(normalize(value)));
            return result;
        }
        if (node.isNumber() && node.canConvertToLong() && node.asDouble() == Math.rint(node.asDouble())
                && Math.abs(node.asDouble()) <= 9007199254740991d) return JSON.getNodeFactory().numberNode(node.longValue());
        return node;
    }
    public static String canonicalHash(JsonNode value) {
        try {
            byte[] bytes = JSON.writeValueAsString(normalize(value)).getBytes(StandardCharsets.UTF_8);
            return "sha256:" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException | JsonProcessingException error) {
            throw new IllegalStateException(error);
        }
    }
    public static String indexHash(JsonNode index) { return canonicalHash(without(index, "indexHash")); }
    public static String scriptHash(JsonNode script) { return canonicalHash(without(script, "scriptHash", "validationReport", "quality", "reviewStatus")); }
    public static String inputHash(JsonNode submission) {
        return canonicalHash(object("projectId", submission.get("projectId"), "assetRef", submission.get("assetRef"),
                "configVersion", submission.get("configVersion"), "input", without(submission.get("input"), "requestId")));
    }
    public static ScriptContractBundleV1 parseBundle(String json) throws JsonProcessingException {
        JsonNode bundle = normalize(JSON.readTree(json));
        B1Structure.validate("ScriptContractBundleV1", bundle);
        validateBundle(bundle);
        return JSON.treeToValue(bundle, ScriptContractBundleV1.class);
    }
    private static void validRange(JsonNode range, long duration) {
        require(num(range, "startMs") < num(range, "endMs") && num(range, "endMs") <= duration, "invalid source/output range");
    }
    private static boolean oneOf(String value, String... allowed) { return List.of(allowed).contains(value); }
    private static boolean sameSet(List<String> left, List<String> right) { return new HashSet<>(left).equals(new HashSet<>(right)); }
    private static List<String> flattenRefs(JsonNode rows, String field) {
        List<String> result = new ArrayList<>();
        rows.forEach(row -> result.addAll(strings(row.get(field))));
        return result;
    }
    private static void validateIndex(JsonNode index) {
        require(text(index, "indexHash").equals(indexHash(index)), "indexHash mismatch");
        Map<String, JsonNode> scenes = keyed(index.get("scenes"), "sceneId");
        Map<String, JsonNode> frames = keyed(index.get("observations"), "frameId");
        Map<String, JsonNode> units = keyed(index.get("units"), "unitId");
        Map<String, JsonNode> transcripts = keyed(index.get("transcripts"), "transcriptId");
        long duration = num(index.get("assetRef"), "durationMs"), nextStart = 0;
        for (JsonNode record : transcripts.values()) {
            validRange(record.get("sourceRange"), duration);
            require(oneOf(text(record.get("source"), "mode"), "REAL", "SIMULATED", "MIXED"), "transcript requires attributed speech");
        }
        for (JsonNode scene : scenes.values()) {
            JsonNode range = scene.get("sourceRange");
            validRange(range, duration);
            require(num(range, "startMs") == nextStart, "scene index must cover the whole asset");
            nextStart = num(range, "endMs");
        }
        require(nextStart == duration, "scene index must cover the whole asset");
        for (JsonNode frame : frames.values()) {
            JsonNode scene = scenes.get(text(frame, "sceneId"));
            require(scene != null && num(scene.get("sourceRange"), "startMs") <= num(frame, "timestampMs")
                    && num(frame, "timestampMs") < num(scene.get("sourceRange"), "endMs"), "frame must belong to its scene");
        }
        long previousEnd = 0;
        for (JsonNode unit : units.values()) {
            JsonNode range = unit.get("sourceRange");
            validRange(range, duration);
            require(num(range, "startMs") >= previousEnd, "units must be ordered and nonoverlapping");
            previousEnd = num(range, "endMs");
            for (String key : List.of("transcriptRefs", "sceneRefs", "frameRefs")) unique(strings(unit.get(key)), "unit reference");
            for (String ref : strings(unit.get("sceneRefs"))) {
                JsonNode scene = scenes.get(ref);
                require(scene != null && num(scene.get("sourceRange"), "startMs") < num(range, "endMs")
                        && num(range, "startMs") < num(scene.get("sourceRange"), "endMs"), "unit scene reference must overlap");
            }
            for (String ref : strings(unit.get("frameRefs"))) {
                JsonNode frame = frames.get(ref);
                require(frame != null && strings(unit.get("sceneRefs")).contains(text(frame, "sceneId"))
                        && num(range, "startMs") <= num(frame, "timestampMs") && num(frame, "timestampMs") < num(range, "endMs"),
                        "unit frame reference is foreign");
            }
            if (text(unit, "kind").equals("SPEECH")) {
                require(!text(unit, "originalText").isBlank() && !unit.get("transcriptRefs").isEmpty()
                    && !text(unit, "timingQuality").equals("NONE") && oneOf(text(unit.get("asrSource"), "mode"), "REAL", "SIMULATED", "MIXED"),
                    "speech requires attributed transcript");
                List<String> refs = strings(unit.get("transcriptRefs"));
                require(refs.stream().allMatch(transcripts::containsKey), "unknown transcript reference");
                List<JsonNode> records = refs.stream().map(transcripts::get).toList();
                require(num(range, "startMs") == num(records.get(0).get("sourceRange"), "startMs")
                        && num(range, "endMs") == num(records.get(records.size() - 1).get("sourceRange"), "endMs"),
                        "unit must preserve whole contiguous transcript records");
                for (int i = 1; i < records.size(); i++) require(num(records.get(i - 1).get("sourceRange"), "endMs")
                        == num(records.get(i).get("sourceRange"), "startMs"), "unit must preserve whole contiguous transcript records");
                StringBuilder original = new StringBuilder();
                Map<String, Integer> ranks = Map.of("COARSE_BLOCK", 1, "SENTENCE", 2, "WORD", 3, "MANUAL", 4);
                Set<String> modes = new HashSet<>();
                for (JsonNode record : records) {
                    original.append(text(record, "text")); modes.add(text(record.get("source"), "mode"));
                    require(ranks.get(text(unit, "timingQuality")) <= ranks.get(text(record, "timingQuality")), "cannot invent finer ASR alignment");
                }
                require(original.toString().equals(text(unit, "originalText")), "unit text differs from transcript evidence");
                require(text(unit.get("asrSource"), "mode").equals(modes.size() == 1 ? modes.iterator().next() : "MIXED"), "unit ASR provenance mismatch");
            } else {
                require(text(unit, "originalText").isEmpty() && unit.get("transcriptRefs").isEmpty()
                    && text(unit, "timingQuality").equals("NONE") && oneOf(text(unit.get("asrSource"), "mode"), "NO_SPEECH", "UNAVAILABLE"),
                    "visual-only unit cannot invent speech");
                if (text(unit.get("asrSource"), "mode").equals("NO_SPEECH")) require(transcripts.values().stream().noneMatch(record ->
                        num(record.get("sourceRange"), "startMs") < num(range, "endMs") && num(range, "startMs") < num(record.get("sourceRange"), "endMs")),
                        "NO_SPEECH contradicts indexed transcript");
            }
            List<String> dependencies = new ArrayList<>();
            for (JsonNode dependency : unit.get("dependencies")) {
                String ref = text(dependency, "unitId"); dependencies.add(ref);
                require(units.containsKey(ref) && !ref.equals(text(unit, "unitId")), "unknown/self dependency");
            }
            unique(dependencies, "dependency");
        }
    }
    private static void validateDecision(JsonNode decision, JsonNode index) {
        require(decision.get("indexRef").equals(object("indexId", index.get("indexId"), "indexVersion", index.get("indexVersion"),
                "indexHash", index.get("indexHash"))), "decision index binding mismatch");
        Map<String, JsonNode> rows = keyed(decision.get("rows"), "rowId"), units = keyed(index.get("units"), "unitId");
        List<String> proposals = new ArrayList<>(), selected = flattenRefs(decision.get("rows"), "sourceUnitRefs");
        decision.get("rows").forEach(row -> row.get("packagingSuggestions").forEach(p -> proposals.add(text(p, "suggestionId"))));
        unique(proposals, "suggestionId"); unique(selected, "selected unit");
        require(selected.stream().allMatch(units::containsKey), "unknown selected unit");
        long previousEnd = 0;
        for (JsonNode row : rows.values()) {
            List<String> refs = strings(row.get("sourceUnitRefs"));
            require(num(units.get(refs.get(0)).get("sourceRange"), "startMs") >= previousEnd, "source order changed or overlaps");
            for (int i = 1; i < refs.size(); i++) require(num(units.get(refs.get(i - 1)).get("sourceRange"), "endMs")
                    == num(units.get(refs.get(i)).get("sourceRange"), "startMs"), "noncontiguous units must use separate rows");
            previousEnd = num(units.get(refs.get(refs.size() - 1)).get("sourceRange"), "endMs");
        }
        for (String ref : selected) for (JsonNode dependency : units.get(ref).get("dependencies"))
            require(!text(dependency, "level").equals("REQUIRED") || selected.contains(text(dependency, "unitId")), "required dependency removed");
    }
    private static void validateScript(JsonNode script, JsonNode index, JsonNode decision) {
        require(script.get("assetRef").equals(index.get("assetRef")) && script.get("indexRef").equals(decision.get("indexRef"))
                && script.get("inputHash").equals(decision.get("inputHash")), "script input/index binding mismatch");
        require(text(script, "scriptHash").equals(scriptHash(script)), "scriptHash mismatch");
        require(script.get("validationReport").get("candidateHash").equals(script.get("scriptHash")), "validation belongs to another candidate");
        JsonNode quality = script.get("quality"), target = script.get("target");
        require(quality.isNull() || quality.get("candidateHash").equals(script.get("scriptHash")), "QA belongs to another candidate");
        require(target.get("desiredDurationMs").isNull() || num(target, "desiredDurationMs") <= num(target, "maxDurationMs"), "desired duration exceeds hard maximum");
        Map<String, JsonNode> rows = keyed(script.get("rows"), "rowId"), chosenRows = keyed(decision.get("rows"), "rowId"),
                units = keyed(index.get("units"), "unitId"), frames = keyed(index.get("observations"), "frameId"),
                risks = keyed(script.get("riskItems"), "riskId"), cues = keyed(script.get("captionCues"), "cueId");
        keyed(script.get("executableActions"), "actionId"); keyed(script.get("packagingSuggestions"), "suggestionId");
        require(new ArrayList<>(rows.keySet()).equals(new ArrayList<>(chosenRows.keySet())), "script rows differ from decision");
        Set<String> selected = new HashSet<>(flattenRefs(script.get("rows"), "sourceUnitRefs"));
        for (JsonNode risk : risks.values()) {
            List<String> rowRefs = strings(risk.get("rowRefs")), unitRefs = strings(risk.get("unitRefs"));
            unique(rowRefs, "risk row reference"); unique(unitRefs, "risk unit reference");
            require(rows.keySet().containsAll(rowRefs) && units.keySet().containsAll(unitRefs), "unknown risk reference");
        }
        require(sameSet(strings(script.get("validationReport").get("issueRefs")), new ArrayList<>(risks.keySet())), "validation must list all risks");
        require(script.get("validationReport").get("hardPassed").asBoolean()
                == risks.values().stream().noneMatch(r -> text(r, "level").equals("HARD")), "hard gate and hard risks disagree");
        if (!quality.isNull()) {
            unique(strings(quality.get("issueRefs")), "QA issue reference");
            require(risks.keySet().containsAll(strings(quality.get("issueRefs"))), "unknown QA risk reference");
            require(quality.get("passed").asBoolean() || !quality.get("issueRefs").isEmpty(), "failed QA requires risk references");
        }
        long elapsed = 0, number = 0;
        boolean riskySource = false;
        for (JsonNode row : rows.values()) {
            JsonNode chosen = chosenRows.get(text(row, "rowId"));
            require(num(row, "shotNo") == ++number && row.get("sourceUnitRefs").equals(chosen.get("sourceUnitRefs"))
                    && row.get("narrativeRole").equals(chosen.get("narrativeRole"))
                    && row.get("selectionReason").equals(chosen.get("selectionReason")), "script decision projection changed");
            List<JsonNode> rowUnits = strings(row.get("sourceUnitRefs")).stream().map(units::get).toList();
            List<JsonNode> parts = new ArrayList<>(), quotes = new ArrayList<>(), visual = new ArrayList<>();
            List<String> frameIds = new ArrayList<>(), dependencies = new ArrayList<>(), rowRisks = new ArrayList<>();
            long length = 0;
            for (JsonNode unit : rowUnits) {
                parts.add(object("unitId", unit.get("unitId"), "sourceRange", unit.get("sourceRange")));
                length += num(unit.get("sourceRange"), "endMs") - num(unit.get("sourceRange"), "startMs");
                if (text(unit, "kind").equals("SPEECH")) quotes.add(object("unitId", unit.get("unitId"), "text", unit.get("originalText")));
                for (String ref : strings(unit.get("frameRefs"))) if (!frameIds.contains(ref)) frameIds.add(ref);
                for (JsonNode dep : unit.get("dependencies")) if (!dependencies.contains(text(dep, "unitId"))) dependencies.add(text(dep, "unitId"));
            }
            for (String ref : frameIds) visual.add(object("frameId", ref, "observedDescription", frames.get(ref).get("description")));
            require(row.get("sourceParts").equals(array(parts)), "source parts must map whole index units");
            require(row.get("outputRange").equals(object("startMs", elapsed, "endMs", elapsed + length)), "output time must be cumulative original speed");
            elapsed += length;
            require(row.get("spokenQuotes").equals(array(quotes)), "spoken quote differs from original");
            require(row.get("visualEvidence").equals(array(visual)), "visual fact differs from indexed observation");
            require(strings(row.get("dependencyRefs")).equals(dependencies), "dependency projection changed");
            for (JsonNode risk : risks.values()) if (strings(risk.get("rowRefs")).contains(text(row, "rowId"))) rowRisks.add(text(risk, "riskId"));
            unique(strings(row.get("riskRefs")), "row risk reference");
            require(sameSet(strings(row.get("riskRefs")), rowRisks), "row risk projection changed");
            for (JsonNode unit : rowUnits) {
                Set<String> codes = new HashSet<>();
                for (JsonNode risk : risks.values()) if (strings(risk.get("rowRefs")).contains(text(row, "rowId"))
                        && strings(risk.get("unitRefs")).contains(text(unit, "unitId"))) codes.add(text(risk, "code"));
                if (text(unit, "timingQuality").equals("COARSE_BLOCK")) require(codes.contains("COARSE_ALIGNMENT"), "coarse alignment must be disclosed");
                if (!oneOf(text(unit.get("asrSource"), "mode"), "REAL", "NO_SPEECH")) {
                    require(codes.contains("UNTRUSTED_SOURCE"), "untrusted ASR must be disclosed"); riskySource = true;
                }
                if (unit.get("frameRefs").isEmpty() || strings(unit.get("frameRefs")).stream().anyMatch(ref -> !text(frames.get(ref).get("source"), "mode").equals("REAL"))) {
                    require(codes.contains("VISUAL_UNVERIFIED"), "unverified visual evidence must be disclosed"); riskySource = true;
                }
                for (JsonNode dep : unit.get("dependencies")) if (text(dep, "level").equals("REVIEW") && !selected.contains(text(dep, "unitId")))
                    require(codes.contains("MISSING_DEPENDENCY"), "missing review dependency must be disclosed");
            }
        }
        require(elapsed == num(script, "estimatedDurationMs") && elapsed <= num(target, "maxDurationMs"), "duration must be exact and within hard maximum");
        Set<String> cueUnits = new HashSet<>(); long previousCaptionEnd = 0;
        for (JsonNode cue : cues.values()) {
            JsonNode row = rows.get(text(cue, "rowId")), unit = units.get(text(cue, "unitId"));
            require(row != null && unit != null && strings(row.get("sourceUnitRefs")).contains(text(cue, "unitId"))
                    && text(unit, "kind").equals("SPEECH") && text(unit.get("asrSource"), "mode").equals("REAL")
                    && cue.get("timingQuality").equals(unit.get("timingQuality")), "caption requires reliable original alignment");
            require(cueUnits.add(text(cue, "unitId")) && cue.get("text").equals(unit.get("originalText")), "caption must quote an entire aligned unit once");
            long offset = 0;
            for (String ref : strings(row.get("sourceUnitRefs"))) {
                if (ref.equals(text(cue, "unitId"))) break;
                offset += num(units.get(ref).get("sourceRange"), "endMs") - num(units.get(ref).get("sourceRange"), "startMs");
            }
            long start = num(row.get("outputRange"), "startMs") + offset;
            require(cue.get("outputRange").equals(object("startMs", start, "endMs", start + num(unit.get("sourceRange"), "endMs") - num(unit.get("sourceRange"), "startMs"))),
                    "caption must use global output time");
            require(num(cue.get("outputRange"), "startMs") >= previousCaptionEnd, "captions must be ordered without overlap");
            previousCaptionEnd = num(cue.get("outputRange"), "endMs");
        }
        if (target.get("subtitleRequested").asBoolean()) for (JsonNode row : rows.values()) for (String ref : strings(row.get("sourceUnitRefs")))
            if (text(units.get(ref), "kind").equals("SPEECH") && !cueUnits.contains(ref)) require(risks.values().stream().anyMatch(r -> text(r, "code").equals("SUBTITLE_UNAVAILABLE")
                    && strings(r.get("rowRefs")).contains(text(row, "rowId")) && strings(r.get("unitRefs")).contains(ref)), "unmet subtitle requirement must be disclosed");
        List<String> usedCues = new ArrayList<>(), audioRows = new ArrayList<>();
        for (JsonNode action : script.get("executableActions")) {
            String rowId = text(action, "rowId"); require(rows.containsKey(rowId), "action references unknown row");
            if (text(action, "type").equals("CAPTION")) {
                JsonNode cue = cues.get(text(action, "cueId"));
                require(cue != null && text(cue, "rowId").equals(rowId), "action references foreign caption");
                usedCues.add(text(action, "cueId"));
            } else { require(action.get("cueId").isNull(), "audio action cannot reference caption"); audioRows.add(rowId); }
        }
        require(usedCues.size() == cues.size() && sameSet(usedCues, new ArrayList<>(cues.keySet())), "each caption must have exactly one action");
        require(audioRows.size() == rows.size() && sameSet(audioRows, new ArrayList<>(rows.keySet())), "each row must preserve original audio exactly once");
        List<JsonNode> proposals = new ArrayList<>();
        for (JsonNode chosen : chosenRows.values()) for (JsonNode proposal : chosen.get("packagingSuggestions")) {
            ObjectNode projected = proposal.deepCopy(); projected.set("rowId", chosen.get("rowId")); proposals.add(projected);
        }
        require(proposals.size() == script.get("packagingSuggestions").size(), "packaging projection changed");
        for (int i = 0; i < proposals.size(); i++) require(proposals.get(i).equals(without(script.get("packagingSuggestions").get(i), "status")), "packaging proposal changed");
        if (text(script, "reviewStatus").equals("READY")) require(script.get("validationReport").get("hardPassed").asBoolean()
                && risks.isEmpty() && !riskySource && !quality.isNull() && quality.get("passed").asBoolean(), "READY requires hard and semantic review");
        if (quality.isNull()) require(risks.values().stream().anyMatch(r -> text(r, "code").equals("QA_UNAVAILABLE")), "missing QA must be disclosed");
    }
    private static void validateSubmission(JsonNode submission) {
        require(submission.get("input").get("assetId").equals(submission.get("assetRef").get("assetId")), "selected asset mismatch");
        require(text(submission, "inputHash").equals(inputHash(submission)), "inputHash mismatch");
        JsonNode target = submission.get("input").get("target");
        require(target.get("desiredDurationMs").isNull() || num(target, "desiredDurationMs") <= num(target, "maxDurationMs"), "desired duration exceeds hard maximum");
        for (String part : text(submission, "mediaObjectKey").split("/", -1))
            require(!oneOf(part, "", ".", ".."), "media key must be an object key, not a filesystem path");
    }
    private static void validateEvent(JsonNode event, JsonNode submission) {
        try {
            require(java.time.Instant.parse(text(event, "heartbeatAt")).toString().equals(text(event, "heartbeatAt")), "invalid UTC heartbeat");
        } catch (java.time.format.DateTimeParseException error) {
            throw new IllegalArgumentException("invalid UTC heartbeat", error);
        }
        for (String field : List.of("taskId", "projectId", "runId", "attempt", "inputHash"))
            require(event.get(field).equals(submission.get(field)), "event belongs to another run/input");
        require(event.get("requestId").equals(submission.get("input").get("requestId"))
                && event.get("assetId").equals(submission.get("assetRef").get("assetId"))
                && event.get("assetHash").equals(submission.get("assetRef").get("assetHash")), "event input identity mismatch");
        if (text(event, "event").equals("PROGRESS")) require(text(event, "executionStatus").equals("RUNNING") && num(event, "progress") < 100
                && !oneOf(text(event, "phase"), "COMPLETED", "FAILED") && text(event, "analysisOutcome").equals("NONE")
                && text(event, "reviewStatus").equals("NOT_AVAILABLE") && event.get("resultRefs").isNull() && event.get("error").isNull(), "progress cannot publish a terminal result");
        else if (text(event, "executionStatus").equals("SUCCESS")) {
            require(num(event, "progress") == 100 && text(event, "phase").equals("COMPLETED")
                    && oneOf(text(event, "analysisOutcome"), "COMPLETE", "PARTIAL") && oneOf(text(event, "reviewStatus"), "READY", "NEEDS_REVIEW")
                    && !event.get("resultRefs").isNull() && event.get("error").isNull(), "successful completion requires qualified result references");
            require(!text(event, "analysisOutcome").equals("PARTIAL") || text(event, "reviewStatus").equals("NEEDS_REVIEW"), "partial result cannot be READY");
        } else require(text(event, "executionStatus").equals("FAILED") && text(event, "phase").equals("FAILED") && num(event, "progress") < 100
                && text(event, "analysisOutcome").equals("NONE") && text(event, "reviewStatus").equals("NOT_AVAILABLE")
                && event.get("resultRefs").isNull() && !event.get("error").isNull(), "failure cannot carry a normal result");
    }
    private static void validateBundle(JsonNode bundle) {
        JsonNode index = bundle.get("materialIndex"), decision = bundle.get("decision"), script = bundle.get("script"), submission = bundle.get("submission");
        validateSubmission(submission);
        if (!index.isNull()) { validateIndex(index); require(index.get("assetRef").equals(submission.get("assetRef")), "index asset binding mismatch"); }
        if (!decision.isNull()) {
            require(!index.isNull(), "decision requires its index context"); validateDecision(decision, index);
            require(decision.get("inputHash").equals(submission.get("inputHash")), "decision input binding mismatch");
        }
        if (!script.isNull()) {
            require(!decision.isNull(), "script requires its decision context"); validateScript(script, index, decision);
            require(script.get("projectId").equals(submission.get("projectId")) && script.get("generationTaskId").equals(submission.get("taskId"))
                    && script.get("target").equals(submission.get("input").get("target")), "script task/target binding mismatch");
        }
        keyed(bundle.get("events"), "eventId"); long progress = 0, sequence = 0; boolean terminal = false;
        for (JsonNode event : bundle.get("events")) {
            validateEvent(event, submission);
            require(!terminal && num(event, "sequence") > sequence && num(event, "progress") >= progress, "accepted history cannot regress or revive a terminal task");
            progress = num(event, "progress"); sequence = num(event, "sequence"); terminal = text(event, "event").equals("COMPLETED");
            if (text(event, "executionStatus").equals("SUCCESS")) {
                require(!script.isNull() && !index.isNull(), "successful result requires artifacts");
                require(script.get("validationReport").get("hardPassed").asBoolean(), "hard-invalid script cannot be a successful result");
                JsonNode refs = event.get("resultRefs");
                require(refs.get("analysis").equals(index.get("analysisRef")), "analysis result binding mismatch");
                require(refs.get("materialIndex").equals(object("artifactId", index.get("indexId"), "revision", index.get("indexVersion"), "contentHash", index.get("indexHash"))), "index result binding mismatch");
                require(refs.get("script").equals(object("artifactId", script.get("scriptId"), "revision", script.get("revision"), "contentHash", script.get("scriptHash"))), "script result binding mismatch");
                require(text(event, "reviewStatus").equals(text(script, "reviewStatus").equals("READY") ? "READY" : "NEEDS_REVIEW"), "event review state differs from script");
            }
            if (text(event, "executionStatus").equals("FAILED")) require(script.isNull() && decision.isNull() && index.isNull(), "failed result cannot carry qualified artifacts");
        }
    }
}
