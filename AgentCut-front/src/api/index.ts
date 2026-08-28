import client from './client';
import type { Plan } from '../types/plan';

/* ==================== 接口 DTO ==================== */

/** 项目 */
export interface Project {
  projectId: string;
  userId?: string;
  title: string;
  status: string;
}

/** 创建项目请求体 */
export interface CreateProjectRequest {
  userId?: string;
  title: string;
}

/** 发起分析请求体（用户意图，显式传入，替代长期记忆） */
export interface AnalyzeRequest {
  aspectRatio: string;
  maxDuration: number;
  addSubtitle: boolean;
  style: string;
}

/** 发起分析的结果 */
export interface AnalyzeResult {
  taskId: string;
  status: string;
  progress: number;
}

/** 任务类型 */
export type TaskType = 'ANALYZE' | 'RENDER';

/** 任务（状态机 PENDING → RUNNING → SUCCESS / FAILED） */
export interface Task {
  taskId: string;
  type?: TaskType;
  status: string;
  progress: number;
  resultJson?: string;
}

/** 应用方案的结果（成片元信息） */
export interface ApplyResult {
  taskId?: string;
  outputPath: string;
  duration: number;
  size: number;
}

/** 素材（源视频/成片/BGM/封面） */
export interface Asset {
  assetId: string;
  projectId: string;
  type: string;
  ossUrl: string;
  fileName: string;
  size: number;
  duration: number;
  width: number;
  height: number;
  fps: number;
}

/* ==================== 接口封装 ==================== */

/** 创建项目 */
export function createProject(req: CreateProjectRequest): Promise<Project> {
  return client.post<Project>('/projects', req).then((r) => r.data);
}

/** 查询项目 */
export function getProject(projectId: string): Promise<Project> {
  return client.get<Project>(`/projects/${projectId}`).then((r) => r.data);
}

/** 发起分析（返回 taskId，进度通过轮询任务接口获取） */
export function analyzeProject(projectId: string, req: AnalyzeRequest): Promise<AnalyzeResult> {
  return client.post<AnalyzeResult>(`/projects/${projectId}/analyze`, req).then((r) => r.data);
}

/** 查询任务状态 / 进度 */
export function getTask(taskId: string): Promise<Task> {
  return client.get<Task>(`/tasks/${taskId}`).then((r) => r.data);
}

/** 获取剪辑方案（对齐 plan-schema.json） */
export function getPlan(projectId: string): Promise<Plan> {
  return client.get<Plan>(`/plans/${projectId}`).then((r) => r.data);
}

/** 获取方案版本列表 */
export function getPlanVersions(projectId: string): Promise<string[]> {
  return client.get<string[]>(`/plans/${projectId}/versions`).then((r) => r.data);
}

/** 回滚到指定版本 */
export function rollbackPlan(projectId: string, version: number): Promise<string> {
  return client
    .post<string>(`/plans/${projectId}/versions/${version}/rollback`)
    .then((r) => r.data);
}

/** 应用方案（出成片） */
export function applyPlan(projectId: string): Promise<ApplyResult> {
  return client.post<ApplyResult>(`/plans/${projectId}/apply`).then((r) => r.data);
}

/** 成片下载直链（后端流式返回，Content-Disposition: attachment） */
export function renderDownloadUrl(taskId: string): string {
  return `${client.defaults.baseURL}/render/${taskId}/download`;
}

/** 上传源视频（multipart/form-data，字段名 file） */
export function uploadVideo(projectId: string, file: File): Promise<Asset> {
  const formData = new FormData();
  formData.append('file', file);
  return client
    .post<Asset>(`/projects/${projectId}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data);
}

/** 保存方案（生成新版本） */
export function savePlan(projectId: string, plan: Plan): Promise<void> {
  return client.put<void>(`/plans/${projectId}`, plan).then(() => undefined);
}
