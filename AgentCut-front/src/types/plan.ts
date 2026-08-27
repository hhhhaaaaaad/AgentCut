/**
 * 剪辑方案 TypeScript 类型定义
 *
 * 唯一契约源：E:\java\AgentCut\docs\plan-schema.json
 * 后端 GET /api/v1/plans/{projectId} 返回的 JSON 即对齐此类型。
 * 核心原则：方案文档是单一事实来源 —— Agent 生成、人编辑、引擎执行、系统存档共用同一份文档。
 */

/** 源时间区间（绝对浮点秒） */
export interface TimeRange {
  start: number;
  end: number;
}

/** 输出配置 */
export interface OutputConfig {
  width: number;
  height: number;
  fps: number;
  codec?: string;
  bitrate?: string;
}

/** 背景音乐（global 级） */
export interface Bgm {
  url: string;
  volume?: number;
  loop?: boolean;
}

/** 字幕样式 */
export interface SubtitleStyle {
  fontSize?: number;
  color?: string;
  position?: 'top' | 'bottom' | 'center';
}

/** 全局设置 */
export interface Global {
  output: OutputConfig;
  bgm?: Bgm;
  subtitleStyle?: SubtitleStyle;
}

/** 源视频信息（来自 ffprobe） */
export interface Source {
  assetId: string;
  url: string;
  duration: number;
  fps: number;
  width: number;
  height: number;
}

/* ==================== 操作（判别联合） ==================== */

/** 操作类型名 */
export type OperationType = 'speed' | 'crop' | 'subtitle' | 'volume' | 'mute';

/** 原子剪辑操作：以 type 字段区分，判别联合（discriminated union） */
export type Operation = SpeedOp | CropOp | SubtitleOp | VolumeOp | MuteOp;

/** 变速 */
export interface SpeedOp {
  type: 'speed';
  rate: number;
}

/** 裁切 */
export interface CropOp {
  type: 'crop';
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 字幕 */
export interface SubtitleOp {
  type: 'subtitle';
  text: string;
  start: number;
  end: number;
}

/** 音量 */
export interface VolumeOp {
  type: 'volume';
  volume: number;
}

/** 静音（无参数） */
export interface MuteOp {
  type: 'mute';
}

/* ==================== 片段 / 转场 / 方案 ==================== */

/** 时间线片段（顺序即最终成片顺序） */
export interface Segment {
  id: string;
  keep: boolean;
  sourceRange: TimeRange;
  operations?: Operation[];
}

/** 转场 */
export interface Transition {
  from: string;
  to: string;
  type: 'fade' | 'none';
  duration?: number;
}

/** 剪辑方案（顶层文档） */
export interface Plan {
  schemaVersion: '1.0';
  planVersion: number;
  projectId: string;
  title?: string;
  source: Source;
  global: Global;
  timeline: Segment[];
  transitions?: Transition[];
}

/* ==================== 辅助：编辑器用 ==================== */

/** 操作类型中文文案 */
export const OPERATION_LABELS: Record<OperationType, string> = {
  speed: '变速',
  crop: '裁切',
  subtitle: '字幕',
  volume: '音量',
  mute: '静音',
};

/** 新增操作时的参数模板 */
export function createOperation(type: OperationType): Operation {
  switch (type) {
    case 'speed':
      return { type: 'speed', rate: 1.0 };
    case 'crop':
      return { type: 'crop', x: 0, y: 0, width: 1080, height: 1920 };
    case 'subtitle':
      return { type: 'subtitle', text: '', start: 0, end: 0 };
    case 'volume':
      return { type: 'volume', volume: 1.0 };
    case 'mute':
      return { type: 'mute' };
  }
}

/** 空方案工厂（便于前端在无后端时构造演示数据） */
export function createEmptyPlan(projectId: string): Plan {
  return {
    schemaVersion: '1.0',
    planVersion: 1,
    projectId,
    source: {
      assetId: '',
      url: '',
      duration: 0,
      fps: 30,
      width: 1920,
      height: 1080,
    },
    global: {
      output: { width: 1080, height: 1920, fps: 30 },
    },
    timeline: [],
  };
}
