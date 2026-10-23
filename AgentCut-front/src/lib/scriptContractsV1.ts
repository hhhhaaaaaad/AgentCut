import Ajv2020 from 'ajv/dist/2020.js';
import schema from '../../../docs/contracts/script-contract-bundle-v1.schema.json' with { type: 'json' };
import type { ScriptContractBundleV1, MaterialIndexV1, DirectorDecisionV1, EditingScriptV1, TaskSubmissionV1, TaskEventV1 } from '../types/scriptContractsV1';

const shape = new Ajv2020({ allErrors: true }).compile<ScriptContractBundleV1>(schema);
function requireContract(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}
export function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonicalJson).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => JSON.stringify(key) + ':' + canonicalJson(item)).join(',') + '}';
  return JSON.stringify(value);
}
const equal = (left: unknown, right: unknown) => canonicalJson(left) === canonicalJson(right);
const unique = (values: unknown[], field: string) => requireContract(new Set(values).size === values.length, 'duplicate ' + field);
const without = (value: object, keys: string[]) => Object.fromEntries(Object.entries(value).filter(([key]) => !keys.includes(key)));
export async function canonicalHash(value: unknown): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonicalJson(value)));
  return 'sha256:' + [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('');
}
export const indexHash = (index: MaterialIndexV1) => canonicalHash(without(index, ['indexHash']));
export const scriptHash = (script: EditingScriptV1) => canonicalHash(without(script, ['scriptHash', 'validationReport', 'quality', 'reviewStatus']));
export const inputHash = (submission: TaskSubmissionV1) => canonicalHash({
  projectId: submission.projectId, assetRef: submission.assetRef, configVersion: submission.configVersion,
  input: without(submission.input, ['requestId']),
});

function validRange(range: { startMs: number; endMs: number }, duration: number) {
  requireContract(range.startMs < range.endMs && range.endMs <= duration, 'invalid source/output range');
}
async function validateIndex(index: MaterialIndexV1) {
  requireContract(index.indexHash === await indexHash(index), 'indexHash mismatch');
  unique(index.scenes.map((scene) => scene.sceneId), 'sceneId');
  unique(index.observations.map((frame) => frame.frameId), 'frameId');
  unique(index.transcripts.map((transcript) => transcript.transcriptId), 'transcriptId');
  unique(index.units.map((unit) => unit.unitId), 'unitId');
  const scenes = new Map(index.scenes.map((scene) => [scene.sceneId, scene]));
  const frames = new Map(index.observations.map((frame) => [frame.frameId, frame]));
  const units = new Map(index.units.map((unit) => [unit.unitId, unit]));
  const transcripts = new Map(index.transcripts.map((transcript) => [transcript.transcriptId, transcript]));
  for (const transcript of index.transcripts) {
    validRange(transcript.sourceRange, index.assetRef.durationMs);
    requireContract(['REAL', 'SIMULATED', 'MIXED'].includes(transcript.source.mode), 'transcript requires attributed speech');
  }
  let nextStart = 0;
  for (const scene of index.scenes) {
    validRange(scene.sourceRange, index.assetRef.durationMs);
    requireContract(scene.sourceRange.startMs === nextStart, 'scene index must cover the whole asset');
    nextStart = scene.sourceRange.endMs;
  }
  requireContract(nextStart === index.assetRef.durationMs, 'scene index must cover the whole asset');
  for (const frame of index.observations) {
    const scene = scenes.get(frame.sceneId);
    requireContract(scene && scene.sourceRange.startMs <= frame.timestampMs && frame.timestampMs < scene.sourceRange.endMs, 'frame must belong to its scene');
  }
  let previousEnd = 0;
  for (const unit of index.units) {
    validRange(unit.sourceRange, index.assetRef.durationMs);
    requireContract(unit.sourceRange.startMs >= previousEnd, 'units must be ordered and nonoverlapping');
    previousEnd = unit.sourceRange.endMs;
    for (const values of [unit.transcriptRefs, unit.sceneRefs, unit.frameRefs]) unique(values, 'unit reference');
    requireContract(unit.sceneRefs.every((ref) => {
      const scene = scenes.get(ref);
      return scene && scene.sourceRange.startMs < unit.sourceRange.endMs && unit.sourceRange.startMs < scene.sourceRange.endMs;
    }), 'unit scene reference must overlap');
    requireContract(unit.frameRefs.every((ref) => {
      const frame = frames.get(ref);
      return frame && unit.sceneRefs.includes(frame.sceneId) && unit.sourceRange.startMs <= frame.timestampMs && frame.timestampMs < unit.sourceRange.endMs;
    }), 'unit frame reference is foreign');
    if (unit.kind === 'SPEECH') {
      requireContract(unit.originalText.trim() && unit.transcriptRefs.length && unit.timingQuality !== 'NONE' && ['REAL', 'SIMULATED', 'MIXED'].includes(unit.asrSource.mode), 'speech requires attributed transcript');
      requireContract(unit.transcriptRefs.every((ref) => transcripts.has(ref)), 'unknown transcript reference');
      const records = unit.transcriptRefs.map((ref) => transcripts.get(ref)!);
      requireContract(unit.sourceRange.startMs === records[0].sourceRange.startMs && unit.sourceRange.endMs === records[records.length - 1].sourceRange.endMs && records.every((record, i) => i === 0 || records[i - 1].sourceRange.endMs === record.sourceRange.startMs), 'unit must preserve whole contiguous transcript records');
      requireContract(unit.originalText === records.map((record) => record.text).join(''), 'unit text differs from transcript evidence');
      const ranks = { NONE: 0, COARSE_BLOCK: 1, SENTENCE: 2, WORD: 3, MANUAL: 4 };
      requireContract(ranks[unit.timingQuality] <= Math.min(...records.map((record) => ranks[record.timingQuality])), 'cannot invent finer ASR alignment');
      const modes = [...new Set(records.map((record) => record.source.mode))];
      requireContract(unit.asrSource.mode === (modes.length === 1 ? modes[0] : 'MIXED'), 'unit ASR provenance mismatch');
    } else {
      requireContract(unit.originalText === '' && !unit.transcriptRefs.length && unit.timingQuality === 'NONE' && ['NO_SPEECH', 'UNAVAILABLE'].includes(unit.asrSource.mode), 'visual-only unit cannot invent speech');
      if (unit.asrSource.mode === 'NO_SPEECH') requireContract(!index.transcripts.some((record) => record.sourceRange.startMs < unit.sourceRange.endMs && unit.sourceRange.startMs < record.sourceRange.endMs), 'NO_SPEECH contradicts indexed transcript');
    }
    unique(unit.dependencies.map((dependency) => dependency.unitId), 'dependency');
    requireContract(unit.dependencies.every((dependency) => units.has(dependency.unitId) && dependency.unitId !== unit.unitId), 'unknown/self dependency');
  }
}
function validateDecision(decision: DirectorDecisionV1, index: MaterialIndexV1) {
  requireContract(equal(decision.indexRef, { indexId: index.indexId, indexVersion: index.indexVersion, indexHash: index.indexHash }), 'decision index binding mismatch');
  unique(decision.rows.map((row) => row.rowId), 'rowId');
  unique(decision.rows.flatMap((row) => row.packagingSuggestions.map((proposal) => proposal.suggestionId)), 'suggestionId');
  const units = new Map(index.units.map((unit) => [unit.unitId, unit]));
  const selected = decision.rows.flatMap((row) => row.sourceUnitRefs);
  unique(selected, 'selected unit');
  requireContract(selected.every((ref) => units.has(ref)), 'unknown selected unit');
  let previousEnd = 0;
  for (const row of decision.rows) {
    const rowUnits = row.sourceUnitRefs.map((ref) => units.get(ref)!);
    requireContract(rowUnits[0].sourceRange.startMs >= previousEnd, 'source order changed or overlaps');
    for (let i = 1; i < rowUnits.length; i++) requireContract(rowUnits[i - 1].sourceRange.endMs === rowUnits[i].sourceRange.startMs, 'noncontiguous units must use separate rows');
    previousEnd = rowUnits[rowUnits.length - 1].sourceRange.endMs;
  }
  for (const ref of selected) requireContract(units.get(ref)!.dependencies.every((dependency) => dependency.level !== 'REQUIRED' || selected.includes(dependency.unitId)), 'required dependency removed');
}
async function validateScript(script: EditingScriptV1, index: MaterialIndexV1, decision: DirectorDecisionV1) {
  requireContract(equal(script.assetRef, index.assetRef) && equal(script.indexRef, decision.indexRef) && script.inputHash === decision.inputHash, 'script input/index binding mismatch');
  requireContract(script.scriptHash === await scriptHash(script), 'scriptHash mismatch');
  requireContract(script.validationReport.candidateHash === script.scriptHash, 'validation belongs to another candidate');
  requireContract(!script.quality || script.quality.candidateHash === script.scriptHash, 'QA belongs to another candidate');
  requireContract(script.target.desiredDurationMs === null || script.target.desiredDurationMs <= script.target.maxDurationMs, 'desired duration exceeds hard maximum');
  requireContract(equal(script.rows.map((row) => row.rowId), decision.rows.map((row) => row.rowId)), 'script rows differ from decision');
  for (const values of [script.riskItems.map((risk) => risk.riskId), script.captionCues.map((cue) => cue.cueId), script.executableActions.map((action) => action.actionId), script.packagingSuggestions.map((proposal) => proposal.suggestionId)]) unique(values, 'script item ID');
  const units = new Map(index.units.map((unit) => [unit.unitId, unit]));
  const frames = new Map(index.observations.map((frame) => [frame.frameId, frame]));
  const rows = new Map(script.rows.map((row) => [row.rowId, row]));
  const risks = new Map(script.riskItems.map((risk) => [risk.riskId, risk]));
  const selected = new Set(script.rows.flatMap((row) => row.sourceUnitRefs));
  for (const risk of script.riskItems) {
    unique(risk.rowRefs, 'risk row reference'); unique(risk.unitRefs, 'risk unit reference');
    requireContract(risk.rowRefs.every((ref) => rows.has(ref)) && risk.unitRefs.every((ref) => units.has(ref)), 'unknown risk reference');
  }
  const sameSet = (a: string[], b: string[]) => equal([...new Set(a)].sort(), [...new Set(b)].sort());
  requireContract(sameSet(script.validationReport.issueRefs, [...risks.keys()]), 'validation must list all risks');
  requireContract(script.validationReport.hardPassed === !script.riskItems.some((risk) => risk.level === 'HARD'), 'hard gate and hard risks disagree');
  if (script.quality) {
    unique(script.quality.issueRefs, 'QA issue reference');
    requireContract(script.quality.issueRefs.every((ref) => risks.has(ref)), 'unknown QA risk reference');
    requireContract(script.quality.passed || script.quality.issueRefs.length, 'failed QA requires risk references');
  }
  let elapsed = 0, riskySource = false;
  for (let number = 0; number < script.rows.length; number++) {
    const row = script.rows[number], chosen = decision.rows[number];
    requireContract(row.shotNo === number + 1 && equal(row.sourceUnitRefs, chosen.sourceUnitRefs) && row.narrativeRole === chosen.narrativeRole && row.selectionReason === chosen.selectionReason, 'script decision projection changed');
    const rowUnits = row.sourceUnitRefs.map((ref) => units.get(ref)!);
    requireContract(equal(row.sourceParts, rowUnits.map((unit) => ({ unitId: unit.unitId, sourceRange: unit.sourceRange }))), 'source parts must map whole index units');
    const length = rowUnits.reduce((total, unit) => total + unit.sourceRange.endMs - unit.sourceRange.startMs, 0);
    requireContract(equal(row.outputRange, { startMs: elapsed, endMs: elapsed + length }), 'output time must be cumulative original speed');
    elapsed += length;
    requireContract(equal(row.spokenQuotes, rowUnits.filter((unit) => unit.kind === 'SPEECH').map((unit) => ({ unitId: unit.unitId, text: unit.originalText }))), 'spoken quote differs from original');
    const frameIds = [...new Set(rowUnits.flatMap((unit) => unit.frameRefs))];
    requireContract(equal(row.visualEvidence, frameIds.map((ref) => ({ frameId: ref, observedDescription: frames.get(ref)!.description }))), 'visual fact differs from indexed observation');
    requireContract(equal(row.dependencyRefs, [...new Set(rowUnits.flatMap((unit) => unit.dependencies.map((dependency) => dependency.unitId)))]), 'dependency projection changed');
    unique(row.riskRefs, 'row risk reference');
    requireContract(sameSet(row.riskRefs, script.riskItems.filter((risk) => risk.rowRefs.includes(row.rowId)).map((risk) => risk.riskId)), 'row risk projection changed');
    for (const unit of rowUnits) {
      const codes = script.riskItems.filter((risk) => risk.rowRefs.includes(row.rowId) && risk.unitRefs.includes(unit.unitId)).map((risk) => risk.code);
      if (unit.timingQuality === 'COARSE_BLOCK') requireContract(codes.includes('COARSE_ALIGNMENT'), 'coarse alignment must be disclosed');
      if (!['REAL', 'NO_SPEECH'].includes(unit.asrSource.mode)) {
        requireContract(codes.includes('UNTRUSTED_SOURCE'), 'untrusted ASR must be disclosed'); riskySource = true;
      }
      if (!unit.frameRefs.length || unit.frameRefs.some((ref) => frames.get(ref)!.source.mode !== 'REAL')) {
        requireContract(codes.includes('VISUAL_UNVERIFIED'), 'unverified visual evidence must be disclosed'); riskySource = true;
      }
      if (unit.dependencies.some((dependency) => dependency.level === 'REVIEW' && !selected.has(dependency.unitId))) requireContract(codes.includes('MISSING_DEPENDENCY'), 'missing review dependency must be disclosed');
    }
  }
  requireContract(elapsed === script.estimatedDurationMs && elapsed <= script.target.maxDurationMs, 'duration must be exact and within hard maximum');
  const cues = new Map(script.captionCues.map((cue) => [cue.cueId, cue])), cueUnits = new Set<string>();
  let previousCaptionEnd = 0;
  for (const cue of script.captionCues) {
    const row = rows.get(cue.rowId), unit = units.get(cue.unitId);
    requireContract(row && unit && row.sourceUnitRefs.includes(cue.unitId) && unit.kind === 'SPEECH' && unit.asrSource.mode === 'REAL' && cue.timingQuality === unit.timingQuality, 'caption requires reliable original alignment');
    requireContract(!cueUnits.has(cue.unitId) && cue.text === unit.originalText, 'caption must quote an entire aligned unit once');
    cueUnits.add(cue.unitId);
    const offset = row.sourceUnitRefs.slice(0, row.sourceUnitRefs.indexOf(cue.unitId)).reduce((total, ref) => total + units.get(ref)!.sourceRange.endMs - units.get(ref)!.sourceRange.startMs, 0);
    requireContract(equal(cue.outputRange, { startMs: row.outputRange.startMs + offset, endMs: row.outputRange.startMs + offset + unit.sourceRange.endMs - unit.sourceRange.startMs }), 'caption must use global output time');
    requireContract(cue.outputRange.startMs >= previousCaptionEnd, 'captions must be ordered without overlap');
    previousCaptionEnd = cue.outputRange.endMs;
  }
  if (script.target.subtitleRequested) for (const row of script.rows) for (const ref of row.sourceUnitRefs) {
    if (units.get(ref)!.kind === 'SPEECH' && !cueUnits.has(ref)) requireContract(script.riskItems.some((risk) => risk.code === 'SUBTITLE_UNAVAILABLE' && risk.rowRefs.includes(row.rowId) && risk.unitRefs.includes(ref)), 'unmet subtitle requirement must be disclosed');
  }
  const usedCues: string[] = [], audioRows: string[] = [];
  for (const action of script.executableActions) {
    requireContract(rows.has(action.rowId), 'action references unknown row');
    if (action.type === 'CAPTION') {
      requireContract(action.cueId !== null && cues.has(action.cueId) && cues.get(action.cueId)!.rowId === action.rowId, 'action references foreign caption');
      usedCues.push(action.cueId);
    } else { requireContract(action.cueId === null, 'audio action cannot reference caption'); audioRows.push(action.rowId); }
  }
  requireContract(equal(usedCues.sort(), [...cues.keys()].sort()), 'each caption must have exactly one action');
  requireContract(equal(audioRows.sort(), [...rows.keys()].sort()), 'each row must preserve original audio exactly once');
  const proposed = decision.rows.flatMap((row) => row.packagingSuggestions.map((proposal) => ({ rowId: row.rowId, proposal })));
  requireContract(proposed.length === script.packagingSuggestions.length, 'packaging projection changed');
  proposed.forEach(({ rowId, proposal }, i) => requireContract(script.packagingSuggestions[i].rowId === rowId && equal(proposal, without(script.packagingSuggestions[i], ['rowId', 'status'])), 'packaging proposal changed'));
  if (script.reviewStatus === 'READY') requireContract(script.validationReport.hardPassed && !risks.size && !riskySource && script.quality?.passed, 'READY requires hard and semantic review');
  if (!script.quality) requireContract(script.riskItems.some((risk) => risk.code === 'QA_UNAVAILABLE'), 'missing QA must be disclosed');
}
async function validateSubmission(submission: TaskSubmissionV1) {
  requireContract(submission.input.assetId === submission.assetRef.assetId, 'selected asset mismatch');
  requireContract(submission.inputHash === await inputHash(submission), 'inputHash mismatch');
  requireContract(submission.input.target.desiredDurationMs === null || submission.input.target.desiredDurationMs <= submission.input.target.maxDurationMs, 'desired duration exceeds hard maximum');
  requireContract(submission.mediaObjectKey.split('/').every((part) => !['', '.', '..'].includes(part)), 'media key must be an object key, not a filesystem path');
}
function validateEvent(event: TaskEventV1, submission: TaskSubmissionV1) {
  requireContract(new Date(event.heartbeatAt).toISOString() === event.heartbeatAt.replace('Z', '.000Z'), 'invalid UTC heartbeat');
  for (const field of ['taskId', 'projectId', 'runId', 'attempt', 'inputHash'] as const) requireContract(event[field] === submission[field], 'event belongs to another run/input');
  requireContract(event.requestId === submission.input.requestId && event.assetId === submission.assetRef.assetId && event.assetHash === submission.assetRef.assetHash, 'event input identity mismatch');
  if (event.event === 'PROGRESS') requireContract(event.executionStatus === 'RUNNING' && event.progress < 100 && !['COMPLETED', 'FAILED'].includes(event.phase) && event.analysisOutcome === 'NONE' && event.reviewStatus === 'NOT_AVAILABLE' && event.resultRefs === null && event.error === null, 'progress cannot publish a terminal result');
  else if (event.executionStatus === 'SUCCESS') {
    requireContract(event.progress === 100 && event.phase === 'COMPLETED' && ['COMPLETE', 'PARTIAL'].includes(event.analysisOutcome) && ['READY', 'NEEDS_REVIEW'].includes(event.reviewStatus) && event.resultRefs !== null && event.error === null, 'successful completion requires qualified result references');
    requireContract(event.analysisOutcome !== 'PARTIAL' || event.reviewStatus === 'NEEDS_REVIEW', 'partial result cannot be READY');
  } else requireContract(event.executionStatus === 'FAILED' && event.phase === 'FAILED' && event.progress < 100 && event.analysisOutcome === 'NONE' && event.reviewStatus === 'NOT_AVAILABLE' && event.resultRefs === null && event.error !== null, 'failure cannot carry a normal result');
}

/** Requires immutable index/decision context; JSON Schema alone cannot validate references. */
export async function parseScriptContractBundleV1(value: unknown): Promise<ScriptContractBundleV1> {
  requireContract(shape(value), 'B1 structure: ' + JSON.stringify(shape.errors));
  const bundle = value as ScriptContractBundleV1, { materialIndex: index, decision, script, submission, events } = bundle;
  await validateSubmission(submission);
  if (index) { await validateIndex(index); requireContract(equal(index.assetRef, submission.assetRef), 'index asset binding mismatch'); }
  if (decision) {
    requireContract(index, 'decision requires its index context'); validateDecision(decision, index);
    requireContract(decision.inputHash === submission.inputHash, 'decision input binding mismatch');
  }
  if (script) {
    requireContract(index && decision, 'script requires its decision context'); await validateScript(script, index, decision);
    requireContract(script.projectId === submission.projectId && script.generationTaskId === submission.taskId && equal(script.target, submission.input.target), 'script task/target binding mismatch');
  }
  unique(events.map((event) => event.eventId), 'accepted eventId');
  let progress = 0, sequence = 0, terminal = false;
  for (const event of events) {
    validateEvent(event, submission);
    requireContract(!terminal && event.sequence > sequence && event.progress >= progress, 'accepted history cannot regress or revive a terminal task');
    progress = event.progress; sequence = event.sequence; terminal = event.event === 'COMPLETED';
    if (event.executionStatus === 'SUCCESS') {
      requireContract(script && index && event.resultRefs, 'successful result requires artifacts');
      requireContract(script.validationReport.hardPassed, 'hard-invalid script cannot be a successful result');
      requireContract(equal(event.resultRefs.analysis, index.analysisRef), 'analysis result binding mismatch');
      requireContract(equal(event.resultRefs.materialIndex, { artifactId: index.indexId, revision: index.indexVersion, contentHash: index.indexHash }), 'index result binding mismatch');
      requireContract(equal(event.resultRefs.script, { artifactId: script.scriptId, revision: script.revision, contentHash: script.scriptHash }), 'script result binding mismatch');
      requireContract(event.reviewStatus === (script.reviewStatus === 'READY' ? 'READY' : 'NEEDS_REVIEW'), 'event review state differs from script');
    }
    if (event.executionStatus === 'FAILED') requireContract(!script && !decision && !index, 'failed result cannot carry qualified artifacts');
  }
  return bundle;
}
