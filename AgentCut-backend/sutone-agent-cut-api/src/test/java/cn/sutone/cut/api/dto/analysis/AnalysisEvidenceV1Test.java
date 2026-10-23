package cn.sutone.cut.api.dto.analysis;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class AnalysisEvidenceV1Test {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Path FIXTURES = Path.of("..", "..", "docs", "contracts");

    private String fixture(String name) throws Exception {
        return Files.readString(FIXTURES.resolve("analysis-evidence-v1." + name + ".json"));
    }

    @Test
    void completeFixtureKeepsGlobalTimeAndCrossWindowTranscript() throws Exception {
        AnalysisEvidenceV1 result = AnalysisEvidenceV1.parseStrict(fixture("valid"));

        assertEquals("READY", result.reviewStatus());
        assertEquals(result.windows().get(0).endMs(), result.windows().get(1).startMs());
        assertEquals("asr_001", result.windowAnalyses().get(0).transcriptRefs().get(0));
        assertEquals("asr_001", result.windowAnalyses().get(1).transcriptRefs().get(0));
        AnalysisEvidenceV1.parseStrict(MAPPER.writeValueAsString(result));
    }

    @Test
    void partialFixturePreservesSuccessfulEvidenceAndNeedsReview() throws Exception {
        AnalysisEvidenceV1 result = AnalysisEvidenceV1.parseStrict(fixture("needs-review"));

        assertEquals("PARTIAL", result.analysisOutcome());
        assertEquals("NEEDS_REVIEW", result.reviewStatus());
        assertEquals("window_002", result.coverage().failedWindowIds().get(0));
        assertEquals("frame_w001_001", result.frameObservations().get(0).frameId());
    }

    @Test
    void noSpeechFixtureIsCompleteWithoutTranscript() throws Exception {
        AnalysisEvidenceV1 result = AnalysisEvidenceV1.parseStrict(fixture("no-speech"));

        assertEquals("COMPLETE", result.analysisOutcome());
        assertEquals("READY", result.reviewStatus());
        assertEquals("NO_SPEECH", result.provenance().get("asr").mode());
        assertEquals(0, result.transcripts().size());
    }

    @Test
    void mixedFixtureRequiresReviewDespiteFullCoverage() throws Exception {
        AnalysisEvidenceV1 result = AnalysisEvidenceV1.parseStrict(fixture("mixed"));

        assertEquals("COMPLETE", result.analysisOutcome());
        assertEquals("NEEDS_REVIEW", result.reviewStatus());
        assertEquals(2, result.coverage().completeWindows());
        assertEquals("MIXED", result.provenance().get("vlm").mode());
    }

    @Test
    void completeAudioWithoutTranscriptRequiresNoSpeechProvenance() throws Exception {
        ObjectNode document = (ObjectNode) MAPPER.readTree(fixture("no-speech"));
        ObjectNode firstAnalysis = (ObjectNode) document.withArray("windowAnalyses").get(0);
        ((ObjectNode) firstAnalysis.get("provenance").get("asr")).put("mode", "REAL");

        assertThrows(IllegalArgumentException.class,
                () -> AnalysisEvidenceV1.parseStrict(MAPPER.writeValueAsString(document)));
    }

    @Test
    void mixedEvidenceCannotBeReady() throws Exception {
        ObjectNode document = (ObjectNode) MAPPER.readTree(fixture("mixed"));
        document.put("reviewStatus", "READY");

        assertThrows(IllegalArgumentException.class,
                () -> AnalysisEvidenceV1.parseStrict(MAPPER.writeValueAsString(document)));
    }

    @Test
    void modelSuppliedFreeTimeIsRejected() throws Exception {
        assertThrows(JsonProcessingException.class,
                () -> AnalysisEvidenceV1.parseStrict(fixture("invalid-extra-time")));
    }

    @Test
    void floatingTimestampIsRejected() throws Exception {
        ObjectNode document = (ObjectNode) MAPPER.readTree(fixture("valid"));
        ((ObjectNode) document.withArray("frameObservations").get(0)).put("timestampMs", 20000.5);

        assertThrows(JsonProcessingException.class,
                () -> AnalysisEvidenceV1.parseStrict(MAPPER.writeValueAsString(document)));
    }

    @Test
    void manualProfileOverrideAndWindowGapAreRejected() throws Exception {
        ObjectNode document = (ObjectNode) MAPPER.readTree(fixture("valid"));
        JsonNode profile = document.get("profile");
        ((ObjectNode) profile).put("effectiveType", "VLOG_DOCUMENTARY");
        assertThrows(IllegalArgumentException.class,
                () -> AnalysisEvidenceV1.parseStrict(MAPPER.writeValueAsString(document)));

        ((ObjectNode) profile).put("effectiveType", "TUTORIAL_INTERVIEW");
        ((ObjectNode) document.withArray("windows").get(1)).put("startMs", 61000);
        assertThrows(IllegalArgumentException.class,
                () -> AnalysisEvidenceV1.parseStrict(MAPPER.writeValueAsString(document)));
    }

    @Test
    void partialEvidenceCannotBeReady() throws Exception {
        ObjectNode document = (ObjectNode) MAPPER.readTree(fixture("needs-review"));
        document.put("reviewStatus", "READY");

        assertThrows(IllegalArgumentException.class,
                () -> AnalysisEvidenceV1.parseStrict(MAPPER.writeValueAsString(document)));
    }

    @Test
    void coverageOrderUsesWindowOrderEvenIfAnalysesAreShuffled() throws Exception {
        ObjectNode document = (ObjectNode) MAPPER.readTree(fixture("needs-review"));
        ArrayNode analyses = document.withArray("windowAnalyses");
        JsonNode first = analyses.get(0);
        analyses.set(0, analyses.get(1));
        analyses.set(1, first);

        AnalysisEvidenceV1 result = AnalysisEvidenceV1.parseStrict(MAPPER.writeValueAsString(document));
        assertEquals("window_002", result.coverage().failedWindowIds().get(0));
    }

    @Test
    void missingSummaryIsRejected() throws Exception {
        ObjectNode document = (ObjectNode) MAPPER.readTree(fixture("valid"));
        ((ObjectNode) document.withArray("windowAnalyses").get(0)).remove("summary");

        assertThrows(IllegalArgumentException.class,
                () -> AnalysisEvidenceV1.parseStrict(MAPPER.writeValueAsString(document)));
    }
}
