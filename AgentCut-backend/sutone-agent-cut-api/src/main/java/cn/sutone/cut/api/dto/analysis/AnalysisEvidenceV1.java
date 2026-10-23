package cn.sutone.cut.api.dto.analysis;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Additive B1 analysis-evidence contract. All times use global integer milliseconds.
 * This DTO is not wired into the legacy AnalysisReport/Plan 1.0 endpoints.
 */
public record AnalysisEvidenceV1(
        String schemaVersion,
        String assetId,
        String assetHash,
        long durationMs,
        String configVersion,
        AnalysisProfile profile,
        List<AnalysisWindow> windows,
        List<FrameObservation> frameObservations,
        List<TranscriptSegment> transcripts,
        List<WindowAnalysis> windowAnalyses,
        GlobalAnalysis globalAnalysis,
        GlobalCoverage coverage,
        List<FailureRange> failureRanges,
        String executionStatus,
        String analysisOutcome,
        String reviewStatus,
        Map<String, SourceProvenance> provenance) {

    private static final ObjectMapper CONTRACT_MAPPER = new ObjectMapper()
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .enable(DeserializationFeature.FAIL_ON_NULL_FOR_PRIMITIVES)
            .disable(DeserializationFeature.ACCEPT_FLOAT_AS_INT);

    private static final Set<String> SOURCE_MODES = Set.of(
            "REAL", "SIMULATED", "MIXED", "NO_SPEECH", "UNAVAILABLE");

    public static AnalysisEvidenceV1 parseStrict(String json) throws JsonProcessingException {
        AnalysisEvidenceV1 result = CONTRACT_MAPPER.readValue(json, AnalysisEvidenceV1.class);
        result.validate();
        return result;
    }

    public void validate() {
        require("1.0".equals(schemaVersion), "unsupported schemaVersion");
        requireId(assetId);
        requireText(assetHash, "assetHash");
        require(durationMs > 0, "durationMs must be positive");
        requireText(configVersion, "configVersion");
        require(profile != null, "profile is required");
        require(windows != null && !windows.isEmpty(), "windows are required");
        require(frameObservations != null && transcripts != null && windowAnalyses != null,
                "evidence lists are required");
        require(globalAnalysis != null && coverage != null && failureRanges != null && provenance != null,
                "analysis, coverage, failures, and provenance are required");
        require("SUCCESS".equals(executionStatus), "evidence document requires SUCCESS execution");
        require(allowed(Set.of("COMPLETE", "PARTIAL"), analysisOutcome), "invalid analysisOutcome");
        require(allowed(Set.of("READY", "NEEDS_REVIEW"), reviewStatus), "invalid reviewStatus");

        profile.validate();
        require(configVersion.equals(profile.configVersion()), "profile configVersion mismatch");

        Map<String, AnalysisWindow> byWindow = new HashMap<>();
        List<String> windowIds = new ArrayList<>();
        Set<String> selectedFrameIds = new HashSet<>();
        long nextStart = 0;
        for (AnalysisWindow window : windows) {
            require(window != null, "null window");
            requireId(window.windowId());
            require(byWindow.putIfAbsent(window.windowId(), window) == null, "duplicate windowId");
            windowIds.add(window.windowId());
            require(window.startMs() == nextStart && window.startMs() < window.endMs(),
                    "primary windows must be contiguous and nonempty");
            require(0 <= window.contextStartMs() && window.contextStartMs() <= window.startMs()
                    && window.endMs() <= window.contextEndMs()
                    && window.contextEndMs() <= durationMs, "invalid window context");
            require(assetHash.equals(window.assetHash()), "window assetHash mismatch");
            require(profile.profileVersion().equals(window.profileVersion()), "window profileVersion mismatch");
            requireText(window.plannerVersion(), "plannerVersion");
            require(window.sceneIds() != null && window.selectedFrameIds() != null, "window IDs missing");
            requireUniqueIds(window.sceneIds(), "duplicate sceneId in window");
            requireUniqueIds(window.selectedFrameIds(), "duplicate selectedFrameId in window");
            for (String frameId : window.selectedFrameIds()) {
                require(selectedFrameIds.add(frameId), "selected frameId belongs to more than one window");
            }
            nextStart = window.endMs();
        }
        require(nextStart == durationMs, "primary windows must cover the whole asset");

        Map<String, FrameObservation> frames = new HashMap<>();
        for (FrameObservation frame : frameObservations) {
            require(frame != null, "null frame observation");
            requireId(frame.frameId());
            require(frames.putIfAbsent(frame.frameId(), frame) == null, "duplicate frameId");
            AnalysisWindow window = byWindow.get(frame.windowId());
            require(window != null && window.selectedFrameIds().contains(frame.frameId()),
                    "frameId is not selected by its window");
            require(window.sceneIds().contains(frame.sceneId()), "unknown sceneId for frame");
            require(window.contextStartMs() <= frame.timestampMs()
                    && frame.timestampMs() < window.contextEndMs(), "frame timestamp outside window context");
            require(frame.importance() >= 0 && frame.importance() <= 1, "frame importance out of range");
            require(frame.description() != null, "frame description missing");
            requireStrings(frame.tags(), "frame tags");
            validateSource(frame.source());
        }

        Map<String, TranscriptSegment> transcriptById = new HashMap<>();
        for (TranscriptSegment transcript : transcripts) {
            require(transcript != null, "null transcript");
            requireId(transcript.transcriptId());
            require(transcriptById.putIfAbsent(transcript.transcriptId(), transcript) == null,
                    "duplicate transcriptId");
            require(0 <= transcript.startMs() && transcript.startMs() < transcript.endMs()
                    && transcript.endMs() <= durationMs, "invalid transcript range");
            require(transcript.text() != null, "transcript text missing");
            require(allowed(Set.of("COARSE_BLOCK", "SENTENCE", "WORD", "MANUAL"),
                    transcript.timingQuality()), "invalid timingQuality");
            validateSource(transcript.source());
        }

        Map<String, WindowAnalysis> analyses = new HashMap<>();
        Set<String> referencedFrames = new HashSet<>();
        Set<String> referencedTranscripts = new HashSet<>();
        Map<String, Boolean> completeByWindow = new HashMap<>();
        for (WindowAnalysis analysis : windowAnalyses) {
            require(analysis != null, "null WindowAnalysis");
            requireId(analysis.windowId());
            require(analyses.putIfAbsent(analysis.windowId(), analysis) == null, "duplicate WindowAnalysis");
            AnalysisWindow window = byWindow.get(analysis.windowId());
            require(window != null, "WindowAnalysis references unknown window");
            require(analysis.startMs() == window.startMs() && analysis.endMs() == window.endMs(),
                    "WindowAnalysis range differs from window");
            require(analysis.frameObservationRefs() != null && analysis.transcriptRefs() != null
                    && analysis.coverage() != null && analysis.provenance() != null,
                    "WindowAnalysis references, coverage, or provenance missing");
            require(analysis.summary() != null, "WindowAnalysis summary missing");
            requireStrings(analysis.topics(), "WindowAnalysis topics");
            requireStrings(analysis.events(), "WindowAnalysis events");
            requireUniqueIds(analysis.frameObservationRefs(), "duplicate frame observation reference");
            requireUniqueIds(analysis.transcriptRefs(), "duplicate transcript reference");
            for (String frameId : analysis.frameObservationRefs()) {
                FrameObservation frame = frames.get(frameId);
                require(frame != null && analysis.windowId().equals(frame.windowId()),
                        "unknown or foreign frame observation reference");
                referencedFrames.add(frameId);
            }
            List<long[]> overlaps = new ArrayList<>();
            for (String transcriptId : analysis.transcriptRefs()) {
                TranscriptSegment transcript = transcriptById.get(transcriptId);
                require(transcript != null && transcript.startMs() < window.endMs()
                        && transcript.endMs() > window.startMs(),
                        "transcript reference does not overlap window");
                referencedTranscripts.add(transcriptId);
                overlaps.add(new long[]{Math.max(window.startMs(), transcript.startMs()),
                        Math.min(window.endMs(), transcript.endMs())});
            }
            WindowCoverage count = analysis.coverage();
            require(count.selectedFrames() == window.selectedFrameIds().size(), "selected frame count mismatch");
            require(count.successfulFrames() == analysis.frameObservationRefs().size(),
                    "successful frame count mismatch");
            require(count.successfulFrames() <= count.selectedFrames(), "successful frames exceed selected");
            require(count.visualComplete() == (count.selectedFrames() > 0
                    && count.successfulFrames() == count.selectedFrames()), "visualComplete mismatch");
            require(count.asrOverlapMs() == unionMs(overlaps, window.startMs()), "ASR overlap mismatch");
            analysis.provenance().values().forEach(AnalysisEvidenceV1::validateSource);
            if (count.audioComplete() && analysis.transcriptRefs().isEmpty()) {
                SourceProvenance asr = analysis.provenance().get("asr");
                require(asr != null && "NO_SPEECH".equals(asr.mode()),
                        "audioComplete without transcript requires NO_SPEECH provenance");
            }
            completeByWindow.put(window.windowId(), count.visualComplete() && count.audioComplete());
        }
        require(analyses.keySet().equals(byWindow.keySet()), "one WindowAnalysis is required per window");
        require(referencedFrames.equals(frames.keySet()), "unreferenced frame observation");
        require(referencedTranscripts.equals(transcriptById.keySet()), "unreferenced transcript");
        List<String> failedWindowIds = new ArrayList<>();
        for (String windowId : windowIds) {
            if (!completeByWindow.get(windowId)) {
                failedWindowIds.add(windowId);
            }
        }
        int completeWindows = windowIds.size() - failedWindowIds.size();

        require(globalAnalysis.windowRefs() != null && globalAnalysis.windowRefs().equals(windowIds),
                "GlobalAnalysis must reference all windows in order");
        require(globalAnalysis.findings() != null && globalAnalysis.provenance() != null,
                "GlobalAnalysis findings and provenance are required");
        require(globalAnalysis.summary() != null, "GlobalAnalysis summary missing");
        requireStrings(globalAnalysis.topics(), "GlobalAnalysis topics");
        Set<String> findingIds = new HashSet<>();
        for (GlobalFinding finding : globalAnalysis.findings()) {
            require(finding != null, "null finding");
            requireId(finding.findingId());
            require(findingIds.add(finding.findingId()), "duplicate findingId");
            require(allowed(Set.of("TOPIC", "CHAPTER", "ARGUMENT", "HIGHLIGHT", "REDUNDANCY", "DEPENDENCY"),
                    finding.kind()), "invalid finding kind");
            require(0 <= finding.startMs() && finding.startMs() < finding.endMs()
                    && finding.endMs() <= durationMs, "invalid finding range");
            requireText(finding.text(), "finding text");
            require(finding.evidenceRefs() != null && !finding.evidenceRefs().isEmpty(),
                    "finding requires evidence");
            for (String ref : finding.evidenceRefs()) {
                boolean supported;
                if (frames.containsKey(ref)) {
                    long time = frames.get(ref).timestampMs();
                    supported = finding.startMs() <= time && time < finding.endMs();
                } else if (transcriptById.containsKey(ref)) {
                    TranscriptSegment transcript = transcriptById.get(ref);
                    supported = transcript.startMs() < finding.endMs()
                            && transcript.endMs() > finding.startMs();
                } else if (byWindow.containsKey(ref)) {
                    AnalysisWindow window = byWindow.get(ref);
                    supported = window.startMs() < finding.endMs() && window.endMs() > finding.startMs();
                } else {
                    supported = false;
                }
                require(supported, "finding evidence does not overlap its range");
            }
        }
        globalAnalysis.provenance().values().forEach(AnalysisEvidenceV1::validateSource);

        require(coverage.totalWindows() == windows.size() && coverage.completeWindows() == completeWindows
                && coverage.coveredMs() == durationMs && failedWindowIds.equals(coverage.failedWindowIds()),
                "global coverage mismatch");
        for (FailureRange failure : failureRanges) {
            require(failure != null && 0 <= failure.startMs() && failure.startMs() < failure.endMs()
                    && failure.endMs() <= durationMs, "invalid failure range");
            require(allowed(Set.of("PROBE", "SCENE", "FRAMES", "ASR", "VLM", "FUSION", "GLOBAL"),
                    failure.phase()), "invalid failure phase");
            requireText(failure.code(), "failure code");
            require(failure.reason() != null, "failure reason missing");
        }
        require(!"COMPLETE".equals(analysisOutcome) || (failedWindowIds.isEmpty() && failureRanges.isEmpty()),
                "COMPLETE contains missing evidence");
        require(!"PARTIAL".equals(analysisOutcome) || (!failedWindowIds.isEmpty() || !failureRanges.isEmpty()),
                "PARTIAL has no recorded gap");
        require(!"PARTIAL".equals(analysisOutcome) || "NEEDS_REVIEW".equals(reviewStatus),
                "partial analysis requires review");
        provenance.values().forEach(AnalysisEvidenceV1::validateSource);
        if ("READY".equals(reviewStatus)) {
            List<SourceProvenance> sources = new ArrayList<>(provenance.values());
            frameObservations.forEach(frame -> sources.add(frame.source()));
            transcripts.forEach(transcript -> sources.add(transcript.source()));
            windowAnalyses.forEach(analysis -> sources.addAll(analysis.provenance().values()));
            sources.addAll(globalAnalysis.provenance().values());
            require(sources.stream().noneMatch(source -> allowed(Set.of("SIMULATED", "MIXED", "UNAVAILABLE"),
                    source.mode())), "READY cannot rely on simulated or missing evidence");
        }
    }

    private static long unionMs(List<long[]> overlaps, long startMs) {
        overlaps.sort(Comparator.comparingLong(item -> item[0]));
        long total = 0;
        long lastEnd = startMs;
        for (long[] overlap : overlaps) {
            total += Math.max(0, overlap[1] - Math.max(overlap[0], lastEnd));
            lastEnd = Math.max(lastEnd, overlap[1]);
        }
        return total;
    }

    private static void validateSource(SourceProvenance source) {
        require(source != null && allowed(SOURCE_MODES, source.mode()), "invalid source provenance");
    }

    private static boolean allowed(Set<String> options, String value) {
        return value != null && options.contains(value);
    }

    private static void requireStrings(List<String> values, String field) {
        require(values != null && values.stream().allMatch(value -> value != null), field + " is required");
    }

    private static void requireUniqueIds(List<String> ids, String message) {
        Set<String> seen = new HashSet<>();
        for (String id : ids) {
            requireId(id);
            require(seen.add(id), message);
        }
    }

    private static void requireId(String value) {
        require(value != null && value.matches("[A-Za-z0-9_-]+"), "invalid ID");
    }

    private static void requireText(String value, String field) {
        require(value != null && !value.isBlank(), field + " is required");
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new IllegalArgumentException(message);
        }
    }

    public record SourceProvenance(String mode, String provider, String model, String reason) {}

    public record AnalysisProfile(String profileVersion, String configVersion, String requestedType,
                                  String effectiveType, String detectedPace, double shotCountPerMinute,
                                  double novelShotCountPerMinute, double confidence, String adjustmentReason,
                                  long windowTargetMs, int frameBudget, int vlmBatchSize, int vlmConcurrency) {
        void validate() {
            requireText(profileVersion, "profileVersion");
            requireText(configVersion, "configVersion");
            require(allowed(Set.of("AUTO", "TUTORIAL_INTERVIEW", "VLOG_DOCUMENTARY", "FAST_SHORT_VIDEO"),
                    requestedType), "invalid requestedType");
            require(allowed(Set.of("TUTORIAL_INTERVIEW", "VLOG_DOCUMENTARY", "FAST_SHORT_VIDEO"),
                    effectiveType), "invalid effectiveType");
            require("AUTO".equals(requestedType) || requestedType.equals(effectiveType),
                    "manual requestedType cannot be overridden");
            require(allowed(Set.of("SLOW", "NORMAL", "FAST"), detectedPace), "invalid detectedPace");
            require(shotCountPerMinute >= 0 && novelShotCountPerMinute >= 0
                    && novelShotCountPerMinute <= shotCountPerMinute, "invalid shot density");
            require(confidence >= 0 && confidence <= 1, "invalid confidence");
            require(adjustmentReason != null, "adjustmentReason is required");
            require(windowTargetMs > 0 && frameBudget >= 0 && vlmBatchSize > 0 && vlmConcurrency > 0,
                    "invalid analysis budget");
        }
    }

    public record AnalysisWindow(String windowId, String assetHash, long startMs, long endMs,
                                 long contextStartMs, long contextEndMs, List<String> sceneIds,
                                 List<String> selectedFrameIds, String profileVersion, String plannerVersion) {}

    public record FrameObservation(String frameId, String windowId, String sceneId, long timestampMs,
                                   String description, List<String> tags, double importance,
                                   SourceProvenance source) {}

    public record TranscriptSegment(String transcriptId, long startMs, long endMs, String text,
                                    String timingQuality, SourceProvenance source) {}

    public record WindowCoverage(int selectedFrames, int successfulFrames, long asrOverlapMs,
                                 boolean visualComplete, boolean audioComplete) {}

    public record WindowAnalysis(String windowId, long startMs, long endMs,
                                 List<String> frameObservationRefs, List<String> transcriptRefs,
                                 String summary, List<String> topics, List<String> events,
                                 WindowCoverage coverage, Map<String, SourceProvenance> provenance) {}

    public record GlobalFinding(String findingId, String kind, long startMs, long endMs,
                                String text, List<String> evidenceRefs) {}

    public record GlobalAnalysis(List<String> windowRefs, String summary, List<String> topics,
                                 List<GlobalFinding> findings, Map<String, SourceProvenance> provenance) {}

    public record FailureRange(long startMs, long endMs, String phase, String code, String reason) {}

    public record GlobalCoverage(int totalWindows, int completeWindows, long coveredMs,
                                 List<String> failedWindowIds) {}
}
