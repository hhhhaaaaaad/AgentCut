package cn.sutone.cut.app.service;

import cn.sutone.cut.api.dto.script.ScriptContractsV1;
import cn.sutone.cut.domain.adapter.port.IScriptRunClient;
import cn.sutone.cut.domain.project.service.ProjectDomainService;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * B3a single-process aggregate store. One monitor publishes artifacts, history and
 * terminal state atomically. Strings are immutable; no mutable stored node escapes.
 * No project-current pointer is advanced, so older tasks cannot replace new work.
 */
@Service
@Profile("local & !mysql")
@ConditionalOnProperty(name = "agentcut.script-tasks.enabled", havingValue = "true")
public class ScriptTaskService {
    public static final class Problem extends RuntimeException {
        public final int status;
        public Problem(int status, String code) { super(code); this.status = status; }
    }
    private static final List<String> TERMINAL = List.of("SUCCESS", "NEEDS_REVIEW", "FAILED");
    private final Object lock = new Object();
    private final Map<String, State> tasks = new LinkedHashMap<>();
    private final Map<String, String> requests = new LinkedHashMap<>();
    private final PreparedScriptCatalog catalog;
    private final ProjectDomainService projects;
    private final IScriptRunClient client;
    private final ObjectMapper json;
    private final String callbackBase;
    private final int maxRetained;

    private static final class State {
        String id, project, requestHash, packet, submission, token, createdAt;
        String status = "ACCEPTING", phase = "VALIDATING_INPUT", acceptance = "PENDING";
        String bundle, error;
        int progress;
        long sequence;
        String heartbeatAt;
        final List<JsonNode> events = new ArrayList<>();
        final Map<String, String> eventHashes = new LinkedHashMap<>();
    }

    public ScriptTaskService(PreparedScriptCatalog catalog, ProjectDomainService projects, IScriptRunClient client,
                             ObjectMapper mapper,
                             @Value("${agentcut.callback.base-url:http://127.0.0.1:8080}") String callbackBase,
                             @Value("${agentcut.script-tasks.max-retained:64}") int maxRetained) {
        this.catalog = catalog;
        this.projects = projects;
        this.client = client;
        this.json = mapper.copy().enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                .enable(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
        this.callbackBase = callbackBase.replaceAll("/+$", "");
        if (maxRetained < 1 || maxRetained > 256) throw new IllegalArgumentException("invalid script capacity");
        this.maxRetained = maxRetained;
    }

    public JsonNode create(Long projectId, JsonNode input) {
        try { ScriptContractsV1.validateStructure("AnalyzeInputV1", input); }
        catch (Exception error) { throw new Problem(422, "INVALID_INPUT"); }
        String project = projectId.toString();
        String requestKey = project + "/" + input.get("requestId").asText();
        String requestHash = ScriptContractsV1.canonicalHash(input);
        State state;
        synchronized (lock) {
            String oldId = requests.get(requestKey);
            if (oldId != null) {
                State old = tasks.get(oldId);
                if (!old.requestHash.equals(requestHash)) throw new Problem(409, "REQUEST_ID_CONFLICT");
                return detail(old);
            }
            if (projects.query(projectId) == null) throw new Problem(404, "PROJECT_NOT_FOUND");
            if (tasks.size() >= maxRetained) throw new Problem(503, "SCRIPT_TASK_CAPACITY_EXCEEDED");
            JsonNode prepared = catalog.load(project, input.get("assetId").asText()).deepCopy();
            JsonNode oldSubmission = prepared.path("submission");
            ObjectNode submission = json.createObjectNode();
            String taskId = "script_" + UUID.randomUUID().toString().replace("-", "");
            String token = UUID.randomUUID().toString().replace("-", "");
            submission.put("protocolVersion", "1.0").put("messageType", "ANALYZE_REQUEST")
                    .put("taskId", taskId).put("projectId", project)
                    .put("runId", "run_" + UUID.randomUUID().toString().replace("-", ""))
                    .put("attempt", 1).put("configVersion", "prepared-script-rules-0.1")
                    .put("mediaObjectKey", oldSubmission.path("mediaObjectKey").asText())
                    .put("callbackUrl", callbackBase + "/api/v1/script-tasks/" + taskId + "/events?token=" + token);
            submission.set("input", input.deepCopy());
            submission.set("assetRef", prepared.path("sourceIndex").path("assetRef").deepCopy());
            submission.put("inputHash", ScriptContractsV1.inputHash(submission));
            // Validate new identity and target through the frozen cross-language contract.
            checked(bundle(submission, null, List.of()));
            ((ObjectNode) prepared).set("submission", submission);
            ObjectNode packet = json.createObjectNode().set("prepared", prepared);
            String encoded = packet.toString();
            if (encoded.getBytes(StandardCharsets.UTF_8).length > 5_000_000) throw new Problem(413, "PREPARED_INDEX_TOO_LARGE");
            state = new State();
            state.id = taskId; state.project = project; state.requestHash = requestHash;
            state.packet = encoded; state.submission = submission.toString(); state.token = token;
            state.createdAt = Instant.now().toString();
            tasks.put(taskId, state);
            requests.put(requestKey, taskId);
        }
        // No network call while holding the aggregate lock. A concurrent duplicate
        // sees the reserved task; a fast callback can commit before POST returns.
        try {
            JsonNode accepted = read(client.submit(state.packet));
            JsonNode submission = read(state.submission);
            if (accepted.size() != 6 || !accepted.path("protocolVersion").asText().equals("1.0")
                    || !accepted.path("status").asText().equals("accepted")
                    || !accepted.path("runId").equals(submission.get("runId"))
                    || !accepted.path("jobId").equals(submission.get("runId"))
                    || !accepted.path("taskId").equals(submission.get("taskId"))
                    || !accepted.path("inputHash").equals(submission.get("inputHash"))) {
                throw new IScriptRunClient.SubmissionException(true);
            }
            synchronized (lock) {
                state.acceptance = "ACCEPTED";
                if (!TERMINAL.contains(state.status) && state.sequence == 0) state.status = "RUNNING";
            }
        } catch (Exception error) {
            synchronized (lock) {
                boolean uncertain = !(error instanceof IScriptRunClient.SubmissionException e) || e.uncertain();
                state.acceptance = state.sequence > 0 ? "ACCEPTED" : uncertain ? "UNCERTAIN" : "REJECTED";
                // Existing callback evidence takes precedence over a transport error.
                if (!TERMINAL.contains(state.status) && state.sequence == 0) {
                    state.status = uncertain ? "SUBMISSION_UNCERTAIN" : "FAILED";
                    state.error = uncertain ? "SUBMISSION_UNCERTAIN" : "SUBMISSION_REJECTED";
                    if (!uncertain) state.phase = "FAILED";
                }
            }
        }
        synchronized (lock) { return detail(state); }
    }

    public JsonNode query(String id) { synchronized (lock) { return detail(requireTask(id)); } }

    public JsonNode list(Long projectId, int offset, int limit) {
        if (offset < 0 || limit < 1 || limit > 100) throw new Problem(422, "INVALID_PAGE");
        synchronized (lock) {
            var selected = tasks.values().stream().filter(s -> s.project.equals(projectId.toString())).toList();
            List<State> newest = new ArrayList<>(selected);
            java.util.Collections.reverse(newest);
            var items = json.createArrayNode();
            newest.stream().skip(offset).limit(limit).forEach(s -> items.add(detail(s)));
            var page = json.createObjectNode();
            page.set("items", items); page.put("total", selected.size());
            page.put("offset", offset); page.put("limit", limit);
            return page;
        }
    }

    public JsonNode result(String id, boolean scriptOnly) {
        synchronized (lock) {
            State state = requireTask(id);
            if (state.bundle == null) throw new Problem(409, "RESULT_NOT_AVAILABLE");
            JsonNode result = read(state.bundle);
            if (scriptOnly && result.get("script").isNull()) throw new Problem(409, "SCRIPT_NOT_AVAILABLE");
            if (scriptOnly) return result.get("script");
            // The per-run callback capability is transport metadata, outside inputHash.
            ObjectNode submission = (ObjectNode) result.get("submission");
            submission.put("callbackUrl", submission.get("callbackUrl").asText().split("\\?", 2)[0]);
            return result;
        }
    }

    public JsonNode evidence(String id) {
        synchronized (lock) {
            ObjectNode prepared = (ObjectNode) read(requireTask(id).packet).get("prepared");
            prepared.remove("submission");
            return prepared;
        }
    }

    public String receive(String id, String token, JsonNode envelope) {
        synchronized (lock) {
            State state = requireTask(id);
            if (token == null || !MessageDigest.isEqual(state.token.getBytes(StandardCharsets.UTF_8),
                    token.getBytes(StandardCharsets.UTF_8))) throw new Problem(403, "INVALID_CALLBACK_TOKEN");
            return accept(state, envelope);
        }
    }

    public JsonNode reconcile(String id) {
        String runId, token;
        synchronized (lock) {
            State state = requireTask(id);
            if (TERMINAL.contains(state.status)) return detail(state);
            runId = read(state.submission).get("runId").asText();
            token = state.token;
        }
        // Query only. A 404 after Python restart cannot prove a job never ran.
        JsonNode remote;
        try { remote = read(client.status(runId, token)); }
        catch (Exception error) { throw new Problem(503, "RECONCILIATION_UNAVAILABLE"); }
        synchronized (lock) {
            State state = requireTask(id);
            JsonNode submission = read(state.submission);
            for (String key : List.of("runId", "taskId", "inputHash")) {
                if (!remote.path(key).equals(submission.get(key))) throw new Problem(422, "RECONCILIATION_IDENTITY_MISMATCH");
            }
            if (!remote.path("events").isArray()) throw new Problem(422, "INVALID_RECONCILIATION");
            String execution = remote.path("executionStatus").asText();
            if (!List.of("PENDING", "RUNNING", "SUCCESS", "FAILED").contains(execution)) {
                throw new Problem(422, "INVALID_RECONCILIATION");
            }
            // Import only the latest event. Missing progress events need not be replayed.
            JsonNode events = remote.get("events");
            if (!events.isEmpty()) {
                if (!events.get(events.size() - 1).path("executionStatus").asText().equals(execution)) {
                    throw new Problem(422, "INVALID_RECONCILIATION");
                }
                var envelope = json.createObjectNode();
                envelope.set("event", events.get(events.size() - 1));
                envelope.set("bundle", remote.path("bundle"));
                accept(state, envelope);
            } else {
                if (!List.of("PENDING", "RUNNING").contains(execution) || !remote.path("bundle").isNull()) {
                    throw new Problem(422, "INVALID_RECONCILIATION");
                }
                if (!TERMINAL.contains(state.status)) {
                    state.acceptance = "ACCEPTED"; state.status = "RUNNING"; state.error = null;
                }
            }
            return detail(state);
        }
    }

    private String accept(State state, JsonNode envelope) {
        if (!envelope.isObject() || envelope.size() != 2 || !envelope.has("event") || !envelope.has("bundle")) {
            throw new Problem(422, "INVALID_CALLBACK");
        }
        JsonNode event = envelope.get("event"), submission = read(state.submission);
        try { ScriptContractsV1.validateStructure("TaskEventV1", event); }
        catch (Exception error) { throw new Problem(422, "INVALID_EVENT"); }
        for (String key : List.of("taskId", "projectId", "runId", "attempt", "inputHash")) {
            if (key.equals("attempt") ? event.get(key).longValue() != submission.get(key).longValue()
                    : !event.get(key).equals(submission.get(key))) return "IGNORED_IDENTITY";
        }
        if (!event.get("requestId").equals(submission.get("input").get("requestId"))
                || !event.get("assetId").equals(submission.get("assetRef").get("assetId"))
                || !event.get("assetHash").equals(submission.get("assetRef").get("assetHash"))) return "IGNORED_IDENTITY";
        String fingerprint = ScriptContractsV1.canonicalHash(envelope);
        String eventId = event.get("eventId").asText();
        String old = state.eventHashes.get(eventId);
        if (old != null) {
            if (!old.equals(fingerprint)) throw new Problem(409, "EVENT_ID_CONFLICT");
            return "DUPLICATE";
        }
        if (TERMINAL.contains(state.status)) return "IGNORED_TERMINAL";
        if (event.get("sequence").longValue() <= state.sequence || event.get("progress").intValue() < state.progress) return "IGNORED_STALE";
        if (state.events.size() >= 1024) throw new Problem(503, "EVENT_HISTORY_CAPACITY_EXCEEDED");
        JsonNode artifacts = envelope.get("bundle");
        boolean success = event.get("executionStatus").asText().equals("SUCCESS");
        boolean completed = event.get("event").asText().equals("COMPLETED");
        if (!artifacts.isNull()) {
            checked(artifacts);
            if (!ScriptContractsV1.canonicalHash(artifacts.get("submission")).equals(ScriptContractsV1.canonicalHash(submission))
                    || artifacts.get("events").isEmpty()
                    || !ScriptContractsV1.canonicalHash(artifacts.get("events").get(artifacts.get("events").size() - 1))
                        .equals(ScriptContractsV1.canonicalHash(event))) {
                throw new Problem(422, "RESULT_IDENTITY_MISMATCH");
            }
        }
        if (success && artifacts.isNull() || !completed && !artifacts.isNull()) throw new Problem(422, "INVALID_RESULT");
        if (success) {
            JsonNode prepared = read(state.packet).get("prepared"), evidence = prepared.get("evidence");
            JsonNode index = artifacts.get("materialIndex"), ref = index.get("analysisRef");
            if (!ref.get("artifactId").equals(evidence.get("evidenceId"))
                    || ref.get("revision").longValue() != evidence.get("revision").longValue()
                    || !ref.get("contentHash").asText().equals(ScriptContractsV1.canonicalHash(evidence))
                    || index.get("indexVersion").longValue() != prepared.path("indexVersion").asLong(1)) {
                throw new Problem(422, "RESULT_EVIDENCE_BINDING_MISMATCH");
            }
        }
        List<JsonNode> history = new ArrayList<>(state.events);
        history.add(event.deepCopy());
        ObjectNode combined = bundle(submission, artifacts, history);
        checked(combined);
        // Every fallible validation precedes this single atomic publication.
        if (completed) state.bundle = combined.toString();
        state.events.add(event.deepCopy());
        state.eventHashes.put(eventId, fingerprint);
        state.sequence = event.get("sequence").longValue(); state.progress = event.get("progress").intValue();
        state.phase = event.get("phase").asText(); state.heartbeatAt = event.get("heartbeatAt").asText();
        state.status = completed ? success ? event.get("reviewStatus").asText().equals("READY") ? "SUCCESS" : "NEEDS_REVIEW" : "FAILED" : "RUNNING";
        state.error = event.get("error").isNull() ? null : event.get("error").toString();
        state.acceptance = "ACCEPTED";
        return "ACCEPTED";
    }

    private State requireTask(String id) {
        State state = tasks.get(id);
        if (state == null) throw new Problem(404, "SCRIPT_TASK_NOT_FOUND");
        return state;
    }
    private JsonNode detail(State state) {
        JsonNode submission = read(state.submission);
        var node = json.createObjectNode();
        node.put("taskId", state.id).put("projectId", state.project).put("runId", submission.get("runId").asText())
                .put("inputHash", submission.get("inputHash").asText()).put("status", state.status)
                .put("acceptance", state.acceptance).put("phase", state.phase).put("progress", state.progress)
                .put("sequence", state.sequence).put("createdAt", state.createdAt).put("heartbeatAt", state.heartbeatAt)
                .put("error", state.error).put("hasScript", state.bundle != null && !read(state.bundle).get("script").isNull());
        node.set("input", submission.get("input")); node.set("assetRef", submission.get("assetRef"));
        return node;
    }
    private ObjectNode bundle(JsonNode submission, JsonNode artifacts, List<JsonNode> history) {
        var bundle = json.createObjectNode();
        for (String key : List.of("materialIndex", "decision", "script")) {
            bundle.set(key, artifacts == null ? json.nullNode() : artifacts.get(key));
        }
        bundle.set("submission", submission);
        ArrayNode events = bundle.putArray("events"); history.forEach(events::add);
        return bundle;
    }
    private void checked(JsonNode value) {
        try { ScriptContractsV1.parseBundle(value.toString()); }
        catch (Exception error) { throw new Problem(422, "SCRIPT_CONTRACT_VALIDATION_FAILED"); }
    }
    public JsonNode read(String value) {
        try { return json.readTree(value); }
        catch (Exception error) { throw new Problem(422, "INVALID_JSON"); }
    }
}
