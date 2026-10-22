import Ajv from 'ajv';
import schema from '../../../docs/plan-schema.json' with { type: 'json' };
import type { Plan, Segment } from '../types/plan';
import type { Task } from '../api';

const validateShape = new Ajv({ allErrors: true, strict: false, validateFormats: false }).compile<Plan>(schema);
export const TERMINAL_STATUSES = new Set(['SUCCESS', 'FAILED', 'NEEDS_REVIEW']);
export const isTaskDone = (task: Task | null) => !!task && TERMINAL_STATUSES.has(task.status);

export function savedPlanVersion(plan: Plan | null, versions: string[]): number | null {
  const saved = versions.map(Number).filter((value) => Number.isInteger(value) && value > 0);
  return saved.length ? Math.max(...saved) : plan?.planVersion ?? null;
}

export function isRenderedPlanCurrent(plan: Plan | null, renderedPlan: Plan | null, dirty: boolean): boolean {
  return !dirty && !!plan && !!renderedPlan && JSON.stringify(plan) === JSON.stringify(renderedPlan);
}

export function mergeTask(current: Task | null, incoming: Task): Task {
  if (!current || current.taskId !== incoming.taskId) return incoming;
  if (isTaskDone(current)) return current;
  return { ...incoming, progress: Math.max(current.progress || 0, Math.min(100, incoming.progress || 0)) };
}

export function validatePlan(value: unknown): string | null {
  if (!validateShape(value)) {
    const error = validateShape.errors?.[0];
    return `方案格式有误：${error?.instancePath || '/'} ${error?.message || ''}`;
  }
  const plan = value as Plan;
  const ids = new Set<string>();
  for (const segment of plan.timeline) {
    if (ids.has(segment.id)) return `片段 ID 重复：${segment.id}`;
    ids.add(segment.id);
    const { start, end } = segment.sourceRange;
    if (start >= end) return `${segment.id}：结束时间必须大于开始时间`;
    if (plan.source.duration > 0 && end > plan.source.duration + 0.001) return `${segment.id}：源时间超出原视频时长`;
    if (!segment.keep && segment.operations?.length) return `${segment.id}：删除的片段不能携带段内操作`;
    const segmentDuration = outputDuration([{ ...segment, keep: true }]);
    for (const operation of segment.operations || []) {
      if (operation.type === 'subtitle' && (operation.start >= operation.end || operation.end > segmentDuration + .001)) return `${segment.id}：字幕时间必须位于此片段输出时长 0—${segmentDuration.toFixed(2)} 秒内`;
      if (operation.type === 'crop' && (operation.x + operation.width > plan.source.width || operation.y + operation.height > plan.source.height)) return `${segment.id}：裁切范围超出源视频尺寸`;
    }
  }
  for (const transition of plan.transitions || []) {
    if (!ids.has(transition.from) || !ids.has(transition.to)) return '转场引用了不存在的片段';
  }
  return null;
}

/** Java responses include null optional fields; keep required-field validation strict. */
export function omitNullFields(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(omitNullFields);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).filter(([, entry]) => entry !== null).map(([key, entry]) => [key, omitNullFields(entry)]));
  return value;
}

export function outputDuration(timeline: Segment[]): number {
  return timeline.filter((segment) => segment.keep).reduce((total, segment) => {
    const speed = (segment.operations || []).find((op) => op.type === 'speed');
    return total + Math.max(0, segment.sourceRange.end - segment.sourceRange.start) / (speed?.type === 'speed' ? speed.rate : 1);
  }, 0);
}
