/** B1 analysis evidence. Time ranges use integer milliseconds on the source asset. */

export type EvidenceId = string;
export type SourceMode = 'REAL' | 'SIMULATED' | 'MIXED' | 'NO_SPEECH' | 'UNAVAILABLE';

export interface SourceProvenance {
  mode: SourceMode;
  provider?: string | null;
  model?: string | null;
  reason?: string | null;
}

export type AnalysisType = 'TUTORIAL_INTERVIEW' | 'VLOG_DOCUMENTARY' | 'FAST_SHORT_VIDEO';

export interface AnalysisProfile {
  profileVersion: string;
  configVersion: string;
  requestedType: AnalysisType | 'AUTO';
  effectiveType: AnalysisType;
  detectedPace: 'SLOW' | 'NORMAL' | 'FAST';
  shotCountPerMinute: number;
  novelShotCountPerMinute: number;
  confidence: number;
  adjustmentReason: string;
  windowTargetMs: number;
  frameBudget: number;
  vlmBatchSize: number;
  vlmConcurrency: number;
}

export interface AnalysisWindow {
  windowId: EvidenceId;
  assetHash: string;
  startMs: number;
  endMs: number;
  contextStartMs: number;
  contextEndMs: number;
  sceneIds: EvidenceId[];
  selectedFrameIds: EvidenceId[];
  profileVersion: string;
  plannerVersion: string;
}

export interface FrameObservation {
  frameId: EvidenceId;
  windowId: EvidenceId;
  sceneId: EvidenceId;
  timestampMs: number;
  description: string;
  tags: string[];
  importance: number;
  source: SourceProvenance;
}

export interface TranscriptSegmentV1 {
  transcriptId: EvidenceId;
  startMs: number;
  endMs: number;
  text: string;
  timingQuality: 'COARSE_BLOCK' | 'SENTENCE' | 'WORD' | 'MANUAL';
  source: SourceProvenance;
}

export interface WindowCoverage {
  selectedFrames: number;
  successfulFrames: number;
  asrOverlapMs: number;
  visualComplete: boolean;
  audioComplete: boolean;
}

export interface WindowAnalysis {
  windowId: EvidenceId;
  startMs: number;
  endMs: number;
  frameObservationRefs: EvidenceId[];
  transcriptRefs: EvidenceId[];
  summary: string;
  topics: string[];
  events: string[];
  coverage: WindowCoverage;
  provenance: Record<string, SourceProvenance>;
}

export interface GlobalFinding {
  findingId: EvidenceId;
  kind: 'TOPIC' | 'CHAPTER' | 'ARGUMENT' | 'HIGHLIGHT' | 'REDUNDANCY' | 'DEPENDENCY';
  startMs: number;
  endMs: number;
  text: string;
  evidenceRefs: EvidenceId[];
}

export interface GlobalAnalysis {
  windowRefs: EvidenceId[];
  summary: string;
  topics: string[];
  findings: GlobalFinding[];
  provenance: Record<string, SourceProvenance>;
}

export interface FailureRange {
  startMs: number;
  endMs: number;
  phase: 'PROBE' | 'SCENE' | 'FRAMES' | 'ASR' | 'VLM' | 'FUSION' | 'GLOBAL';
  code: string;
  reason: string;
}

export interface GlobalCoverage {
  totalWindows: number;
  completeWindows: number;
  coveredMs: number;
  failedWindowIds: EvidenceId[];
}

/** Separate from the legacy AnalysisReport and Plan 1.0 contracts. */
export interface AnalysisEvidenceV1 {
  schemaVersion: '1.0';
  assetId: EvidenceId;
  assetHash: string;
  durationMs: number;
  configVersion: string;
  profile: AnalysisProfile;
  windows: AnalysisWindow[];
  frameObservations: FrameObservation[];
  transcripts: TranscriptSegmentV1[];
  windowAnalyses: WindowAnalysis[];
  globalAnalysis: GlobalAnalysis;
  coverage: GlobalCoverage;
  failureRanges: FailureRange[];
  executionStatus: 'SUCCESS';
  analysisOutcome: 'COMPLETE' | 'PARTIAL';
  reviewStatus: 'READY' | 'NEEDS_REVIEW';
  provenance: Record<string, SourceProvenance>;
}
