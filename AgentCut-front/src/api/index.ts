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
  outputPath: string;
  duration: number;
  size: number;
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

/** 保存方案（后端未开放，预留签名，TODO：savePlan 需完整反序列化） */
// export function savePlan(projectId: string, plan: Plan): Promise<Plan> {
//   return client.put<Plan>(`/plans/${projectId}`, plan).then((r) => r.data);
// }
