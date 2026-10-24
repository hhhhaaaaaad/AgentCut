package cn.sutone.cut.app;

import cn.sutone.cut.api.dto.script.ScriptContractsV1;
import cn.sutone.cut.app.service.PreparedScriptCatalog;
import cn.sutone.cut.app.service.ScriptTaskService;
import cn.sutone.cut.domain.adapter.port.IScriptRunClient;
import cn.sutone.cut.domain.project.service.ProjectDomainService;
import cn.sutone.cut.infrastructure.persistence.project.InMemoryProjectRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

class ScriptTaskServiceTest {
    @TempDir Path directory;
    final ObjectMapper json = new ObjectMapper();
    Path docs = Path.of("..", "..", "docs", "contracts");
    Stub client;
    ScriptTaskService service;
    ProjectDomainService projects;
    JsonNode input;

    class Stub implements IScriptRunClient {
        JsonNode packet, remote;
        final AtomicInteger posts = new AtomicInteger();
        boolean uncertain, rejected, malformed;
        Runnable onSubmit;
        public String submit(String snapshot) {
            posts.incrementAndGet();
            try { packet = json.readTree(snapshot); } catch (Exception e) { throw new AssertionError(e); }
            if (onSubmit != null) onSubmit.run();
            if (uncertain || rejected) throw new SubmissionException(uncertain);
            if (malformed) return "{}";
            JsonNode s = packet.get("prepared").get("submission");
            ObjectNode accepted = json.createObjectNode().put("protocolVersion", "1.0").put("status", "accepted");
            for (String key : List.of("runId", "taskId", "inputHash")) accepted.set(key, s.get(key));
            accepted.set("jobId", s.get("runId"));
            return accepted.toString();
        }
        public String status(String runId, String token) {
            assertEquals(submission().get("runId").asText(), runId);
            assertEquals(token(), token);
            if (remote == null) throw new SubmissionException(true);
            return remote.toString();
        }
    }

    @BeforeEach void setup() throws Exception {
        JsonNode prepared = json.readTree(Files.readString(docs.resolve("offline-id-director.input.json")));
        ((ObjectNode) prepared.get("submission")).put("projectId", "1");
        Files.createDirectories(directory.resolve("1"));
        String assetId = prepared.get("sourceIndex").get("assetRef").get("assetId").asText();
        Files.writeString(directory.resolve("1").resolve(assetId + ".json"), prepared.toString());
        input = prepared.get("submission").get("input").deepCopy();
        projects = new ProjectDomainService(new InMemoryProjectRepository());
        projects.createProject(0L, "Synthetic prepared-index integration");
        client = new Stub();
        service = new ScriptTaskService(new PreparedScriptCatalog(directory.toString(), json), projects, client,
                json, "http://127.0.0.1:8080", 64);
    }
    JsonNode submission() { return client.packet.get("prepared").get("submission"); }
    String token() { return submission().get("callbackUrl").asText().split("token=", 2)[1]; }
    String task() { return submission().get("taskId").asText(); }

    ObjectNode event(int sequence, int progress, boolean success) {
        JsonNode s = submission();
        ObjectNode event = json.createObjectNode().put("protocolVersion", "1.0")
                .put("event", success ? "COMPLETED" : "PROGRESS").put("eventId", "evt_" + sequence)
                .put("sequence", sequence).put("heartbeatAt", "2026-10-24T08:00:00Z")
                .put("phase", success ? "COMPLETED" : "CHECKING").put("progress", progress)
                .put("executionStatus", success ? "SUCCESS" : "RUNNING")
                .put("analysisOutcome", success ? "COMPLETE" : "NONE")
                .put("reviewStatus", success ? "NEEDS_REVIEW" : "NOT_AVAILABLE");
        for (String key : List.of("taskId", "projectId", "runId", "attempt", "inputHash")) event.set(key, s.get(key));
        event.set("requestId", s.get("input").get("requestId"));
        event.set("assetId", s.get("assetRef").get("assetId")); event.set("assetHash", s.get("assetRef").get("assetHash"));
        event.putNull("resultRefs"); event.putNull("error");
        return event;
    }
    ObjectNode envelope(JsonNode event, JsonNode bundle) {
        var envelope = json.createObjectNode();
        envelope.set("event", event); envelope.set("bundle", bundle == null ? json.nullNode() : bundle);
        return envelope;
    }
    ObjectNode completed() throws Exception {
        ObjectNode bundle = (ObjectNode) json.readTree(Files.readString(docs.resolve("offline-id-director.bundle.json")));
        JsonNode s = submission();
        bundle.set("submission", s.deepCopy());
        ((ObjectNode) bundle.get("decision")).set("inputHash", s.get("inputHash"));
        ObjectNode script = (ObjectNode) bundle.get("script");
        script.set("projectId", s.get("projectId")); script.set("generationTaskId", s.get("taskId"));
        script.set("inputHash", s.get("inputHash"));
        script.put("scriptHash", ScriptContractsV1.scriptHash(script));
        ((ObjectNode) script.get("validationReport")).set("candidateHash", script.get("scriptHash"));
        ObjectNode event = event(3, 100, true);
        ObjectNode refs = event.putObject("resultRefs");
        JsonNode index = bundle.get("materialIndex");
        refs.set("analysis", index.get("analysisRef"));
        refs.putObject("materialIndex").put("artifactId", index.get("indexId").asText())
                .put("revision", index.get("indexVersion").longValue()).put("contentHash", index.get("indexHash").asText());
        refs.putObject("script").put("artifactId", script.get("scriptId").asText())
                .put("revision", script.get("revision").longValue()).put("contentHash", script.get("scriptHash").asText());
        bundle.putArray("events").add(event);
        ScriptContractsV1.parseBundle(bundle.toString());
        return envelope(event, bundle);
    }

    @Test void requestIdDeduplicatesBeforeCatalogIsReadAgainAndConflictsAre409() throws Exception {
        JsonNode first = service.create(1L, input);
        Files.delete(directory.resolve("1").resolve(input.get("assetId").asText() + ".json"));
        assertEquals(first, service.create(1L, input));
        assertEquals(1, client.posts.get());
        ObjectNode changed = input.deepCopy(); changed.put("taskName", "different input");
        assertEquals(409, assertThrows(ScriptTaskService.Problem.class, () -> service.create(1L, changed)).status);
        assertFalse(first.toString().contains("token="));
        assertEquals(client.packet.get("prepared").get("evidence"), service.evidence(task()).get("evidence"));
        assertFalse(service.evidence(task()).has("submission"));
    }

    @Test void concurrentDuplicateIsReservedBeforeNetworkSubmission() throws Exception {
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        client.onSubmit = () -> {
            entered.countDown();
            try { assertTrue(release.await(5, TimeUnit.SECONDS)); } catch (InterruptedException e) { throw new AssertionError(e); }
        };
        var pool = Executors.newSingleThreadExecutor();
        try {
            var pending = pool.submit(() -> service.create(1L, input));
            assertTrue(entered.await(5, TimeUnit.SECONDS));
            JsonNode duplicate = service.create(1L, input);
            assertEquals("ACCEPTING", duplicate.get("status").asText());
            release.countDown();
            assertEquals(duplicate.get("taskId"), pending.get(5, TimeUnit.SECONDS).get("taskId"));
            assertEquals(1, client.posts.get());
        } finally { release.countDown(); pool.shutdownNow(); }
    }

    @Test void atomicCommitRejectsChangedQuoteWithoutAnyPublishedResultOrProgress() throws Exception {
        service.create(1L, input);
        var complete = completed();
        ObjectNode forgedScript = (ObjectNode) complete.get("bundle").get("script");
        ((ObjectNode) forgedScript.get("rows").get(0).get("spokenQuotes").get(0)).put("text", "forged original quote");
        forgedScript.put("scriptHash", ScriptContractsV1.scriptHash(forgedScript));
        ((ObjectNode) forgedScript.get("validationReport")).set("candidateHash", forgedScript.get("scriptHash"));
        ((ObjectNode) complete.get("event").get("resultRefs").get("script")).set("contentHash", forgedScript.get("scriptHash"));
        assertThrows(ScriptTaskService.Problem.class, () -> service.receive(task(), token(), complete));
        assertEquals(0, service.query(task()).get("progress").intValue());
        assertFalse(service.query(task()).get("hasScript").asBoolean());
        assertThrows(ScriptTaskService.Problem.class, () -> service.result(task(), true));
        assertEquals("ACCEPTED", service.receive(task(), token(), completed()));
        assertEquals("NEEDS_REVIEW", service.query(task()).get("status").asText());
        assertEquals(100, service.query(task()).get("progress").intValue());
        assertFalse(service.result(task(), false).toString().contains("token="));
        ScriptContractsV1.parseBundle(service.result(task(), false).toString());
    }

    @Test void duplicateConflictingAndLateCallbacksCannotRewriteHistory() throws Exception {
        service.create(1L, input);
        var progress = envelope(event(1, 40, false), null);
        assertEquals("ACCEPTED", service.receive(task(), token(), progress));
        assertEquals("DUPLICATE", service.receive(task(), token(), progress));
        var conflict = progress.deepCopy(); ((ObjectNode) conflict.get("event")).put("progress", 50);
        assertEquals(409, assertThrows(ScriptTaskService.Problem.class, () -> service.receive(task(), token(), conflict)).status);
        var stale = envelope(event(2, 20, false), null);
        assertEquals("IGNORED_STALE", service.receive(task(), token(), stale));
        var done = completed();
        assertEquals("ACCEPTED", service.receive(task(), token(), done));
        assertEquals("DUPLICATE", service.receive(task(), token(), done));
        String saved = service.result(task(), false).toString();
        assertEquals("IGNORED_TERMINAL", service.receive(task(), token(), envelope(event(4, 90, false), null)));
        assertEquals(saved, service.result(task(), false).toString());
    }

    @Test void wrongTokenAndOldAttemptDoNotAdvanceTask() {
        service.create(1L, input);
        var progress = envelope(event(1, 40, false), null);
        assertEquals(403, assertThrows(ScriptTaskService.Problem.class, () -> service.receive(task(), "wrong", progress)).status);
        ((ObjectNode) progress.get("event")).put("attempt", 2);
        assertEquals("IGNORED_IDENTITY", service.receive(task(), token(), progress));
        assertEquals(0, service.query(task()).get("progress").intValue());
    }

    @Test void otherwiseValidResultCannotSubstituteAnotherAnalysisSnapshot() throws Exception {
        service.create(1L, input);
        var completion = completed();
        ObjectNode bundle = (ObjectNode) completion.get("bundle");
        ObjectNode index = (ObjectNode) bundle.get("materialIndex");
        ((ObjectNode) index.get("analysisRef")).put("contentHash", "sha256:" + "b".repeat(64));
        index.put("indexHash", ScriptContractsV1.indexHash(index));
        ((ObjectNode) bundle.get("decision").get("indexRef")).set("indexHash", index.get("indexHash"));
        ObjectNode script = (ObjectNode) bundle.get("script");
        ((ObjectNode) script.get("indexRef")).set("indexHash", index.get("indexHash"));
        script.put("scriptHash", ScriptContractsV1.scriptHash(script));
        ((ObjectNode) script.get("validationReport")).set("candidateHash", script.get("scriptHash"));
        ObjectNode refs = (ObjectNode) completion.get("event").get("resultRefs");
        refs.set("analysis", index.get("analysisRef"));
        ((ObjectNode) refs.get("materialIndex")).set("contentHash", index.get("indexHash"));
        ((ObjectNode) refs.get("script")).set("contentHash", script.get("scriptHash"));
        ScriptContractsV1.parseBundle(bundle.toString());
        assertEquals("RESULT_EVIDENCE_BINDING_MISMATCH", assertThrows(ScriptTaskService.Problem.class,
                () -> service.receive(task(), token(), completion)).getMessage());
        assertFalse(service.query(task()).get("hasScript").asBoolean());
        assertEquals("ACCEPTED", service.receive(task(), token(), completed()));
    }

    @Test void failedCompletionCannotSaveAnyQualifiedArtifact() throws Exception {
        service.create(1L, input);
        ObjectNode failure = event(2, 50, false);
        failure.put("event", "COMPLETED").put("executionStatus", "FAILED").put("phase", "FAILED");
        failure.putObject("error").put("code", "NO_CANDIDATE").put("message", "No whole unit matched").put("retryable", false);
        var forged = envelope(failure, completed().get("bundle"));
        assertThrows(ScriptTaskService.Problem.class, () -> service.receive(task(), token(), forged));
        assertEquals("ACCEPTED", service.receive(task(), token(), envelope(failure, null)));
        assertEquals("FAILED", service.query(task()).get("status").asText());
        assertTrue(service.result(task(), false).get("script").isNull());
        assertThrows(ScriptTaskService.Problem.class, () -> service.result(task(), true));
    }

    @Test void uncertainAcceptanceNeverCreatesReplacementRunAndCanReconcileLostCallback() throws Exception {
        client.uncertain = true;
        JsonNode first = service.create(1L, input);
        assertEquals("SUBMISSION_UNCERTAIN", first.get("status").asText());
        assertEquals(first, service.create(1L, input));
        var completed = completed();
        ObjectNode remote = json.createObjectNode();
        remote.put("executionStatus", "SUCCESS");
        for (String key : List.of("runId", "taskId", "inputHash")) remote.set(key, submission().get(key));
        remote.putArray("events").add(completed.get("event")); remote.set("bundle", completed.get("bundle"));
        client.remote = remote;
        assertEquals("NEEDS_REVIEW", service.reconcile(task()).get("status").asText());
        assertEquals(1, client.posts.get());
    }

    @Test void missingRemoteRunRemainsUncertainAndIsNeverResubmitted() {
        client.uncertain = true;
        service.create(1L, input);
        assertEquals(503, assertThrows(ScriptTaskService.Problem.class, () -> service.reconcile(task())).status);
        assertEquals("SUBMISSION_UNCERTAIN", service.query(task()).get("status").asText());
        assertEquals(1, client.posts.get());
    }

    @Test void queuedRemoteRunResolvesUncertaintyWithoutResubmission() {
        client.uncertain = true;
        service.create(1L, input);
        ObjectNode remote = json.createObjectNode().put("executionStatus", "PENDING");
        for (String key : List.of("runId", "taskId", "inputHash")) remote.set(key, submission().get(key));
        remote.putArray("events"); remote.putNull("bundle"); client.remote = remote;
        assertEquals("RUNNING", service.reconcile(task()).get("status").asText());
        assertEquals("ACCEPTED", service.query(task()).get("acceptance").asText());
        assertEquals(1, client.posts.get());
    }

    @Test void catalogRejectsForeignProjectAndSymlinksEscapingItsRoot() throws Exception {
        var fixture = json.readTree(Files.readString(docs.resolve("offline-id-director.input.json")));
        Path root = directory.resolve("catalog"); Files.createDirectories(root.resolve("1"));
        var catalog = new PreparedScriptCatalog(root.toString(), json);
        Path entry = root.resolve("1/foreign.json"); Files.writeString(entry, fixture.toString());
        assertEquals(422, assertThrows(ScriptTaskService.Problem.class, () -> catalog.load("1", "foreign")).status);
        Path outside = directory.resolve("outside.json"); Files.writeString(outside, fixture.toString());
        Files.createSymbolicLink(root.resolve("1/escape.json"), outside);
        assertEquals(422, assertThrows(ScriptTaskService.Problem.class, () -> catalog.load("1", "escape")).status);
        assertEquals(422, assertThrows(ScriptTaskService.Problem.class, () -> catalog.load("1", "../escape")).status);
    }

    @Test void malformed202IsUncertainWhileDefiniteRejectionIsFailed() {
        client.malformed = true;
        assertEquals("SUBMISSION_UNCERTAIN", service.create(1L, input).get("status").asText());
        client.malformed = false; client.rejected = true;
        ((ObjectNode) input).put("requestId", "request_rejected");
        assertEquals("FAILED", service.create(1L, input).get("status").asText());
        assertFalse(service.query(task()).get("hasScript").asBoolean());
    }

    @Test void callbackBeforeSubmissionResponseWinsOverTransportUncertainty() {
        client.uncertain = true;
        client.onSubmit = () -> {
            try { service.receive(task(), token(), completed()); } catch (Exception e) { throw new AssertionError(e); }
        };
        var state = service.create(1L, input);
        assertEquals("NEEDS_REVIEW", state.get("status").asText());
        assertEquals("ACCEPTED", state.get("acceptance").asText());
        assertNull(state.get("error").textValue());
    }

    @Test void boundedListKeepsTaskResultsSeparateAndNewestFirst() throws Exception {
        service.create(1L, input);
        String firstTask = task(), firstToken = token();
        var firstComplete = completed();
        ((ObjectNode) input).put("requestId", "request_next");
        JsonNode second = service.create(1L, input);
        service.receive(firstTask, firstToken, firstComplete);
        assertEquals("RUNNING", service.query(second.get("taskId").asText()).get("status").asText());
        var page = service.list(1L, 0, 1);
        assertEquals(2, page.get("total").intValue());
        assertEquals(second.get("taskId"), page.get("items").get(0).get("taskId"));
        assertEquals(firstTask, service.list(1L, 1, 1).get("items").get(0).get("taskId").asText());
        assertEquals(422, assertThrows(ScriptTaskService.Problem.class, () -> service.list(1L, 0, 101)).status);
    }

    @Test void projectOwnershipMissingCatalogAndCapacityFailClosed() {
        assertEquals(404, assertThrows(ScriptTaskService.Problem.class, () -> service.create(2L, input)).status);
        ObjectNode wrong = input.deepCopy(); wrong.put("assetId", "missing");
        assertEquals(409, assertThrows(ScriptTaskService.Problem.class, () -> service.create(1L, wrong)).status);
        service = new ScriptTaskService(new PreparedScriptCatalog(directory.toString(), json), projects, client, json,
                "http://127.0.0.1:8080", 1);
        service.create(1L, input);
        ((ObjectNode) input).put("requestId", "request_over_capacity");
        assertEquals(503, assertThrows(ScriptTaskService.Problem.class, () -> service.create(1L, input)).status);
        assertEquals(1, client.posts.get());
    }

    @Test void invalidTimeAndDuplicateJsonKeysAreRejected() {
        ObjectNode changed = input.deepCopy();
        ((ObjectNode) changed.get("target")).put("desiredDurationMs", 99_000_000);
        assertThrows(ScriptTaskService.Problem.class, () -> service.create(1L, changed));
        assertEquals(0, client.posts.get());
        assertThrows(ScriptTaskService.Problem.class, () -> service.read("{\"x\":1,\"x\":2}"));
        assertThrows(ScriptTaskService.Problem.class, () -> service.read("{} {}"));
    }
}
