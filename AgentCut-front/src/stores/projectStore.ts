import { create } from 'zustand';
import type { Plan } from '../types/plan';
import type { AnalysisFlags, ApplyResult, Asset, Project, Task } from '../api';
import { mergeTask, savedPlanVersion } from '../lib/plan';

/**
 * 全局项目状态：当前项目 / 分析任务 / 剪辑方案 / 版本列表 / 分析可信度标志。
 * 各页面通过此 store 共享数据，避免层层传参。
 */
interface ProjectState {
  project: Project | null;
  task: Task | null;
  plan: Plan | null;
  planVersions: string[];
  /** 分析可信度标志（降级 / 质量），驱动告警横幅 */
  analysisFlags: AnalysisFlags | null;
  asset: Asset | null;
  sourcePreviewUrl: string | null;
  renderResult: ApplyResult | null;
  renderedPlanVersion: number | null;
  renderedPlan: Plan | null;
  planDirty: boolean;
  demo: boolean;
  uploading: boolean;
  uploadProgress: number;

  setProject: (project: Project | null) => void;
  setTask: (task: Task | null) => void;
  setPlan: (plan: Plan | null) => void;
  setPlanVersions: (versions: string[]) => void;
  setAnalysisFlags: (flags: AnalysisFlags | null) => void;
  setAsset: (asset: Asset, previewUrl?: string) => void;
  editPlan: (plan: Plan) => void;
  setRenderResult: (result: ApplyResult, plan: Plan) => void;
  setUploading: (uploading: boolean) => void;
  setUploadProgress: (uploadProgress: number) => void;
  /** 清空全部（如新建项目前） */
  reset: () => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  project: null,
  task: null,
  plan: null,
  planVersions: [],
  analysisFlags: null,
  asset: null,
  sourcePreviewUrl: null,
  renderResult: null,
  renderedPlanVersion: null,
  renderedPlan: null,
  planDirty: false,
  demo: false,
  uploading: false,
  uploadProgress: 0,

  setProject: (project) => set((state) => {
    if (state.sourcePreviewUrl) URL.revokeObjectURL(state.sourcePreviewUrl);
    return { project, asset: null, sourcePreviewUrl: null, task: null, plan: null, planDirty: false,
      analysisFlags: null, renderResult: null, renderedPlanVersion: null, renderedPlan: null, planVersions: [] };
  }),
  setTask: (task) => set((state) => ({ task: task ? mergeTask(state.task, task) : null })),
  setPlan: (plan) => set({ plan, planDirty: false }),
  editPlan: (plan) => set({ plan, planDirty: true }),
  setAsset: (asset, previewUrl) => set((state) => {
    if (state.sourcePreviewUrl) URL.revokeObjectURL(state.sourcePreviewUrl);
    return { asset, sourcePreviewUrl: previewUrl || null, plan: null, planDirty: false, planVersions: [],
      task: null, analysisFlags: null, renderResult: null, renderedPlanVersion: null, renderedPlan: null };
  }),
  setRenderResult: (renderResult, plan) => set((state) => ({ renderResult, renderedPlanVersion: savedPlanVersion(plan, state.planVersions), renderedPlan: structuredClone(plan) })),
  setUploading: (uploading) => set({ uploading }),
  setUploadProgress: (uploadProgress) => set({ uploadProgress }),
  setPlanVersions: (planVersions) => set({ planVersions }),
  setAnalysisFlags: (analysisFlags) => set({ analysisFlags }),
  reset: () => set((state) => {
    if (state.sourcePreviewUrl) URL.revokeObjectURL(state.sourcePreviewUrl);
    return { project: null, task: null, plan: null, planVersions: [], analysisFlags: null,
      asset: null, sourcePreviewUrl: null, renderResult: null, renderedPlanVersion: null, renderedPlan: null, planDirty: false };
  }),
}));
